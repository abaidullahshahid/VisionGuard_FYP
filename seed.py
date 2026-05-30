"""
Run this once to create the initial admin user in the database.
Usage: python seed.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal, engine
from models import Base, User
import hashlib

# Create all tables first
Base.metadata.create_all(bind=engine)

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

db = SessionLocal()

# Check if admin already exists
existing = db.query(User).filter(User.email == "admin@visionguard.com").first()
if existing:
    print("[OK] Admin user already exists!")
    print("   Email:    admin@visionguard.com")
    print("   Password: admin123")
else:
    users_to_create = [
        User(name="Admin User",    email="admin@visionguard.com",   password=hash_password("admin123"),   role="admin",   status="active"),
        User(name="Safety Officer",email="officer@visionguard.com", password=hash_password("officer123"), role="officer", status="active"),
        User(name="Field Worker",  email="worker@visionguard.com",  password=hash_password("worker123"),  role="worker",  status="active"),
    ]
    for u in users_to_create:
        db.add(u)
    db.commit()
    print("[OK] Demo users created successfully!")
    print("")
    print("--------------------------------------------------")
    print("         VisionGuard Login Credentials")
    print("--------------------------------------------------")
    print(" Role     | Email                   | Password   ")
    print("----------|-------------------------|------------")
    print(" Admin    | admin@visionguard.com   | admin123   ")
    print(" Officer  | officer@visionguard.com | officer123 ")
    print(" Worker   | worker@visionguard.com  | worker123  ")
    print("--------------------------------------------------")

db.close()
