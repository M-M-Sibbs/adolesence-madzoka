from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import Optional, List
from database import get_db, settings
from auth import get_current_user, require_admin
import models
import os
import uuid
import aiofiles

router = APIRouter(prefix="/lessons", tags=["lessons"])

CATEGORIES = [
    "Python Programming", "React Development", "JavaScript",
    "AI Development", "Data Science", "Cybersecurity", "Web Development", "Other"
]

def save_upload(file: UploadFile, subfolder: str) -> tuple[str, str]:
    """Save uploaded file and return (filename, url)"""
    ext = os.path.splitext(file.filename)[1]
    filename = f"{uuid.uuid4()}{ext}"
    path = os.path.join(settings.UPLOAD_DIR, subfolder, filename)
    return filename, path, f"/uploads/{subfolder}/{filename}"

@router.get("/categories")
def get_categories():
    return CATEGORIES

@router.get("")
def list_lessons(
    category: Optional[str] = None,
    published_only: bool = True,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    query = db.query(models.Lesson)
    if published_only and current_user.role == models.UserRole.student:
        query = query.filter(models.Lesson.is_published == True)
    if category:
        query = query.filter(models.Lesson.category == category)
    lessons = query.order_by(models.Lesson.created_at.desc()).all()
    return [lesson_to_dict(l, db, current_user.id) for l in lessons]

@router.get("/{lesson_id}")
def get_lesson(
    lesson_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    lesson = db.query(models.Lesson).filter(models.Lesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    if current_user.role == models.UserRole.student and not lesson.is_published:
        raise HTTPException(status_code=403, detail="Lesson not available")
    return lesson_to_dict(lesson, db, current_user.id)

@router.post("")
async def create_lesson(
    title: str = Form(...),
    description: str = Form(""),
    content: str = Form(""),
    category: str = Form("Other"),
    difficulty: str = Form("beginner"),
    estimated_duration: int = Form(30),
    is_published: bool = Form(False),
    video: Optional[UploadFile] = File(None),
    pdf: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin)
):
    lesson = models.Lesson(
        title=title,
        description=description,
        content=content,
        category=category,
        difficulty=models.DifficultyLevel(difficulty),
        estimated_duration=estimated_duration,
        is_published=is_published,
        created_by=admin.id
    )

    if video and video.filename:
        filename, path, url = save_upload(video, "videos")
        async with aiofiles.open(path, 'wb') as f:
            content_bytes = await video.read()
            await f.write(content_bytes)
        lesson.video_filename = filename
        lesson.video_url = url

    if pdf and pdf.filename:
        filename, path, url = save_upload(pdf, "pdfs")
        async with aiofiles.open(path, 'wb') as f:
            content_bytes = await pdf.read()
            await f.write(content_bytes)
        lesson.pdf_filename = filename
        lesson.pdf_url = url
        # Extract PDF text for AI context
        try:
            import PyPDF2
            import io
            pdf_bytes = open(path, 'rb').read()
            reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
            text = " ".join(page.extract_text() or "" for page in reader.pages)
            lesson.transcript = text[:10000]  # cap at 10k chars
        except:
            pass

    db.add(lesson)
    db.commit()
    db.refresh(lesson)
    return lesson_to_dict(lesson, db, admin.id)

@router.put("/{lesson_id}")
async def update_lesson(
    lesson_id: int,
    title: str = Form(...),
    description: str = Form(""),
    content: str = Form(""),
    category: str = Form("Other"),
    difficulty: str = Form("beginner"),
    estimated_duration: int = Form(30),
    is_published: bool = Form(False),
    video: Optional[UploadFile] = File(None),
    pdf: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin)
):
    lesson = db.query(models.Lesson).filter(models.Lesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")

    lesson.title = title
    lesson.description = description
    lesson.content = content
    lesson.category = category
    lesson.difficulty = models.DifficultyLevel(difficulty)
    lesson.estimated_duration = estimated_duration
    lesson.is_published = is_published

    if video and video.filename:
        filename, path, url = save_upload(video, "videos")
        async with aiofiles.open(path, 'wb') as f:
            await f.write(await video.read())
        lesson.video_filename = filename
        lesson.video_url = url

    if pdf and pdf.filename:
        filename, path, url = save_upload(pdf, "pdfs")
        async with aiofiles.open(path, 'wb') as f:
            await f.write(await pdf.read())
        lesson.pdf_filename = filename
        lesson.pdf_url = url

    db.commit()
    db.refresh(lesson)
    return lesson_to_dict(lesson, db, admin.id)

@router.delete("/{lesson_id}")
def delete_lesson(
    lesson_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin)
):
    lesson = db.query(models.Lesson).filter(models.Lesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    db.delete(lesson)
    db.commit()
    return {"message": "Lesson deleted"}

@router.post("/{lesson_id}/publish")
def toggle_publish(
    lesson_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin)
):
    lesson = db.query(models.Lesson).filter(models.Lesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    lesson.is_published = not lesson.is_published
    db.commit()
    return {"is_published": lesson.is_published}

def lesson_to_dict(lesson: models.Lesson, db: Session, user_id: int) -> dict:
    progress = db.query(models.Progress).filter(
        models.Progress.user_id == user_id,
        models.Progress.lesson_id == lesson.id
    ).first()

    quiz_count = db.query(models.Quiz).filter(models.Quiz.lesson_id == lesson.id).count()

    return {
        "id": lesson.id,
        "title": lesson.title,
        "description": lesson.description,
        "content": lesson.content,
        "category": lesson.category,
        "difficulty": lesson.difficulty.value if lesson.difficulty else "beginner",
        "estimated_duration": lesson.estimated_duration,
        "video_url": lesson.video_url,
        "pdf_url": lesson.pdf_url,
        "is_published": lesson.is_published,
        "created_at": lesson.created_at.isoformat() if lesson.created_at else None,
        "quiz_count": quiz_count,
        "progress": {
            "completed": progress.completed if progress else False,
            "score": progress.score if progress else 0,
            "last_position": progress.last_position if progress else 0,
        } if progress else None
    }