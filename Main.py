from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from database import init_db, settings
from routers.auth import router as auth_router
from routers.lessons import router as lessons_router
from routers.ai import router as ai_router
from routers.quiz_progress import quiz_router, progress_router
from routers.analytics import analytics_router, admin_router
import os

app = FastAPI(
    title="Adolescence AI Learning Platform",
    description="AI-powered educational platform with Gemini 2.5 Flash",
    version="1.0.0"
)

# CORS
origins = settings.CORS_ORIGINS.split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Init DB on startup
@app.on_event("startup")
def startup():
    init_db()
    # Create default admin if none exists
    from database import SessionLocal
    from models import User, UserRole
    from auth import hash_password
    db = SessionLocal()
    try:
        admin_count = db.query(User).filter(User.role == UserRole.admin).count()
        if admin_count == 0:
            default_admin = User(
                name="Admin",
                email="admin@adolescence.app",
                password=hash_password("admin123"),
                role=UserRole.admin
            )
            db.add(default_admin)
            db.commit()
            print("✅ Default admin created: admin@adolescence.app / admin123")
    except Exception as e:
        print(f"Startup error: {e}")
    finally:
        db.close()

# Static files for uploads
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

# Routers
app.include_router(auth_router, prefix="/api")
app.include_router(lessons_router, prefix="/api")
app.include_router(ai_router, prefix="/api")
app.include_router(quiz_router, prefix="/api")
app.include_router(progress_router, prefix="/api")
app.include_router(analytics_router, prefix="/api")
app.include_router(admin_router, prefix="/api")

@app.get("/")
def root():
    return {
        "name": "Adolescence AI Learning Platform",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs"
    }

@app.get("/api/health")
def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)