"""Self-service password reset with an emailed 6-digit code or link.

* The code and the link token are random and stored only as hashes.
* A code works once, for ``CODE_TTL_MINUTES``; ``MAX_ATTEMPTS`` wrong codes
  cancel it.  Requesting a new code cancels older ones.
* At most one email per ``RESEND_SECONDS`` and ``MAX_PER_HOUR`` per hour.
* Callers always show the same message, so nobody can learn which emails
  have accounts.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import secrets
from typing import Optional, Tuple

from sqlalchemy.orm import Session

import models
from routers.auth import SECRET_KEY
from services import email_service


CODE_TTL_MINUTES = 10
MAX_ATTEMPTS = 5
RESEND_SECONDS = 60
MAX_PER_HOUR = 5


class ResetError(ValueError):
    """User-facing reason a code/link cannot be used."""


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _aware(value: datetime.datetime) -> datetime.datetime:
    return value if value.tzinfo else value.replace(tzinfo=datetime.timezone.utc)


def _digest(kind: str, value: str) -> str:
    # Keyed hash: a leaked table cannot be brute-forced without the app secret.
    return hmac.new(SECRET_KEY.encode(), f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()


def _active_codes(db: Session, user_id: int):
    return db.query(models.PasswordResetCode).filter(
        models.PasswordResetCode.user_id == user_id,
        models.PasswordResetCode.used_at.is_(None),
    )


def create_reset(db: Session, user: models.User) -> Optional[Tuple[str, str]]:
    """Return ``(code, token)`` for a new reset, or ``None`` when rate-limited."""

    now = _now()
    recent = db.query(models.PasswordResetCode).filter(
        models.PasswordResetCode.user_id == user.id,
        models.PasswordResetCode.created_at >= now - datetime.timedelta(hours=1),
    ).order_by(models.PasswordResetCode.created_at.desc()).all()
    if len(recent) >= MAX_PER_HOUR:
        return None
    if recent and (now - _aware(recent[0].created_at)).total_seconds() < RESEND_SECONDS:
        return None

    for old in _active_codes(db, user.id).all():
        old.used_at = now  # only the newest code works
    code = f"{secrets.randbelow(1_000_000):06d}"
    token = secrets.token_urlsafe(32)
    db.add(models.PasswordResetCode(
        user_id=user.id,
        code_hash=_digest("code", code),
        token_hash=_digest("token", token),
        expires_at=now + datetime.timedelta(minutes=CODE_TTL_MINUTES),
        created_at=now,
    ))
    db.commit()
    return code, token


def send_reset_email(name: str, email: str, code: str, token: str) -> bool:
    link = f"{email_service.frontend_url()}/reset-password?token={token}"
    text = (
        f"Hello {name},\n\n"
        f"Your VisionGuard password reset code is: {code}\n\n"
        f"Enter it on the reset page, or open this link to set a new password:\n{link}\n\n"
        f"The code and link expire in {CODE_TTL_MINUTES} minutes and work once.\n"
        "If you did not ask for this, ignore this email; your password stays the same.\n\n"
        "VisionGuard Safety"
    )
    html = f"""
<div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;color:#172033">
  <h2 style="color:#1d4ed8;margin-bottom:4px">VisionGuard</h2>
  <p>Hello {name},</p>
  <p>Your password reset code is:</p>
  <p style="font-size:32px;font-weight:700;letter-spacing:8px;background:#eff6ff;padding:12px 16px;border-radius:8px;text-align:center">{code}</p>
  <p>Enter it on the reset page, or click the button to set a new password:</p>
  <p style="text-align:center"><a href="{link}" style="display:inline-block;background:#2563eb;color:#fff;padding:12px 22px;border-radius:8px;text-decoration:none;font-weight:700">Reset password</a></p>
  <p style="color:#64748b;font-size:13px">The code and link expire in {CODE_TTL_MINUTES} minutes and work once.
  If you did not ask for this, ignore this email; your password stays the same.</p>
</div>"""
    return email_service.send_email(email, f"VisionGuard password reset code: {code}", text, html)


def send_changed_email(name: str, email: str) -> bool:
    return email_service.send_email(
        email,
        "Your VisionGuard password was changed",
        f"Hello {name},\n\nYour VisionGuard password was just changed. "
        "If this was not you, contact your administrator immediately.\n\nVisionGuard Safety",
    )


def find_reset(
    db: Session,
    *,
    email: Optional[str] = None,
    code: Optional[str] = None,
    token: Optional[str] = None,
) -> models.PasswordResetCode:
    """The usable reset for a token, or for an email + code (counts attempts)."""

    now = _now()
    if token:
        record = db.query(models.PasswordResetCode).filter(
            models.PasswordResetCode.token_hash == _digest("token", token.strip())
        ).first()
        if record is None or record.used_at is not None or _aware(record.expires_at) < now:
            raise ResetError("This reset link is invalid or has expired. Request a new code.")
        return record

    user = db.query(models.User).filter(models.User.email == (email or "").strip().lower()).first()
    record = None
    if user is not None:
        record = _active_codes(db, user.id).order_by(models.PasswordResetCode.created_at.desc()).first()
    if record is None or _aware(record.expires_at) < now:
        raise ResetError("The code is invalid or has expired. Request a new code.")
    if not hmac.compare_digest(record.code_hash, _digest("code", (code or "").strip())):
        record.attempts += 1
        if record.attempts >= MAX_ATTEMPTS:
            record.used_at = now
            db.commit()
            raise ResetError("Too many wrong codes. Request a new code.")
        db.commit()
        left = MAX_ATTEMPTS - record.attempts
        raise ResetError(f"Wrong code. {left} attempt{'s' if left != 1 else ''} left.")
    return record


def complete_reset(db: Session, record: models.PasswordResetCode, new_password: str) -> models.User:
    from routers.auth import hash_password

    user = record.user
    user.password = hash_password(new_password)
    now = _now()
    for item in _active_codes(db, user.id).all():
        item.used_at = now
    db.commit()
    return user
