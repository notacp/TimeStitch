# ⏱️ TimeStitch - Ctrl+F for YouTube

Modern web application to search inside YouTube video transcripts.

## Tech Stack
- **Frontend**: Next.js 14, TailwindCSS, Framer Motion
- **Backend**: FastAPI, YouTube Data API, YouTube Transcript API

## Getting Started

### 1. Prerequisites
- Python 3.8+
- Node.js 18+
- YouTube Data API Key

### 2. Setup Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```
Create a `.env` file in `backend/`:
```env
YT_API_KEY=your_youtube_api_key_here
```
Run the backend:
```bash
uvicorn app.main:app --reload
```

### 3. Setup Frontend
```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) to use the app.
