# VisionGuard — Smart Workplace Safety Management System

Final Year Project, Department of Software Engineering, FAST-NUCES Chiniot-Faisalabad.
Team: Abaidullah Shahid (22F-3732), Adnan Hussain (22F-3696), Maliha Munir (22F-3647).
Supervisor: Saqib Ameer.

VisionGuard watches workplace cameras with computer vision, detects missing PPE
(helmet, safety vest, gloves) and entry into restricted areas, records each
violation as an incident with a snapshot, and alerts safety officers in the app
and by email.

## Features

- **Admin:** users and roles, locations, cameras (webcam, RTSP/IP, mobile camera, video file),
  safety rules (one or more PPE items, or restricted areas), restricted zones drawn on camera views,
  email alert settings.
- **Safety officer:** live video feed with AI detection, incident register with evidence,
  corrective actions, safety instructions, daily compliance records with CSV export.
- **Worker:** assigned locations, safety instructions to acknowledge, assigned tasks.

## Project structure

| Folder | Contents |
|---|---|
| `frontend/` | React web app (Create React App) |
| `backend/` | FastAPI REST API, PostgreSQL models, services |
| `backend/ai_module/` | YOLO11 PPE detection, tracking, violation and restricted-zone engines |

## Requirements

- Python 3.10 or newer
- Node.js 18 or newer
- PostgreSQL with a database named `visionguard`
- A webcam, phone camera app or RTSP camera (optional for testing: a video file)

## Setup (first time)

**Backend**

```
cd backend
python -m venv venv
venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```

Edit `backend/.env`: database URL, a secret key, and a Gmail address with an
App Password for alert emails. Then create the demo accounts:

```
venv\Scripts\python seed.py
```

Optional, faster AI on Intel CPUs:

```
venv\Scripts\python export_openvino.py
```

**Frontend**

```
cd frontend
npm install
```

## Run

Use two terminals and keep both open.

```
cd backend
venv\Scripts\python -m uvicorn main:app --reload --port 8000
```

```
cd frontend
npm start
```

Open http://localhost:3000. The API documentation is at http://127.0.0.1:8000/docs.

## Tests

```
cd backend
venv\Scripts\python test_rules_and_deletes.py
venv\Scripts\python test_compliance_alerts.py
venv\Scripts\python test_workflows.py
```

(each `test_*.py` file runs on its own with an in-memory database)

```
cd frontend
npm test
```

## Not in the repository

`backend/.env` (private settings), the Python `venv`, `node_modules`, large test
videos and the generated OpenVINO model folder (rebuilt by `export_openvino.py`).
