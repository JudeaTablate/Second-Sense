from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, BehaviorBaseline, SessionScore, Incident
from app.schemas import IngestRequest, ScoreResponse
from app.auth_utils import get_current_user
from app.config import settings
from app.scoring.ewma import EWMAAnomalyScorer
from app.scoring.features import extract_features, N_FEATURES
from app.services import redis_client
from app.services.alerting import fire_incident_alerts
from app.services.enrichment import get_ip_risk_context

router = APIRouter(prefix="/sessions", tags=["scoring"])


def _load_scorer(db: Session, user: User) -> EWMAAnomalyScorer:
    """Load a user's scorer state: Redis cache first, falling back to
    Postgres, falling back to a fresh cold-start scorer."""
    cached = redis_client.get_cached_baseline_state(user.id)
    if cached:
        return EWMAAnomalyScorer.from_state(
            cached, n_features=N_FEATURES, lam=settings.EWMA_LAMBDA, shrinkage=settings.EWMA_SHRINKAGE
        )

    baseline = db.query(BehaviorBaseline).filter(BehaviorBaseline.user_id == user.id).first()
    if baseline and baseline.mean is not None:
        state = {"mean": baseline.mean, "cov": baseline.cov, "count": baseline.sample_count}
        return EWMAAnomalyScorer.from_state(
            state, n_features=N_FEATURES, lam=settings.EWMA_LAMBDA, shrinkage=settings.EWMA_SHRINKAGE
        )

    return EWMAAnomalyScorer(n_features=N_FEATURES, lam=settings.EWMA_LAMBDA, shrinkage=settings.EWMA_SHRINKAGE)


def _persist_scorer(db: Session, user: User, scorer: EWMAAnomalyScorer) -> None:
    state = scorer.to_state()
    redis_client.cache_baseline_state(user.id, state)

    baseline = db.query(BehaviorBaseline).filter(BehaviorBaseline.user_id == user.id).first()
    if not baseline:
        baseline = BehaviorBaseline(user_id=user.id)
        db.add(baseline)

    baseline.mean = state["mean"]
    baseline.cov = state["cov"]
    baseline.sample_count = state["count"]
    db.commit()


@router.post("/ingest", response_model=ScoreResponse)
def ingest_session(
    payload: IngestRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Core pipeline: takes a batch of raw keystroke/mouse events,
    extracts behavioral features, scores against the user's rolling
    baseline, persists the audit trail, and fires alerts if the risk
    score crosses the threshold.
    """
    events = [e.model_dump() for e in payload.events]
    feature_vector = extract_features(events)

    scorer = _load_scorer(db, user)
    risk_score = scorer.score_and_update(feature_vector)
    _persist_scorer(db, user, scorer)

    client_ip = request.client.host if request.client else "unknown"
    ip_context = get_ip_risk_context(client_ip)

    session_score = SessionScore(
        user_id=user.id,
        risk_score=risk_score,
        feature_vector=feature_vector.tolist(),
        ip_address=client_ip,
        ip_risk_context=ip_context,
    )
    db.add(session_score)
    db.commit()
    db.refresh(session_score)

    is_anomalous = risk_score >= settings.RISK_ALERT_THRESHOLD
    if is_anomalous:
        incident = Incident(user_id=user.id, session_score_id=session_score.id, risk_score=risk_score)
        db.add(incident)
        db.commit()
        fire_incident_alerts(user_email=user.email, risk_score=risk_score)

    return ScoreResponse(
        risk_score=round(risk_score, 2),
        is_anomalous=is_anomalous,
        feature_vector=feature_vector.tolist(),
        baseline_sample_count=scorer.count,
        scored_at=datetime.utcnow(),
    )
