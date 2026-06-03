from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from auth import require_admin, get_current_user
import models

analytics_router = APIRouter(prefix="/analytics", tags=["analytics"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])

@analytics_router.get("/overview")
def get_overview(
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin)
):
    total_students = db.query(models.User).filter(models.User.role == models.UserRole.student).count()
    total_lessons = db.query(models.Lesson).count()
    total_completions = db.query(models.Progress).filter(models.Progress.completed == True).count()
    total_ai_chats = db.query(models.AIChat).count()
    avg_quiz_score = db.query(func.avg(models.Progress.score)).scalar() or 0

    # Recent activity
    recent_chats = db.query(models.AIChat).order_by(
        models.AIChat.created_at.desc()
    ).limit(5).all()

    # Top lessons by chat activity
    top_lessons_raw = db.query(
        models.AIChat.lesson_id,
        func.count(models.AIChat.id).label("chat_count")
    ).filter(models.AIChat.lesson_id != None).group_by(
        models.AIChat.lesson_id
    ).order_by(func.count(models.AIChat.id).desc()).limit(5).all()

    top_lessons = []
    for row in top_lessons_raw:
        lesson = db.query(models.Lesson).filter(models.Lesson.id == row.lesson_id).first()
        if lesson:
            top_lessons.append({"title": lesson.title, "chats": row.chat_count})

    return {
        "total_students": total_students,
        "total_lessons": total_lessons,
        "total_completions": total_completions,
        "total_ai_chats": total_ai_chats,
        "avg_quiz_score": round(float(avg_quiz_score), 1),
        "top_lessons": top_lessons,
        "recent_activity": [
            {
                "user_id": c.user_id,
                "lesson_id": c.lesson_id,
                "created_at": c.created_at.isoformat()
            }
            for c in recent_chats
        ]
    }

@admin_router.get("/users")
def list_users(
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin)
):
    users = db.query(models.User).order_by(models.User.created_at.desc()).all()
    return [
        {
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "role": u.role.value,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None
        }
        for u in users
    ]

@admin_router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin)
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    db.delete(user)
    db.commit()
    return {"message": "User deleted"}