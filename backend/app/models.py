import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Float, ForeignKey, JSON, Integer, Text
from sqlalchemy.orm import relationship

from app.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    baseline = relationship("BehaviorBaseline", back_populates="user", uselist=False)
    incidents = relationship("Incident", back_populates="user")


class BehaviorBaseline(Base):
    """Persisted EWMA scorer state (mean vector + covariance matrix) per user."""
    __tablename__ = "behavior_baselines"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), unique=True, nullable=False)
    mean = Column(JSON, nullable=True)     # list[float]
    cov = Column(JSON, nullable=True)      # list[list[float]]
    sample_count = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="baseline")


class SessionScore(Base):
    """Audit log: every scored session/event batch, for history + review."""
    __tablename__ = "session_scores"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    risk_score = Column(Float, nullable=False)
    feature_vector = Column(JSON, nullable=False)
    ip_address = Column(String, nullable=True)
    ip_risk_context = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Incident(Base):
    """Fired when a session's risk score crosses the alert threshold."""
    __tablename__ = "incidents"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    session_score_id = Column(String, nullable=True)
    risk_score = Column(Float, nullable=False)
    status = Column(String, default="open")  # open | acknowledged | false_positive
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="incidents")
