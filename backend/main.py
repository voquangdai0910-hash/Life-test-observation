from fastapi import FastAPI, HTTPException, Depends, status, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta
import json
import os
import re
import logging

from config import APP_NAME, ALLOWED_ORIGINS, ALLOWED_ORIGINS_PATTERN, DEFAULT_UPLOAD_INTERVAL
from models import (
    UserRegister, UserLogin, TokenResponse, DataUpload, 
    UploadIntervalConfig, UploadIntervalResponse, DashboardStats,
    TestingTimeEntry, TestingTimeResponse, CyclePattern, TimeSeriesData,
    DataUploadWithOnHours, TestingSessionWithOnHours
)
from database import db
from auth import (
    get_current_user, get_current_operator, get_current_access_person,
    get_current_admin, TokenData, create_access_token
)

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(title=APP_NAME, version="1.0.0")

# Configure CORS with explicit settings for GitHub Codespaces
# Allow all origins but be explicit about it
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8000",
        "http://localhost:8001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8001",
    ],
    allow_origin_regex=r"https://[a-z0-9\-]+\.app\.github\.dev",  # GitHub Codespaces
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=7200,
)

# Add debug middleware to log incoming requests
@app.middleware("http")
async def debug_middleware(request: Request, call_next):
    logger.info(f"Incoming {request.method} {request.url.path}")
    logger.info(f"  Origin: {request.headers.get('origin', 'N/A')}")
    logger.info(f"  Host: {request.headers.get('host', 'N/A')}")
    response = await call_next(request)
    logger.info(f"  Response: {response.status_code}")
    return response

# ==================== Authentication Routes ====================

# Catch-all OPTIONS handler for preflight requests
@app.options("/{full_path:path}")
async def options_handler(full_path: str):
    """Handle OPTIONS preflight requests"""
    return {"status": "ok"}

@app.post("/api/auth/register", response_model=TokenResponse)
async def register(user: UserRegister):
    """Register a new user"""
    logger.info(f"Register attempt: {user.email}")
    # Check if user already exists
    existing_user = db.get_user_by_email(user.email)
    if existing_user:
        logger.warning(f"User already exists: {user.email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create user in Supabase Auth
    result = db.create_user(user.email, user.full_name, user.password, user.role.value)
    
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"]
        )
    
    auth_user = result["user"]
    
    # Create token
    token_data = {
        "email": user.email,
        "user_id": auth_user["id"],
        "role": user.role.value
    }
    access_token = create_access_token(token_data)
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user={
            "id": auth_user["id"],
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "created_at": auth_user["created_at"]
        }
    )

@app.post("/api/auth/login", response_model=TokenResponse)
async def login(credentials: UserLogin):
    """Login user with email and password"""
    try:
        import hashlib
        # Get user from database
        user_data = db.get_user_by_email(credentials.email)
        
        if not user_data:
            logger.warning(f"Login failed: user not found: {credentials.email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        # Verify password hash
        password_hash = hashlib.sha256(credentials.password.encode()).hexdigest()
        if user_data.get("password_hash") != password_hash:
            logger.warning(f"Login failed: invalid password for {credentials.email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        # Create token
        token_data = {
            "email": credentials.email,
            "user_id": user_data.get("id"),
            "role": user_data.get("role", "operator")
        }
        access_token = create_access_token(token_data)
        
        logger.info(f"Login successful: {credentials.email}")
        
        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            user={
                "id": user_data.get("id"),
                "email": credentials.email,
                "full_name": user_data.get("full_name", ""),
                "role": user_data.get("role", "operator"),
                "created_at": user_data.get("created_at")
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

@app.get("/api/auth/verify")
async def verify_token(current_user: TokenData = Depends(get_current_user)):
    """Verify current token and return user info"""
    user_data = db.get_user_by_id(current_user.user_id)
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return {
        "id": user_data.get("id"),
        "email": user_data.get("email"),
        "full_name": user_data.get("full_name"),
        "role": user_data.get("role"),
        "valid": True
    }

# ==================== Data Upload Routes ====================

@app.post("/api/uploads/data")
async def upload_data(
    upload: DataUpload,
    current_user: TokenData = Depends(get_current_operator)
):
    """Upload test data"""
    
    # Calculate ON hours if time series data is present
    on_hours_result = db.calculate_on_hours_from_data(upload.data)
    
    # Add calculated ON hours to the data
    upload_data = upload.data.copy() if isinstance(upload.data, dict) else {}
    upload_data['on_hours'] = on_hours_result.get('on_hours', 0)
    upload_data['cycle_count'] = on_hours_result.get('cycle_count', 0)
    upload_data['pattern_info'] = on_hours_result.get('pattern', {})
    
    result = db.upload_data(
        operator_id=current_user.user_id,
        test_name=upload.test_name,
        description=upload.description or "",
        data=upload_data
    )
    
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"]
        )
    
    return {
        "message": "Data uploaded successfully",
        "upload": result["upload"],
        "on_hours_calculated": on_hours_result
    }

@app.get("/api/uploads/on-hours/{operator_id}")
async def get_operator_on_hours(
    operator_id: str,
    current_user: TokenData = Depends(get_current_access_person)
):
    """Get accumulated ON hours for an operator"""
    progress = db.get_on_hours_progress(operator_id, target_on_hours=468)
    
    return {
        "operator_id": operator_id,
        "progress": progress
    }

@app.get("/api/uploads/on-hours")
async def get_my_on_hours(
    current_user: TokenData = Depends(get_current_operator)
):
    """Get current operator's accumulated ON hours"""
    progress = db.get_on_hours_progress(current_user.user_id, target_on_hours=468)
    
    return {
        "operator_id": current_user.user_id,
        "progress": progress
    }

@app.get("/api/uploads/my-uploads")
async def get_my_uploads(
    limit: int = 50,
    current_user: TokenData = Depends(get_current_operator)
):
    """Get current user's uploads"""
    uploads = db.get_uploads_by_operator(current_user.user_id, limit)
    
    return {
        "uploads": uploads,
        "total_count": len(uploads)
    }

@app.get("/api/uploads/all")
async def get_all_uploads(
    limit: int = 100,
    current_user: TokenData = Depends(get_current_access_person)
):
    """Get all uploads (access person only)"""
    uploads = db.get_all_uploads(limit)
    last_upload = db.get_last_upload_time()
    interval = db.get_upload_interval()
    next_upload = None
    
    if last_upload:
        next_upload = last_upload + timedelta(minutes=interval)
    
    return {
        "uploads": uploads,
        "total_count": len(uploads),
        "last_upload_time": last_upload,
        "next_scheduled_upload": next_upload,
        "current_interval_minutes": interval
    }

# ==================== Upload Interval Configuration ====================

@app.get("/api/config/upload-interval")
async def get_upload_interval(current_user: TokenData = Depends(get_current_user)):
    """Get current upload interval"""
    interval = db.get_upload_interval()
    return {
        "interval_minutes": interval,
        "interval_hours": interval / 60,
        "description": f"Data must be uploaded every {interval // 60} hours and {interval % 60} minutes"
    }

@app.post("/api/config/upload-interval")
async def set_upload_interval(
    config: UploadIntervalConfig,
    current_user: TokenData = Depends(get_current_admin)
):
    """Set upload interval (admin only)"""
    if config.interval_minutes < 1 or config.interval_minutes > 1440:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Interval must be between 1 and 1440 minutes"
        )
    
    result = db.set_upload_interval(config.interval_minutes, current_user.user_id)
    
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"]
        )
    
    return {
        "message": "Upload interval updated successfully",
        "config": result["config"]
    }

# ==================== Testing Time Routes ====================

@app.post("/api/testing/start")
async def start_testing(
    test: TestingTimeEntry,
    current_user: TokenData = Depends(get_current_operator)
):
    """Start a new testing session"""
    result = db.create_testing_session(
        operator_id=current_user.user_id,
        test_name=test.test_name,
        notes=test.notes
    )
    
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"]
        )
    
    return {
        "message": "Testing session started",
        "session": result["session"]
    }

@app.post("/api/testing/end/{session_id}")
async def end_testing(
    session_id: str,
    current_user: TokenData = Depends(get_current_operator)
):
    """End a testing session"""
    result = db.end_testing_session(session_id)
    
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"]
        )
    
    return {
        "message": "Testing session ended",
        "session": result["session"]
    }

@app.get("/api/testing/active")
async def get_active_tests(current_user: TokenData = Depends(get_current_access_person)):
    """Get all active testing sessions"""
    tests = db.get_active_tests()
    return {
        "active_tests": tests,
        "count": len(tests)
    }

@app.get("/api/testing/history")
async def get_testing_history(
    operator_id: str = None,
    limit: int = 50,
    current_user: TokenData = Depends(get_current_access_person)
):
    """Get testing session history"""
    history = db.get_testing_history(operator_id, limit)
    return {
        "history": history,
        "total_count": len(history)
    }

# ==================== Dashboard Routes ====================

@app.get("/api/dashboard/stats")
async def get_dashboard_stats(current_user: TokenData = Depends(get_current_access_person)):
    """Get dashboard statistics"""
    stats = db.get_dashboard_stats()
    return {
        "stats": stats,
        "timestamp": datetime.utcnow()
    }

@app.get("/api/dashboard/summary")
async def get_dashboard_summary(current_user: TokenData = Depends(get_current_user)):
    """Get dashboard summary for current user"""
    stats = db.get_dashboard_stats()
    
    # If operator, only return their own stats
    if current_user.role == "operator":
        my_uploads = db.get_uploads_by_operator(current_user.user_id, limit=50)
        return {
            "user_type": "operator",
            "my_uploads": len(my_uploads),
            "next_upload_deadline": None,
            "upload_interval_minutes": stats["current_interval_minutes"]
        }
    
    # If access_person or admin
    return {
        "user_type": current_user.role,
        "stats": stats,
        "timestamp": datetime.utcnow()
    }

# ==================== Health Check ====================

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": APP_NAME,
        "timestamp": datetime.utcnow()
    }

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": APP_NAME,
        "version": "1.0.0",
        "docs": "/docs"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
