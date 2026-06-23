from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from config import SECRET_KEY
from typing import Optional

security = HTTPBearer()

# Token settings
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440

class TokenData:
    def __init__(self, email: str = None, user_id: str = None, role: str = None):
        self.email = email
        self.user_id = user_id
        self.role = role

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str) -> TokenData:
    """Verify JWT token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("email")
        user_id: str = payload.get("user_id")
        role: str = payload.get("role")
        
        if email is None or user_id is None:
            raise credentials_exception
        
        token_data = TokenData(email=email, user_id=user_id, role=role)
        return token_data
    except JWTError:
        raise credentials_exception

async def get_current_user(credentials = Depends(security)) -> TokenData:
    """Get current authenticated user from token"""
    token = credentials.credentials
    return verify_token(token)

async def get_current_operator(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    """Get current user and verify they are an operator"""
    if current_user.role not in ["operator", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to perform this action"
        )
    return current_user

async def get_current_access_person(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    """Get current user and verify they are an access person"""
    if current_user.role not in ["access_person", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this data"
        )
    return current_user

async def get_current_admin(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    """Get current user and verify they are an admin"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user
