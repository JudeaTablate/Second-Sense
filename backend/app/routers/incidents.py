from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Incident
from app.schemas import IncidentResponse
from app.auth_utils import get_current_user

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("", response_model=list[IncidentResponse])
def list_incidents(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return (
        db.query(Incident)
        .filter(Incident.user_id == user.id)
        .order_by(Incident.created_at.desc())
        .limit(50)
        .all()
    )
