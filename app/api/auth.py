from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import (
    ALLOWED_ROLES,
    authenticate_user,
    create_access_token,
    create_user,
    get_current_user,
)

router = APIRouter()


class SignupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=8, max_length=200)
    role: str


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=8, max_length=200)


@router.post("/signup")
async def signup(request: SignupRequest):
    role = (request.role or "").strip().lower()
    if role not in ALLOWED_ROLES:
        raise HTTPException(status_code=400, detail="Role must be agent, underwriter, or external")
    create_user(
        name=request.name,
        email=request.email,
        password=request.password,
        role=role,
    )
    return {"status": "created"}


@router.post("/login")
async def login(request: LoginRequest):
    user = authenticate_user(request.email, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return {
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "user": {
            "name": user.name,
            "email": user.email,
            "role": user.role,
        },
    }


@router.get("/me")
async def me(user=Depends(get_current_user)):
    return {"name": user.name, "email": user.email, "role": user.role}
