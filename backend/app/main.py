import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import auth, scoring, incidents

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Second Sense API",
    description="Continuous behavioral authentication and fraud detection API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(scoring.router)
app.include_router(incidents.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
