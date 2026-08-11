from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class InputEvent(BaseModel):
    type: str  # "keydown" | "keyup" | "mousemove"
    timestamp: float
    key: str | None = None
    x: float | None = None
    y: float | None = None


class IngestRequest(BaseModel):
    events: list[InputEvent]


class ScoreResponse(BaseModel):
    risk_score: float
    is_anomalous: bool
    feature_vector: list[float]
    baseline_sample_count: int
    scored_at: datetime


class IncidentResponse(BaseModel):
    id: str
    risk_score: float
    status: str
    created_at: datetime

    class Config:
        from_attributes = True
