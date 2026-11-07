
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="CQA API",
    description="Conversation Quality Analytics",
    version="1.0.0"
)

# Allow frontend to communicate with backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return {
        "message": "CQA Backend is running!"
    }


@app.get("/api/health")
def health_check():
    return {
        "status": "OK",
        "project": "Conversation Quality Analytics"
    }
