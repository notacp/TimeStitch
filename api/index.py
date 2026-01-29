import sys
import os
from pathlib import Path

# Add the backend directory to the Python path
# This allows 'from app.main import app' and internal 'from app.routers' to work on Vercel
backend_path = str(Path(__file__).parent.parent / "backend")
if backend_path not in sys.path:
    sys.path.append(backend_path)

from app.main import app

# Vercel expects the FastAPI instance to be named 'app'
app = app
