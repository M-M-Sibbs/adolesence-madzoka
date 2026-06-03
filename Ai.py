from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from database import get_db, settings
from auth import get_current_user
import models
import google.generativeai as genai
import uuid

router = APIRouter(prefix="/ai", tags=["ai"])

LEARNING_MODES = {
    "explain": "You are a helpful tutor. Explain concepts clearly and thoroughly.",
    "beginner": "You are a patient teacher. Explain everything like the student is 10 years old. Use very simple language, analogies, and examples.",
    "advanced": "You are an expert mentor. Provide deep technical explanations, discuss edge cases, best practices, and advanced concepts.",
    "quiz": "You are a quiz master. Generate practice questions based on the lesson content. Give feedback on answers.",
}

class ChatRequest(BaseModel):
    message: str
    lesson_id: Optional[int] = None
    session_id: Optional[str] = None
    learning_mode: str = "explain"
    conversation_history: Optional[List[dict]] = []

class QuizGenerateRequest(BaseModel):
    lesson_id: int
    count: int = 5

def get_lesson_context(lesson: models.Lesson) -> str:
    context = f"""LESSON CONTEXT:
Title: {lesson.title}
Category: {lesson.category}
Difficulty: {lesson.difficulty.value}

Description: {lesson.description or 'N/A'}

Lesson Content:
{lesson.content or 'No content provided'}
"""
    if lesson.transcript:
        context += f"\n\nPDF/Notes Content:\n{lesson.transcript[:3000]}"
    return context

@router.post("/chat")
async def chat(
    req: ChatRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not settings.GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="AI service not configured. Please set GEMINI_API_KEY.")

    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash")

    lesson = None
    lesson_context = ""
    if req.lesson_id:
        lesson = db.query(models.Lesson).filter(models.Lesson.id == req.lesson_id).first()
        if lesson:
            lesson_context = get_lesson_context(lesson)

    mode_instruction = LEARNING_MODES.get(req.learning_mode, LEARNING_MODES["explain"])

    system_prompt = f"""You are Adolescence AI Tutor — an intelligent educational assistant.

{mode_instruction}

PLATFORM: Adolescence Learning Platform
STUDENT: {current_user.name}

{lesson_context if lesson_context else "The student is asking a general question not tied to a specific lesson."}

RULES:
- Always be encouraging and supportive
- Use code examples when relevant (use markdown code blocks)
- If asked about something outside the lesson, gently redirect while still helping
- Keep answers focused and educational
- Format responses with clear structure when needed
"""

    # Build conversation
    history = []
    for msg in (req.conversation_history or [])[-10:]:  # last 10 messages for context
        role = "user" if msg.get("role") == "user" else "model"
        history.append({"role": role, "parts": [msg.get("content", "")]})

    try:
        chat_session = model.start_chat(history=history)
        full_message = f"{system_prompt}\n\nStudent question: {req.message}"
        response = chat_session.send_message(full_message)
        ai_response = response.text
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI error: {str(e)}")

    # Store in DB
    session_id = req.session_id or str(uuid.uuid4())
    chat_record = models.AIChat(
        user_id=current_user.id,
        lesson_id=req.lesson_id,
        session_id=session_id,
        message=req.message,
        response=ai_response,
        learning_mode=req.learning_mode
    )
    db.add(chat_record)
    db.commit()

    return {
        "response": ai_response,
        "session_id": session_id,
        "lesson_id": req.lesson_id
    }

@router.post("/generate-quiz")
async def generate_quiz(
    req: QuizGenerateRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not settings.GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="AI service not configured.")

    lesson = db.query(models.Lesson).filter(models.Lesson.id == req.lesson_id).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")

    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash")

    prompt = f"""Generate {req.count} quiz questions for this lesson. Return ONLY valid JSON, no markdown.

Lesson: {lesson.title}
Content: {lesson.content[:2000] if lesson.content else lesson.description}

Return this exact JSON format:
{{
  "questions": [
    {{
      "question": "question text",
      "type": "multiple_choice",
      "options": ["A) option1", "B) option2", "C) option3", "D) option4"],
      "correct_answer": "A",
      "explanation": "why this is correct"
    }}
  ]
}}

Mix question types: multiple_choice, true_false, fill_blank.
For true_false: options should be ["True", "False"], correct_answer is "True" or "False".
For fill_blank: options is [], correct_answer is the missing word(s).
"""

    try:
        response = model.generate_content(prompt)
        import json, re
        text = response.text
        # Strip markdown if present
        text = re.sub(r'```json\n?', '', text)
        text = re.sub(r'```\n?', '', text)
        data = json.loads(text.strip())
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Quiz generation failed: {str(e)}")

@router.get("/chat-history/{lesson_id}")
def get_chat_history(
    lesson_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    chats = db.query(models.AIChat).filter(
        models.AIChat.user_id == current_user.id,
        models.AIChat.lesson_id == lesson_id
    ).order_by(models.AIChat.created_at.desc()).limit(50).all()

    return [
        {
            "id": c.id,
            "message": c.message,
            "response": c.response,
            "learning_mode": c.learning_mode,
            "created_at": c.created_at.isoformat()
        }
        for c in reversed(chats)
    ]