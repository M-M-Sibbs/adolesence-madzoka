from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from database import get_db
from auth import get_current_user, require_admin
import models
import json

quiz_router = APIRouter(prefix="/quizzes", tags=["quizzes"])
progress_router = APIRouter(prefix="/progress", tags=["progress"])

class QuizCreate(BaseModel):
    lesson_id: int
    question: str
    type: str = "multiple_choice"
    options: Optional[List[str]] = []
    correct_answer: str
    explanation: Optional[str] = ""

class QuizSubmit(BaseModel):
    lesson_id: int
    answers: List[dict]  # [{quiz_id, answer}]

class ProgressUpdate(BaseModel):
    lesson_id: int
    last_position: Optional[int] = None
    completed: Optional[bool] = None

# --- QUIZ ROUTES ---

@quiz_router.get("/lesson/{lesson_id}")
def get_lesson_quizzes(
    lesson_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    quizzes = db.query(models.Quiz).filter(models.Quiz.lesson_id == lesson_id).all()
    result = []
    for q in quizzes:
        d = {
            "id": q.id,
            "question": q.question,
            "type": q.type.value,
            "options": json.loads(q.options) if q.options else [],
        }
        # Only include answer for admins or after submission
        if current_user.role == models.UserRole.admin:
            d["correct_answer"] = q.correct_answer
            d["explanation"] = q.explanation
        result.append(d)
    return result

@quiz_router.post("")
def create_quiz(
    data: QuizCreate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin)
):
    lesson = db.query(models.Lesson).filter(models.Lesson.id == data.lesson_id).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")

    quiz = models.Quiz(
        lesson_id=data.lesson_id,
        question=data.question,
        type=models.QuestionType(data.type),
        options=json.dumps(data.options),
        correct_answer=data.correct_answer,
        explanation=data.explanation
    )
    db.add(quiz)
    db.commit()
    db.refresh(quiz)
    return {"id": quiz.id, "message": "Quiz created"}

@quiz_router.post("/bulk")
def create_bulk_quizzes(
    lesson_id: int,
    quizzes: List[QuizCreate],
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin)
):
    created = []
    for q in quizzes:
        quiz = models.Quiz(
            lesson_id=lesson_id,
            question=q.question,
            type=models.QuestionType(q.type),
            options=json.dumps(q.options or []),
            correct_answer=q.correct_answer,
            explanation=q.explanation
        )
        db.add(quiz)
        created.append(quiz)
    db.commit()
    return {"created": len(created)}

@quiz_router.post("/submit")
def submit_quiz(
    data: QuizSubmit,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    total = len(data.answers)
    if total == 0:
        return {"score": 0, "correct": 0, "total": 0, "results": []}

    correct_count = 0
    results = []
    for answer in data.answers:
        quiz = db.query(models.Quiz).filter(models.Quiz.id == answer.get("quiz_id")).first()
        if not quiz:
            continue
        is_correct = str(answer.get("answer", "")).strip().lower() == str(quiz.correct_answer).strip().lower()
        if is_correct:
            correct_count += 1
        results.append({
            "quiz_id": quiz.id,
            "is_correct": is_correct,
            "correct_answer": quiz.correct_answer,
            "explanation": quiz.explanation
        })

    score = (correct_count / total) * 100 if total > 0 else 0

    # Update progress
    progress = db.query(models.Progress).filter(
        models.Progress.user_id == current_user.id,
        models.Progress.lesson_id == data.lesson_id
    ).first()
    if not progress:
        progress = models.Progress(user_id=current_user.id, lesson_id=data.lesson_id)
        db.add(progress)

    progress.score = max(progress.score or 0, score)
    progress.quiz_attempts = (progress.quiz_attempts or 0) + 1
    if score >= 70:
        progress.completed = True
    db.commit()

    return {
        "score": round(score, 1),
        "correct": correct_count,
        "total": total,
        "results": results,
        "passed": score >= 70
    }

@quiz_router.delete("/{quiz_id}")
def delete_quiz(
    quiz_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin)
):
    quiz = db.query(models.Quiz).filter(models.Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    db.delete(quiz)
    db.commit()
    return {"message": "Deleted"}

# --- PROGRESS ROUTES ---

@progress_router.get("/me")
def my_progress(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    progress_list = db.query(models.Progress).filter(
        models.Progress.user_id == current_user.id
    ).all()
    lessons_completed = sum(1 for p in progress_list if p.completed)
    avg_score = sum(p.score or 0 for p in progress_list) / len(progress_list) if progress_list else 0
    ai_sessions = db.query(models.AIChat).filter(models.AIChat.user_id == current_user.id).count()

    return {
        "lessons_completed": lessons_completed,
        "lessons_in_progress": len(progress_list) - lessons_completed,
        "average_score": round(avg_score, 1),
        "ai_sessions": ai_sessions,
        "details": [
            {
                "lesson_id": p.lesson_id,
                "completed": p.completed,
                "score": p.score,
                "last_position": p.last_position,
                "quiz_attempts": p.quiz_attempts,
            }
            for p in progress_list
        ]
    }

@progress_router.post("/update")
def update_progress(
    data: ProgressUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    progress = db.query(models.Progress).filter(
        models.Progress.user_id == current_user.id,
        models.Progress.lesson_id == data.lesson_id
    ).first()
    if not progress:
        progress = models.Progress(user_id=current_user.id, lesson_id=data.lesson_id)
        db.add(progress)

    if data.last_position is not None:
        progress.last_position = data.last_position
    if data.completed is not None:
        progress.completed = data.completed

    db.commit()
    return {"updated": True}