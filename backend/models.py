from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime
from enum import Enum

class UserRole(str, Enum):
    """User roles in the system"""
    OPERATOR = "operator"
    ACCESS_PERSON = "access_person"
    ADMIN = "admin"

class UserRegister(BaseModel):
    """User registration model.

    Note: role is intentionally NOT a field here. Self-registration always
    creates an 'operator'; elevated roles are assigned by an administrator.
    """
    email: EmailStr
    password: str
    full_name: str

class UserLogin(BaseModel):
    """User login model"""
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    """User response model"""
    id: str
    email: str
    full_name: str
    role: UserRole
    created_at: datetime

class TokenResponse(BaseModel):
    """Token response model"""
    access_token: str
    token_type: str
    user: UserResponse

class DataUpload(BaseModel):
    """Data upload model"""
    test_name: str
    description: Optional[str] = None
    data: dict

class DataUploadResponse(BaseModel):
    """Data upload response model"""
    id: str
    operator_id: str
    test_name: str
    description: Optional[str]
    data: dict
    uploaded_at: datetime
    file_url: Optional[str] = None

class UploadHistory(BaseModel):
    """Upload history response"""
    uploads: List[DataUploadResponse]
    total_count: int
    last_upload_time: Optional[datetime]
    next_scheduled_upload: Optional[datetime]

class UploadIntervalConfig(BaseModel):
    """Upload interval configuration"""
    interval_minutes: int

class UploadIntervalResponse(BaseModel):
    """Upload interval response"""
    id: str
    interval_minutes: int
    updated_at: datetime
    updated_by: str

class TestingTimeEntry(BaseModel):
    """Testing time entry model"""
    test_name: str
    notes: Optional[str] = None

class TestingTimeResponse(BaseModel):
    """Testing time response"""
    id: str
    test_name: str
    start_time: datetime
    end_time: Optional[datetime]
    duration_minutes: Optional[int]
    status: str
    operator_id: str
    operator_name: str
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

class DashboardStats(BaseModel):
    """Dashboard statistics"""
    total_uploads: int
    total_testing_sessions: int
    active_tests: int
    completed_tests: int
    last_upload: Optional[datetime]
    next_scheduled_upload: Optional[datetime]
    current_interval_minutes: int
    operators_count: int

class CyclePattern(BaseModel):
    """Cycle pattern configuration"""
    name: str
    on_minutes: float  # ON duration in minutes
    off_seconds: float  # OFF duration in seconds
    version: str  # UL/IEC version
    description: Optional[str] = None

class TimeSeriesData(BaseModel):
    """Time series data point"""
    timestamp: datetime
    state: str  # 'ON' or 'OFF'
    value: Optional[float] = None  # Optional sensor value

class DataUploadWithOnHours(BaseModel):
    """Data upload with calculated ON hours"""
    id: str
    operator_id: str
    test_name: str
    description: Optional[str]
    data: dict
    cycle_pattern_id: Optional[str] = None
    total_on_hours: float = 0.0
    cumulative_on_hours: float = 0.0
    target_on_hours: int = 468  # 468 or 500 hours depending on model
    progress_percent: float = 0.0
    uploaded_at: datetime

class TestingSessionWithOnHours(BaseModel):
    """Testing session with ON hour tracking"""
    id: str
    test_name: str
    start_time: datetime
    end_time: Optional[datetime]
    status: str
    operator_id: str
    cumulative_on_hours: float = 0.0
    target_on_hours: int = 468
    progress_percent: float = 0.0
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ==================== Life Test Models ====================

class LifeTestCreate(BaseModel):
    """Create a new life test"""
    test_label: str                        # e.g. LT001
    product: str                           # product name / model
    on_minutes: float = 8.0               # ON duration per cycle
    off_minutes: float = 2.0              # OFF duration per cycle
    target_hours: int = 468               # target ON hours
    initial_machine_hours: float = 0.0   # current machine reading at test start
    notes: Optional[str] = None


class SyncInput(BaseModel):
    """Operator submits a sync reading from the machine display"""
    machine_hours: int    # hours shown on machine
    machine_minutes: int  # minutes shown on machine
    notes: Optional[str] = None


class ECDInput(BaseModel):
    """Set the Estimated Completion Date"""
    ecd_date: str  # YYYY-MM-DD  (empty string to clear)


# ==================== System Pause Models ====================

class SystemPauseRequest(BaseModel):
    """Request to pause or resume all system timers"""
    notes: Optional[str] = None


class SystemStateResponse(BaseModel):
    """Current system pause state"""
    is_paused: bool
    paused_at: Optional[datetime]
    paused_by: Optional[str]
    active_pause_id: Optional[str]
    total_paused_minutes_ever: float

