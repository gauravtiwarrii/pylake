from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.db import get_db
from app.core.config import get_settings
from app.core.security import (
    create_csrf_token,
    create_session_token,
    hash_password,
    session_expiry,
    sha256,
    verify_password,
)
from app.models.entities import AuthSession, User
from app.schemas.auth import LoginRequest, RegisterRequest, UserResponse

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> User:
    email = payload.email.lower()
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")

    user = User(email=email, full_name=payload.full_name.strip(), hashed_password=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")
    return user


@router.post("/login", response_model=UserResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> User:
    settings = get_settings()
    email = payload.email.lower()
    user = db.query(User).filter(func.lower(User.email) == email, User.is_active.is_(True)).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    session_token = create_session_token()
    csrf_token = create_csrf_token()
    db.add(AuthSession(
        user_id=user.id,
        token_hash=sha256(session_token),
        csrf_token_hash=sha256(csrf_token),
        expires_at=session_expiry(),
    ))
    db.commit()

    response.set_cookie(
        "pylake_session",
        session_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=24 * 60 * 60,
        path="/",
    )
    response.set_cookie(
        "pylake_csrf",
        csrf_token,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=24 * 60 * 60,
        path="/",
    )
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    token = request.cookies.get("pylake_session")
    if token:
        session = db.query(AuthSession).filter(AuthSession.token_hash == sha256(token), AuthSession.user_id == user.id).first()
        if session:
            db.delete(session)
            db.commit()
    response.delete_cookie("pylake_session", path="/")
    response.delete_cookie("pylake_csrf", path="/")


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> User:
    return user
