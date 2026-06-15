from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.orm import Session
from database import get_db
import models, schemas
import hashlib
import jwt
import datetime

router = APIRouter(prefix="/auth", tags=["auth"])

SECRET_KEY = "visionguard_secret_key_2024"
ALGORITHM  = "HS256"


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


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

    hashed = hash_password(request.password)
    if user.password != hashed:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if user.status != "active":
        raise HTTPException(status_code=403, detail="Account is inactive. Contact admin.")

    token = create_token(user.id, user.role, user.name)
    return {"token": token, "role": user.role, "name": user.name}


@router.post("/reset-password", response_model=schemas.MessageResponse)
def reset_password(request: schemas.PasswordResetRequest, db: Session = Depends(get_db)):
    if request.new_password != request.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    if len(request.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    user = db.query(models.User).filter(models.User.email == request.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="No account found with this email")

    user.password = hash_password(request.new_password)
    db.commit()
    return {"message": "Password updated successfully"}


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

    if request.department is not None:
        department = request.department.strip()
        user.department = department or None

    wants_password_change = request.current_password or request.new_password or request.confirm_password
    if wants_password_change:
        if not request.current_password:
            raise HTTPException(status_code=400, detail="Current password is required")
        if user.password != hash_password(request.current_password):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        if request.new_password != request.confirm_password:
            raise HTTPException(status_code=400, detail="Passwords do not match")
        if not request.new_password or len(request.new_password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        user.password = hash_password(request.new_password)

    db.commit()
    db.refresh(user)
    return user
