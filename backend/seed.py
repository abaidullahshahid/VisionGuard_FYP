"""
Run this once to create the initial admin user in the database.
Usage: python seed.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal, engine
from models import Base, User
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Create all tables first
Base.metadata.create_all(bind=engine)

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

db = SessionLocal()

demo_users = [
    ("Admin User", "admin@visionguard.com", "admin123", "admin"),
    ("Safety Officer", "officer@visionguard.com", "officer123", "officer"),
    ("Field Worker", "worker@visionguard.com", "worker123", "worker"),
]
created = []
try:
    for name, email, password, role in demo_users:
        existing = db.query(User).filter(User.email == email).first()
        if existing is not None:
            print(f"[OK] {email} already exists; its password was not changed.")
            continue
        db.add(User(
            name=name,
            email=email,
            password=hash_password(password),
            role=role,
            status="active",
        ))
        created.append((role.title(), email, password))
    db.commit()

    if created:
        print("[OK] Missing demo users created successfully!")
        print("Credentials for newly created accounts only:")
        for role, email, password in created:
            print(f"  {role}: {email} / {password}")
    else:
        print("[OK] All demo users already exist; no database changes were made.")
finally:
    db.close()
