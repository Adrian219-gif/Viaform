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

Create `backend/.env` with a DeepSeek API key. The retrieval flow uses
DeepSeek's server-side Web Search; separate Bocha/Tavily keys are not required.

```dotenv
DEEPSEEK_API_KEY=your_key_here
```

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. Interactive API documentation is available at
<http://127.0.0.1:8000/docs>.

## Application Timeline retrieval

After a target program is selected, the frontend sends its university, program
URL, and intended entry year/term to `POST /target-programs/timeline`. The
backend makes one DeepSeek Messages request with server-side Web Search and
returns current official application dates as structured data. Missing or
imprecise official dates remain missing or imprecise; the backend does not add
an HTML fetch, verifier, secondary search provider, or guessed date.
