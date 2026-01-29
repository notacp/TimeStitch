from backend.app.main import app

# This is specific for Vercel. 
# It exposes the FastAPI app as a serverless function handler.
app = app
