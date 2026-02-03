from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import search
from dotenv import load_dotenv
import os

from pathlib import Path

# Load .env from the root directory (3 levels up from this file)
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

app = FastAPI(title="TimeStitch API")

# Add CORS middleware to allow requests from the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, replace with specific frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search.router, prefix="/api")

@app.get("/")
async def root():
    return {"message": "TimeStitch API is running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
