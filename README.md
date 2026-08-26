# AI University Application Analysis MVP

This repository contains two independent applications:

- `frontend`: Next.js + TypeScript
- `backend`: FastAPI + Python

## Start the frontend

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>.

## Start the backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. Interactive API documentation is available at
<http://127.0.0.1:8000/docs>.
