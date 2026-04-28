import time
import os
from typing import Optional
from dataclasses import dataclass
import jwt
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.core.config import get_settings
from app.core.logger import get_logger
from app.db.database import SessionLocal
from app.db.models import DBUser

logger = get_logger(__name__)
settings = get_settings()

security = HTTPBearer(auto_error=False)
ALLOWED_ROLES = {"agent", "underwriter", "external"}

@dataclass
class AuthUser:
    user_id: int
    name: str
    email: str
    role: str

def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()

def hash_password(password: str) -> str:
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters long")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def verify_password(password: str, stored_hash: str) -> bool:
    try:
        # Fallback for old custom PBKDF2 hash
        if stored_hash.startswith("pbkdf2_sha256$"):
            import hashlib
            import hmac
            import base64
            def _b64url_decode(data: str) -> bytes:
                padding = "=" * (-len(data) % 4)
                return base64.urlsafe_b64decode(data + padding)
            algo, iters, salt_b64, digest_b64 = stored_hash.split("$", 3)
            iterations = int(iters)
            salt = _b64url_decode(salt_b64)
            expected = _b64url_decode(digest_b64)
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
            return hmac.compare_digest(actual, expected)

        return bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))
    except Exception as e:
        logger.error("pwd_verification_failed", error=str(e))
        return False

def _jwt_secret() -> str:
    secret = settings.jwt_secret_key
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY is required")
    return secret

def create_access_token(user: AuthUser) -> str:
    now = int(time.time())
    exp = now + (settings.jwt_access_token_exp_minutes * 60)
    payload = {
        "sub": str(user.user_id),
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "iat": now,
        "exp": exp,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")

def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

def create_user(name: str, email: str, password: str, role: str) -> None:
    clean_role = (role or "").strip().lower()
    if clean_role not in ALLOWED_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    clean_name = (name or "").strip()
    clean_email = _normalize_email(email)
    if not clean_name or not clean_email:
        raise HTTPException(status_code=400, detail="Name and email are required")
    if "@" not in clean_email:
        raise HTTPException(status_code=400, detail="Invalid email")
    pwd_hash = hash_password(password)
    
    with SessionLocal() as db:
        existing = db.query(DBUser).filter(DBUser.email == clean_email).first()
        if existing:
            raise HTTPException(status_code=409, detail="Email already exists")
        
        user = DBUser(
            name=clean_name,
            email=clean_email,
            role=clean_role,
            password_hash=pwd_hash
        )
        db.add(user)
        db.commit()

def get_user_by_email(email: str) -> Optional[AuthUser]:
    clean_email = _normalize_email(email)
    with SessionLocal() as db:
        db_user = db.query(DBUser).filter(DBUser.email == clean_email).first()
        if not db_user:
            return None
        return AuthUser(user_id=db_user.id, name=db_user.name, email=db_user.email, role=db_user.role)

def authenticate_user(email: str, password: str) -> Optional[AuthUser]:
    clean_email = _normalize_email(email)
    if "@" not in clean_email:
        return None
    with SessionLocal() as db:
        db_user = db.query(DBUser).filter(DBUser.email == clean_email).first()
        if not db_user:
            return None
        if not verify_password(password, db_user.password_hash):
            return None
        return AuthUser(user_id=db_user.id, name=db_user.name, email=db_user.email, role=db_user.role)

def get_current_user(creds: HTTPAuthorizationCredentials = Depends(security)) -> AuthUser:
    if not creds or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    payload = decode_access_token(creds.credentials)
    role = payload.get("role", "")
    if role not in ALLOWED_ROLES:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid role in token")
    return AuthUser(
        user_id=int(payload["sub"]),
        name=payload.get("name", ""),
        email=payload.get("email", ""),
        role=role,
    )
