"""Email code / link password reset (no real email is sent).

Run:
    python test_password_reset.py
"""

from __future__ import annotations

import datetime
import os
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import get_db
import models
from routers import auth
from routers.auth import hash_password
from services import email_service, password_reset_service


def run_tests() -> None:
    saved_env = {key: os.environ.get(key) for key in ("SMTP_USERNAME", "SMTP_PASSWORD")}
    os.environ["SMTP_USERNAME"] = "visionguard.test@gmail.com"
    os.environ["SMTP_PASSWORD"] = "abcdabcdabcdabcd"
    sent = []
    original_transport = email_service.transport
    email_service.transport = sent.append

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    try:
        with Session() as db:
            db.add(models.User(name="Abaid", email="abaid@example.com", password=hash_password("oldpass1"), role="worker", status="active"))
            db.add(models.User(name="Gone", email="gone@example.com", password=hash_password("oldpass1"), role="worker", status="inactive"))
            db.commit()

        app = FastAPI()
        app.include_router(auth.router)

        def override_db():
            db = Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        client = TestClient(app)

        def body(message):
            return message.get_body(("plain",)).get_content()

        # Same answer for real, unknown and inactive accounts; only the real one gets mail.
        replies = [client.post("/auth/forgot-password", json={"email": email}).json() for email in ("Abaid@example.com", "nobody@example.com", "gone@example.com")]
        assert replies[0] == replies[1] == replies[2] and replies[0]["email_enabled"] is True
        assert len(sent) == 1 and sent[0]["To"] == "abaid@example.com"
        assert sent[0]["From"] == "VisionGuard Safety <visionguard.test@gmail.com>"
        code = re.search(r"reset code is: (\d{6})", body(sent[0])).group(1)
        token = re.search(r"reset-password\?token=([\w-]+)", body(sent[0])).group(1)
        with Session() as db:
            stored = db.query(models.PasswordResetCode).one()
            assert code not in stored.code_hash and token not in stored.token_hash  # hashes only

        # Asking again within a minute sends nothing new.
        client.post("/auth/forgot-password", json={"email": "abaid@example.com"})
        assert len(sent) == 1

        # Wrong codes count down, then the right code works once.
        wrong = "000000" if code != "000000" else "111111"
        bad = client.post("/auth/reset-password/check", json={"email": "abaid@example.com", "code": wrong})
        assert bad.status_code == 400 and "4 attempts left" in bad.json()["detail"]
        assert client.post("/auth/reset-password/check", json={"email": "abaid@example.com", "code": code}).json() == {"valid": True}
        mismatch = client.post("/auth/reset-password", json={"email": "abaid@example.com", "code": code, "new_password": "newpass1", "confirm_password": "other"})
        assert mismatch.status_code == 400
        done = client.post("/auth/reset-password", json={"email": "abaid@example.com", "code": code, "new_password": "newpass1", "confirm_password": "newpass1"})
        assert done.status_code == 200, done.text
        assert client.post("/auth/login", json={"email": "abaid@example.com", "password": "newpass1"}).status_code == 200
        assert client.post("/auth/login", json={"email": "abaid@example.com", "password": "oldpass1"}).status_code == 401
        assert sent[-1]["Subject"] == "Your VisionGuard password was changed"
        reuse = client.post("/auth/reset-password", json={"email": "abaid@example.com", "code": code, "new_password": "again12", "confirm_password": "again12"})
        assert reuse.status_code == 400  # one use only
        assert client.post("/auth/reset-password", json={"token": token, "new_password": "again12", "confirm_password": "again12"}).status_code == 400

        # Link path (new request after the resend wait).
        with Session() as db:
            for record in db.query(models.PasswordResetCode).all():
                record.created_at -= datetime.timedelta(minutes=2)
            db.commit()
        client.post("/auth/forgot-password", json={"email": "abaid@example.com"})
        link_token = re.search(r"reset-password\?token=([\w-]+)", body(sent[-1])).group(1)
        assert client.post("/auth/reset-password/check", json={"token": link_token}).status_code == 200
        assert client.post("/auth/reset-password", json={"token": link_token, "new_password": "linkpass1", "confirm_password": "linkpass1"}).status_code == 200
        assert client.post("/auth/login", json={"email": "abaid@example.com", "password": "linkpass1"}).status_code == 200

        # Five wrong codes cancel the code; expired codes are rejected.
        with Session() as db:
            for record in db.query(models.PasswordResetCode).all():
                record.created_at -= datetime.timedelta(minutes=2)
            db.commit()
        client.post("/auth/forgot-password", json={"email": "abaid@example.com"})
        fresh = re.search(r"reset code is: (\d{6})", body(sent[-1])).group(1)
        wrong = "000000" if fresh != "000000" else "111111"
        for _ in range(4):
            client.post("/auth/reset-password/check", json={"email": "abaid@example.com", "code": wrong})
        locked = client.post("/auth/reset-password/check", json={"email": "abaid@example.com", "code": wrong})
        assert "Too many wrong codes" in locked.json()["detail"]
        assert client.post("/auth/reset-password/check", json={"email": "abaid@example.com", "code": fresh}).status_code == 400
        with Session() as db:
            for record in db.query(models.PasswordResetCode).all():
                record.created_at -= datetime.timedelta(minutes=2)
            db.commit()
        client.post("/auth/forgot-password", json={"email": "abaid@example.com"})
        expiring = re.search(r"reset code is: (\d{6})", body(sent[-1])).group(1)
        with Session() as db:
            latest = db.query(models.PasswordResetCode).order_by(models.PasswordResetCode.id.desc()).first()
            latest.expires_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1)
            db.commit()
        assert "expired" in client.post("/auth/reset-password/check", json={"email": "abaid@example.com", "code": expiring}).json()["detail"]

        # Hourly limit: at most 5 codes per hour.
        with Session() as db:
            db.query(models.PasswordResetCode).delete()
            now = datetime.datetime.now(datetime.timezone.utc)
            user_id = db.query(models.User).filter_by(email="abaid@example.com").one().id
            for minutes in (50, 40, 30, 20, 10):
                db.add(models.PasswordResetCode(user_id=user_id, code_hash="x", token_hash=f"t{minutes}", expires_at=now, created_at=now - datetime.timedelta(minutes=minutes)))
            db.commit()
        count = len(sent)
        client.post("/auth/forgot-password", json={"email": "abaid@example.com"})
        assert len(sent) == count

        # Without Gmail settings the admin fallback is used.
        os.environ["SMTP_USERNAME"] = ""
        assert client.post("/auth/forgot-password", json={"email": "abaid@example.com"}).json()["email_enabled"] is False
    finally:
        email_service.transport = original_transport
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        models.Base.metadata.drop_all(engine)
        engine.dispose()

    print("Password reset tests passed:")
    print("  - same reply for unknown/inactive emails; code + link emailed only to real accounts")
    print("  - hashed storage, one-time use, 5-attempt lock, 10-minute expiry")
    print("  - resend wait and hourly limit; link path; 'password changed' email")
    print("  - admin fallback when Gmail is not configured")


if __name__ == "__main__":
    run_tests()
