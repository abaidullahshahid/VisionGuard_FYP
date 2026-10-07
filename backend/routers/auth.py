import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Header, status
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from database import get_db
import models, schemas
import jwt
import datetime

router = APIRouter(prefix="/auth", tags=["auth"])

SECRET_KEY = os.getenv(
    "VISIONGUARD_SECRET_KEY",
    "visionguard_local_demo_secret_key_2024_change_before_deployment",
)
ALGORITHM  = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except ValueError:
        return False


def create_token(user_id: int, role: str, name: str) -> str:
    payload = {
        "sub": str(user_id),
        "role": role,
        "name": name,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def require_auth(authorization: str = Header(...)) -> dict:
    token = authorization.replace("Bearer ", "")
    return decode_token(token)


@router.post("/login", response_model=schemas.LoginResponse)
def login(request: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == request.email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not verify_password(request.password, user.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if user.status != "active":
        raise HTTPException(status_code=403, detail="Account is inactive. Contact admin.")

    token = create_token(user.id, user.role, user.name)
    return {"token": token, "role": user.role, "name": user.name}


FORGOT_PASSWORD_MESSAGE = (
    "If this email belongs to an active account, an administrator has been asked to reset it. "
    "They will give you a temporary password; change it in your profile after signing in."
)
EMAIL_CODE_MESSAGE = (
    "If this email is registered, we have sent a 6-digit code to it. "
    "It expires in 10 minutes. Check your Spam folder if you do not see it."
)


@router.post("/forgot-password")
def forgot_password(
    request: schemas.ForgotPasswordRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Start a reset without revealing whether the email has an account.

    With Gmail configured (backend/.env) the user receives a code and link by
    email.  Otherwise an administrator is asked to set a temporary password.
    Never changes a password by itself.
    """
    from services import email_service
    from services.notification_service import notify_password_reset_request
    from services.password_reset_service import create_reset, send_reset_email

    email = request.email.strip().lower()
    user = db.query(models.User).filter(models.User.email == email).first()
    if not email_service.is_configured():
        if user is not None and user.status == "active":
            if notify_password_reset_request(db, user):
                db.commit()
        return {"message": FORGOT_PASSWORD_MESSAGE, "email_enabled": False}

    if user is not None and user.status == "active":
        created = create_reset(db, user)
        if created is not None:
            # Sent after the response so timing does not reveal the account.
            background.add_task(send_reset_email, user.name, user.email, *created)
    return {"message": EMAIL_CODE_MESSAGE, "email_enabled": True}


@router.post("/reset-password/check")
def check_reset(request: schemas.ResetCheckRequest, db: Session = Depends(get_db)):
    """Confirm a code or link before asking for the new password."""
    from services.password_reset_service import ResetError, find_reset

    try:
        find_reset(db, email=request.email, code=request.code, token=request.token)
    except ResetError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"valid": True}


@router.post("/reset-password", response_model=schemas.MessageResponse)
def reset_password(
    request: schemas.ResetPasswordRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    from services.password_reset_service import ResetError, complete_reset, find_reset, send_changed_email

    if request.new_password != request.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    if len(request.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    try:
        record = find_reset(db, email=request.email, code=request.code, token=request.token)
    except ResetError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if record.user.status != "active":
        raise HTTPException(status_code=403, detail="Account is inactive. Contact admin.")
    user = complete_reset(db, record, request.new_password)
    background.add_task(send_changed_email, user.name, user.email)
    return {"message": "Password changed. You can now sign in with your new password."}


@router.get("/me", response_model=schemas.UserOut)
def get_profile(db: Session = Depends(get_db), payload=Depends(require_auth)):
    user = db.query(models.User).filter(models.User.id == int(payload.get("sub"))).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/me", response_model=schemas.UserOut)
def update_profile(request: schemas.ProfileUpdate, db: Session = Depends(get_db), payload=Depends(require_auth)):
    user = db.query(models.User).filter(models.User.id == int(payload.get("sub"))).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if request.name is not None:
        name = request.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        user.name = name

    if request.email is not None:
        email = request.email.strip().lower()
        if not email:
            raise HTTPException(status_code=400, detail="Email cannot be empty")
        existing = db.query(models.User).filter(models.User.email == email, models.User.id != user.id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")
        user.email = email

    if request.department is not None and user.role != "admin":
        department = request.department.strip()
        user.department = department or None

    wants_password_change = request.current_password or request.new_password or request.confirm_password
    if wants_password_change:
        if not request.current_password:
            raise HTTPException(status_code=400, detail="Current password is required")
        if not verify_password(request.current_password, user.password):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        if request.new_password != request.confirm_password:
            raise HTTPException(status_code=400, detail="Passwords do not match")
        if not request.new_password or len(request.new_password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        user.password = hash_password(request.new_password)

    db.commit()
    db.refresh(user)
    return user
