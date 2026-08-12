from fastapi import FastAPI, HTTPException, Depends, status, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta
import json
import math
import os
import re
import logging

from config import APP_NAME, ALLOWED_ORIGINS, ALLOWED_ORIGINS_PATTERN, DEFAULT_UPLOAD_INTERVAL, DEBUG
from models import (
    UserRegister, UserLogin, TokenResponse, DataUpload, 
    UploadIntervalConfig, UploadIntervalResponse, DashboardStats,
    TestingTimeEntry, TestingTimeResponse, CyclePattern, TimeSeriesData,
    DataUploadWithOnHours, TestingSessionWithOnHours,
    LifeTestCreate, SyncInput, ECDInput,
    SystemPauseRequest, SystemStateResponse,
    LifeTestPauseRequest, LifeTestResumeRequest,
    AdminUserCreate, RoleUpdate, ChangePassword
)

# Minimum length for a new password (applies to change-password and admin-created accounts)
MIN_PASSWORD_LEN = 8
from database import db
from auth import (
    get_current_user, get_current_operator, get_current_access_person,
    get_current_admin, TokenData, create_access_token
)
from security import verify_password, hash_password

# Setup logging — verbose only when DEBUG is explicitly enabled
logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO)
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
        "http://localhost:8081",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8001",
        "http://127.0.0.1:8081",
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
    logger.debug(f"Incoming {request.method} {request.url.path}")
    logger.debug(f"  Origin: {request.headers.get('origin', 'N/A')}")
    logger.debug(f"  Host: {request.headers.get('host', 'N/A')}")
    response = await call_next(request)
    logger.debug(f"  Response: {response.status_code}")
    return response

# ==================== Authentication Routes ====================

# Catch-all OPTIONS handler for preflight requests
@app.options("/{full_path:path}")
async def options_handler(full_path: str):
    """Handle OPTIONS preflight requests"""
    return {"status": "ok"}

@app.post("/api/auth/register")
async def register(user: UserRegister):
    """Self-registration is DISABLED. Accounts are created by an administrator
    (see the admin User Management panel). This endpoint is kept only to return
    a clear message to any client that still tries to self-register."""
    logger.warning(f"Blocked self-registration attempt: {user.email}")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Self-registration is disabled. Ask an administrator to create your account."
    )


@app.post("/api/auth/change-password")
async def change_password(
    payload: ChangePassword,
    current_user: TokenData = Depends(get_current_user)
):
    """Change your OWN password. Requires the current password."""
    user = db.get_user_by_id(current_user.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    is_valid, _ = verify_password(payload.current_password, user["password_hash"])
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    new_pw = payload.new_password or ""
    if len(new_pw) < MIN_PASSWORD_LEN:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"New password must be at least {MIN_PASSWORD_LEN} characters.")
    if new_pw == payload.current_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="New password must be different from the current one.")
    if not db.update_password_hash(current_user.user_id, hash_password(new_pw)):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not update password")
    return {"message": "Password changed"}


# ==================== Admin: User Management ====================

@app.get("/api/admin/users")
async def admin_list_users(current_user: TokenData = Depends(get_current_admin)):
    """List all accounts (admin only)."""
    return {"users": db.list_users()}


@app.post("/api/admin/users")
async def admin_create_user(
    payload: AdminUserCreate,
    current_user: TokenData = Depends(get_current_admin)
):
    """Create an account with an explicit role (admin only)."""
    if len(payload.password or "") < MIN_PASSWORD_LEN:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    if db.get_user_by_email(payload.email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
    result = db.create_user(payload.email, payload.full_name, payload.password, payload.role.value)
    if not result["success"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
    return {"message": "User created", "user": result["user"]}


@app.patch("/api/admin/users/{user_id}/role")
async def admin_set_user_role(
    user_id: str,
    payload: RoleUpdate,
    current_user: TokenData = Depends(get_current_admin)
):
    """Change an account's role (admin only). Cannot demote the last admin."""
    if user_id == current_user.user_id and payload.role.value != "admin":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="You cannot change your own admin role.")
    result = db.set_user_role(user_id, payload.role.value)
    if not result["success"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
    return {"message": "Role updated", **result}


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(
    user_id: str,
    current_user: TokenData = Depends(get_current_admin)
):
    """Delete an account (admin only). Cannot delete yourself, the last admin,
    or an account that still owns life tests / uploads."""
    if user_id == current_user.user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="You cannot delete your own account.")
    result = db.delete_user(user_id)
    if not result["success"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
    return {"message": "User deleted"}

@app.post("/api/auth/login", response_model=TokenResponse)
async def login(credentials: UserLogin):
    """Login user with email and password"""
    try:
        # Get user from database
        user_data = db.get_user_by_email(credentials.email)

        if not user_data:
            logger.warning("Login failed: invalid credentials")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )

        # Verify password (constant-time bcrypt; legacy SHA-256 accepted once)
        is_valid, needs_rehash = verify_password(
            credentials.password, user_data.get("password_hash") or ""
        )
        if not is_valid:
            logger.warning("Login failed: invalid credentials")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )

        # Transparently upgrade legacy unsalted SHA-256 hashes to bcrypt
        if needs_rehash:
            try:
                db.update_password_hash(user_data["id"], hash_password(credentials.password))
            except Exception as upgrade_err:
                logger.error(f"Password hash upgrade failed: {upgrade_err}")

        # Create token
        token_data = {
            "email": credentials.email,
            "user_id": user_data.get("id"),
            "role": user_data.get("role", "operator")
        }
        access_token = create_access_token(token_data)
        
        logger.info(f"Login successful for user {user_data.get('id')}")
        
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

# ==================== Life Test Routes ====================

def _estimate_hours(last_machine_hours: float, last_synced_at: str,
                    current_time: datetime, on_minutes: float, off_minutes: float,
                    paused_seconds: float = 0.0) -> float:
    """Estimate current machine hours given last sync data, cycle pattern, and paused duration."""
    try:
        sync_time = datetime.fromisoformat(last_synced_at.rstrip('Z'))
        raw_elapsed_sec = max(0.0, (current_time - sync_time).total_seconds())
        elapsed_sec = max(0.0, raw_elapsed_sec - paused_seconds)
        on_sec = on_minutes * 60.0
        cycle_sec = (on_minutes + off_minutes) * 60.0
        if cycle_sec == 0:
            return last_machine_hours
        full_cycles = int(elapsed_sec // cycle_sec)
        remainder = elapsed_sec % cycle_sec
        on_in_remainder = min(remainder, on_sec)
        on_since_sync = full_cycles * on_sec + on_in_remainder
        return last_machine_hours + on_since_sync / 3600.0
    except Exception:
        return last_machine_hours


def _get_effective_now(system_state: dict) -> datetime:
    """Return the effective 'now' — frozen at paused_at if system is paused."""
    if system_state.get("is_paused") and system_state.get("paused_at"):
        return datetime.fromisoformat(system_state["paused_at"].rstrip('Z'))
    return datetime.utcnow()


def _test_effective_now(test: dict, system_state: dict) -> datetime:
    """Effective 'now' for a single life test — frozen at the EARLIEST active
    pause that affects it: its own per-slot pause and/or a system-wide pause.
    Freezing at the earliest keeps the counter and the excluded paused time
    consistent when both apply."""
    candidates = [datetime.utcnow()]
    if test.get("status") == "paused" and test.get("paused_at"):
        try:
            candidates.append(datetime.fromisoformat(test["paused_at"].rstrip('Z')))
        except Exception:
            pass
    if system_state.get("is_paused") and system_state.get("paused_at"):
        try:
            candidates.append(datetime.fromisoformat(system_state["paused_at"].rstrip('Z')))
        except Exception:
            pass
    return min(candidates)


ECD_EDIT_WINDOW_DAYS = 7
ECD_LOCK_MESSAGE = ("The ECD can only be modified once within 7 days "
                    "of its initial creation.")


def _compute_ecd_status(test: dict) -> dict:
    """Derive the ECD edit state for the UI (and as an authoritative hint).

    States:
      * uncreated     — no ECD yet; the initial creation is allowed.
      * editable      — ECD set, not yet edited, still within the 7-day window;
                        one correction remains. `days_remaining` is populated.
      * locked_edited — the one-time edit has already been used.
      * locked_expired— 7 days elapsed with no edit.
    """
    created_at = test.get("ecd_created_at")
    edited = bool(test.get("ecd_edited"))

    if not created_at:
        return {"state": "uncreated", "editable": True,
                "days_remaining": None, "message": None}

    try:
        created_dt = datetime.fromisoformat(created_at.rstrip('Z'))
    except Exception:
        return {"state": "uncreated", "editable": True,
                "days_remaining": None, "message": None}

    window_end = created_dt + timedelta(days=ECD_EDIT_WINDOW_DAYS)
    now = datetime.utcnow()

    if edited:
        return {"state": "locked_edited", "editable": False,
                "days_remaining": 0, "message": ECD_LOCK_MESSAGE}
    if now > window_end:
        return {"state": "locked_expired", "editable": False,
                "days_remaining": 0, "message": ECD_LOCK_MESSAGE}

    days_remaining = max(1, int(math.ceil((window_end - now).total_seconds() / 86400.0)))
    return {"state": "editable", "editable": True,
            "days_remaining": days_remaining, "message": None}


@app.post("/api/life-tests")
async def create_life_test(
    payload: LifeTestCreate,
    current_user: TokenData = Depends(get_current_operator)
):
    """Create a new life test (operator)"""
    result = db.create_life_test(
        test_label=payload.test_label,
        product=payload.product,
        datecode=payload.datecode,
        operator_id=current_user.user_id,
        on_minutes=payload.on_minutes,
        off_minutes=payload.off_minutes,
        target_hours=payload.target_hours,
        initial_machine_hours=payload.initial_machine_hours,
        notes=payload.notes
    )
    if not result["success"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
    return {"message": "Life test created", "id": result["id"], "test_label": result["test_label"]}


@app.get("/api/life-tests")
async def list_life_tests(
    test_status: str = None,
    current_user: TokenData = Depends(get_current_user)
):
    """List all life tests with pause-aware estimated hours (system + per-slot)"""
    tests = db.get_life_tests(status=test_status)
    system_state = db.get_system_state()

    for test in tests:
        # Each test freezes at its own effective 'now' (its own pause or a
        # system pause, whichever started first).
        effective_now = _test_effective_now(test, system_state)
        effective_now_iso = effective_now.isoformat() + 'Z'

        paused_sec = 0.0
        if test.get("last_sync") and test["status"] in ("running", "paused"):
            paused_sec = db.get_effective_paused_seconds(
                test["id"], test["last_sync"]["synced_at"], effective_now_iso
            )
        test["paused_seconds_since_sync"] = paused_sec
        test["is_paused"] = test["status"] == "paused"
        test["slot_total_paused_seconds"] = db.get_test_own_paused_seconds(test["id"])
        test["system_is_paused"] = system_state["is_paused"]
        test["system_paused_at"] = system_state["paused_at"]

    return {"life_tests": tests, "count": len(tests)}


@app.get("/api/life-tests/{lt_id}")
async def get_life_test(
    lt_id: str,
    current_user: TokenData = Depends(get_current_user)
):
    """Get a single life test with pause-aware current estimate"""
    test = db.get_life_test(lt_id)
    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Life test not found")

    system_state = db.get_system_state()
    effective_now = _test_effective_now(test, system_state)
    effective_now_iso = effective_now.isoformat() + 'Z'

    estimated_hours = None
    paused_sec = 0.0
    if test.get("last_sync") and test["status"] in ("running", "paused"):
        paused_sec = db.get_effective_paused_seconds(
            test["id"], test["last_sync"]["synced_at"], effective_now_iso
        )
        estimated_hours = _estimate_hours(
            test["last_sync"]["machine_hours"],
            test["last_sync"]["synced_at"],
            effective_now,
            test["on_minutes"],
            test["off_minutes"],
            paused_sec
        )

    # Total time this test's timeline has been frozen by system pauses,
    # measured from test creation until now (or until completion).
    pause_window_end = effective_now_iso
    if test["status"] == "completed" and test.get("completed_at"):
        pause_window_end = test["completed_at"]
    total_paused_seconds = 0.0
    if test.get("created_at"):
        total_paused_seconds = db.get_paused_seconds_between(test["created_at"], pause_window_end)

    test["estimated_hours"] = estimated_hours
    test["paused_seconds_since_sync"] = paused_sec
    test["total_paused_seconds"] = total_paused_seconds           # system-pause time in window
    test["slot_total_paused_seconds"] = db.get_test_own_paused_seconds(lt_id)  # this slot's own pauses
    test["is_paused"] = test["status"] == "paused"
    test["system_is_paused"] = system_state["is_paused"]
    test["system_paused_at"] = system_state["paused_at"]
    test["ecd_status"] = _compute_ecd_status(test)
    return test


@app.post("/api/life-tests/{lt_id}/sync")
async def submit_sync(
    lt_id: str,
    payload: SyncInput,
    current_user: TokenData = Depends(get_current_operator)
):
    """Operator submits a sync reading from the machine display"""
    test = db.get_life_test(lt_id)
    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Life test not found")
    if test["status"] != "running":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Life test is not running")

    machine_hours_total = payload.machine_hours + payload.machine_minutes / 60.0
    now = datetime.utcnow()

    # Compute what the system was estimating right now (pause-aware)
    system_state = db.get_system_state()
    effective_now = _get_effective_now(system_state)
    effective_now_iso = effective_now.isoformat() + 'Z'

    estimated_hours = machine_hours_total  # default if no prior sync
    if test.get("last_sync"):
        paused_sec = db.get_paused_seconds_between(
            test["last_sync"]["synced_at"], effective_now_iso
        )
        estimated_hours = _estimate_hours(
            test["last_sync"]["machine_hours"],
            test["last_sync"]["synced_at"],
            effective_now,
            test["on_minutes"],
            test["off_minutes"],
            paused_sec
        )

    difference_minutes = (machine_hours_total - estimated_hours) * 60.0

    result = db.add_sync_record(
        life_test_id=lt_id,
        machine_hours=machine_hours_total,
        estimated_hours=round(estimated_hours, 4),
        difference_minutes=round(difference_minutes, 2),
        operator_id=current_user.user_id,
        notes=payload.notes
    )
    if not result["success"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])

    return {
        "message": "Sync recorded",
        "machine_hours": machine_hours_total,
        "system_estimated_hours": round(estimated_hours, 4),
        "difference_minutes": round(difference_minutes, 2),
        "synced_at": result["synced_at"]
    }


@app.get("/api/life-tests/{lt_id}/syncs")
async def get_syncs(
    lt_id: str,
    current_user: TokenData = Depends(get_current_user)
):
    """Get sync history for a life test"""
    test = db.get_life_test(lt_id)
    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Life test not found")
    syncs = db.get_sync_records(lt_id)
    return {"syncs": syncs, "count": len(syncs)}


@app.patch("/api/life-tests/{lt_id}/complete")
async def complete_life_test(
    lt_id: str,
    current_user: TokenData = Depends(get_current_operator)
):
    """Mark a life test as completed, snapshotting the final estimated hours"""
    test = db.get_life_test(lt_id)
    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Life test not found")
    if test["status"] != "running":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only running tests can be completed")

    # Calculate the accumulated ON-hours at this exact moment (pause-aware)
    now = datetime.utcnow()
    final_hours = 0.0
    if test.get("last_sync"):
        system_state = db.get_system_state()
        effective_now = _get_effective_now(system_state)
        effective_now_iso = effective_now.isoformat() + 'Z'
        paused_sec = db.get_paused_seconds_between(
            test["last_sync"]["synced_at"], effective_now_iso
        )
        final_hours = _estimate_hours(
            test["last_sync"]["machine_hours"],
            test["last_sync"]["synced_at"],
            effective_now,
            test["on_minutes"],
            test["off_minutes"],
            paused_sec
        )

    # Store the final value as a completion sync so the frozen counter is accurate
    db.add_sync_record(
        life_test_id=lt_id,
        machine_hours=round(final_hours, 4),
        estimated_hours=round(final_hours, 4),
        difference_minutes=0.0,
        operator_id=current_user.user_id,
        notes="Test completed"
    )

    result = db.complete_life_test(lt_id)
    if not result["success"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
    return {"message": "Life test marked as completed", "final_hours": round(final_hours, 4)}


@app.patch("/api/life-tests/{lt_id}/ecd")
async def set_ecd(
    lt_id: str,
    payload: ECDInput,
    current_user: TokenData = Depends(get_current_operator)
):
    """Set or update the Estimated Completion Date (operator only).

    The one-time / 7-day edit restriction is enforced here in the database
    layer, so it cannot be bypassed via direct API calls.
    """
    test = db.get_life_test(lt_id)
    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Life test not found")
    user = db.get_user_by_id(current_user.user_id)
    operator_name = user["full_name"] if user else current_user.user_id
    result = db.set_ecd(lt_id, payload.ecd_date, current_user.user_id, operator_name)
    if not result["success"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
    # Recompute the fresh lock state so the client can update its UI immediately
    ecd_status = _compute_ecd_status(db.get_life_test(lt_id))
    return {
        "message": "ECD updated",
        "ecd": result["ecd"],
        "action": result.get("action"),
        "ecd_status": ecd_status
    }


@app.get("/api/life-tests/{lt_id}/ecd-logs")
async def get_ecd_logs(
    lt_id: str,
    current_user: TokenData = Depends(get_current_user)
):
    """Get the ECD change audit trail for a life test (any authenticated user)."""
    test = db.get_life_test(lt_id)
    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Life test not found")
    return {"logs": db.get_ecd_audit_logs(lt_id), "ecd_status": _compute_ecd_status(test)}


@app.delete("/api/life-tests/{lt_id}")
async def delete_life_test(
    lt_id: str,
    current_user: TokenData = Depends(get_current_operator)
):
    """Delete a completed life test and all its data (operator only)"""
    test = db.get_life_test(lt_id)
    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Life test not found")
    if test["status"] != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only completed tests can be deleted"
        )
    result = db.delete_life_test(lt_id)
    if not result["success"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
    return {"message": "Life test deleted successfully"}


# ==================== Per-Slot (Life Test) Pause Routes ====================

@app.post("/api/life-tests/{lt_id}/pause")
async def pause_life_test(
    lt_id: str,
    req: LifeTestPauseRequest,
    current_user: TokenData = Depends(get_current_operator)
):
    """Pause a single life test / slot (operator or admin).

    A non-empty reason is mandatory — it is recorded in the slot's pause history.
    Pausing one slot does not affect any other slot.
    """
    if not (req.reason or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A pause reason is required"
        )
    user = db.get_user_by_id(current_user.user_id)
    operator_name = user["full_name"] if user else current_user.user_id
    result = db.pause_life_test(lt_id, current_user.user_id, operator_name, req.reason)
    if not result["success"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
    logger.info(f"Slot {lt_id} PAUSED by {operator_name}: {result['reason']}")
    return {
        "message": "Slot paused — timer frozen",
        "paused_at": result["paused_at"],
        "paused_by": operator_name,
        "reason": result["reason"],
        "pause_id": result["pause_id"]
    }


@app.post("/api/life-tests/{lt_id}/resume")
async def resume_life_test(
    lt_id: str,
    req: LifeTestResumeRequest,
    current_user: TokenData = Depends(get_current_operator)
):
    """Resume a paused life test / slot (operator or admin).

    Ends the pause period, accumulates the paused duration (excluded from
    effective testing time), and continues the timer from where it stopped.
    """
    user = db.get_user_by_id(current_user.user_id)
    operator_name = user["full_name"] if user else current_user.user_id
    result = db.resume_life_test(lt_id, current_user.user_id, operator_name)
    if not result["success"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
    logger.info(f"Slot {lt_id} RESUMED by {operator_name} "
                f"(paused {result['total_paused_minutes']} min)")
    return {
        "message": "Slot resumed — timer continues",
        "resumed_at": result["resumed_at"],
        "resumed_by": operator_name,
        "total_paused_minutes": result["total_paused_minutes"]
    }


@app.get("/api/life-tests/{lt_id}/pause-logs")
async def get_life_test_pause_logs(
    lt_id: str,
    limit: int = 100,
    current_user: TokenData = Depends(get_current_user)
):
    """Get the pause history for a single slot (any authenticated user)."""
    test = db.get_life_test(lt_id)
    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Life test not found")
    logs = db.get_test_pause_logs(lt_id, limit)
    return {"logs": logs, "count": len(logs)}


@app.get("/api/reports/sync-quality")
async def sync_quality_report(
    current_user: TokenData = Depends(get_current_access_person)
):
    """Sync quality report"""
    report = db.get_sync_quality_report()
    return {"report": report}


# ==================== System Pause / Resume Routes ====================

@app.get("/api/system/state")
async def get_system_state(current_user: TokenData = Depends(get_current_user)):
    """Get current system pause state (any authenticated user)"""
    state = db.get_system_state()
    paused_by_name = None
    if state["paused_by"]:
        user = db.get_user_by_id(state["paused_by"])
        paused_by_name = user["full_name"] if user else state["paused_by"]
    return {
        "is_paused": state["is_paused"],
        "paused_at": state["paused_at"],
        "paused_by": state["paused_by"],
        "paused_by_name": paused_by_name,
        "active_pause_id": state["active_pause_id"],
        "total_paused_minutes_ever": state["total_paused_minutes_ever"]
    }


@app.post("/api/system/pause")
async def pause_system(
    req: SystemPauseRequest,
    current_user: TokenData = Depends(get_current_operator)
):
    """Pause all life-test timers (operator and above)"""
    user = db.get_user_by_id(current_user.user_id)
    operator_name = user["full_name"] if user else current_user.user_id
    result = db.pause_system(current_user.user_id, operator_name, req.notes)
    if not result["success"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
    logger.info(f"System PAUSED by {operator_name} at {result['paused_at']}")
    return {
        "message": "System paused — all timers frozen",
        "paused_at": result["paused_at"],
        "paused_by": operator_name,
        "pause_id": result["pause_id"]
    }


@app.post("/api/system/resume")
async def resume_system(
    req: SystemPauseRequest,
    current_user: TokenData = Depends(get_current_operator)
):
    """Resume all life-test timers (operator and above)"""
    user = db.get_user_by_id(current_user.user_id)
    operator_name = user["full_name"] if user else current_user.user_id
    result = db.resume_system(current_user.user_id, operator_name, req.notes)
    if not result["success"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])

    # Recalculate ECDs: push out the completion date of every running test by
    # the whole number of days lost to this pause, so the timeline reflects
    # actual factory operating days.
    paused_days = int(round(result["total_paused_minutes"] / 1440.0))
    ecd_updated_count = db.advance_running_ecds(paused_days)

    logger.info(f"System RESUMED by {operator_name} at {result['resumed_at']}")
    return {
        "message": "System resumed — timers restarted",
        "resumed_at": result["resumed_at"],
        "resumed_by": operator_name,
        "total_paused_minutes": result["total_paused_minutes"],
        "ecd_shifted_days": paused_days,
        "ecd_updated_count": ecd_updated_count
    }


@app.get("/api/system/pause-logs")
async def get_pause_logs(
    limit: int = 100,
    current_user: TokenData = Depends(get_current_access_person)
):
    """Get audit log of all pause/resume events (access person and above)"""
    logs = db.get_pause_logs(limit)
    return {"logs": logs, "count": len(logs)}


if __name__ == "__main__":
    import uvicorn
    # Auto-reload restarts the worker on every .py change. During that restart the
    # outgoing and incoming worker briefly share the same SQLite file, which can
    # surface a transient "database is locked" on an in-flight write. Keep reload
    # OFF by default so real lab usage is stable; a developer can opt back in by
    # setting API_RELOAD=true in the environment / backend/.env.
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    reload_enabled = os.getenv("API_RELOAD", "false").strip().lower() in ("1", "true", "yes", "on")
    uvicorn.run("main:app", host=host, port=port, reload=reload_enabled)

