"""
Fires fraud alerts through multiple channels when a session's risk
score crosses the threshold. Every provider call is wrapped in retry
with exponential backoff (tenacity), and every provider degrades
independently — if Twilio is down, email/webhook still fire.

Runs in "mocked" mode automatically when API keys aren't configured,
so the whole pipeline is testable/demoable without real accounts.
"""

from __future__ import annotations

import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import settings

logger = logging.getLogger("secondsense.alerting")

RETRYABLE_EXC = (httpx.TransportError, httpx.TimeoutException)


def _mocked(reason: str) -> dict:
    logger.info(f"[MOCK ALERT] {reason}")
    return {"status": "mocked", "reason": reason}


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    retry=retry_if_exception_type(RETRYABLE_EXC),
    reraise=True,
)
def send_sms_alert(user_email: str, risk_score: float) -> dict:
    if not settings.TWILIO_ACCOUNT_SID or not settings.ALERT_SMS_TO:
        return _mocked(f"SMS alert for {user_email} (risk={risk_score:.1f}) — no Twilio creds set")

    url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Messages.json"
    body = {
        "From": settings.TWILIO_FROM_NUMBER,
        "To": settings.ALERT_SMS_TO,
        "Body": f"[Second Sense] High-risk session for {user_email}: risk score {risk_score:.1f}/100",
    }
    with httpx.Client(timeout=5.0) as client:
        resp = client.post(
            url,
            data=body,
            auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
        )
        resp.raise_for_status()
        return {"status": "sent", "provider": "twilio", "sid": resp.json().get("sid")}


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
    retry=retry_if_exception_type(RETRYABLE_EXC),
    reraise=True,
)
def send_email_alert(user_email: str, risk_score: float) -> dict:
    if not settings.SENDGRID_API_KEY or not settings.ALERT_EMAIL_TO:
        return _mocked(f"Email alert for {user_email} (risk={risk_score:.1f}) — no SendGrid key set")

    payload = {
        "personalizations": [{"to": [{"email": settings.ALERT_EMAIL_TO}]}],
        "from": {"email": settings.ALERT_EMAIL_FROM},
        "subject": f"[Second Sense] High-risk session detected — {user_email}",
        "content": [{
            "type": "text/plain",
            "value": f"User {user_email} triggered risk score {risk_score:.1f}/100. Review in dashboard.",
        }],
    }
    with httpx.Client(timeout=5.0) as client:
        resp = client.post(
            "https://api.sendgrid.com/v3/mail/send",
            json=payload,
            headers={"Authorization": f"Bearer {settings.SENDGRID_API_KEY}"},
        )
        resp.raise_for_status()
        return {"status": "sent", "provider": "sendgrid"}


def fire_incident_alerts(user_email: str, risk_score: float, webhook_url: str | None = None) -> list[dict]:
    """Fan out to all configured channels. Each failure is caught and
    logged independently so one bad provider doesn't block the others."""
    results = []
    for fn, name in [(send_sms_alert, "sms"), (send_email_alert, "email")]:
        try:
            results.append(fn(user_email, risk_score))
        except Exception as exc:  # noqa: BLE001 - alerting must never crash the request
            logger.error(f"{name} alert failed after retries: {exc}")
            results.append({"status": "failed", "provider": name, "error": str(exc)})

    if webhook_url:
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(webhook_url, json={"user": user_email, "risk_score": risk_score})
                resp.raise_for_status()
                results.append({"status": "sent", "provider": "webhook"})
        except Exception as exc:  # noqa: BLE001
            logger.error(f"webhook alert failed: {exc}")
            results.append({"status": "failed", "provider": "webhook", "error": str(exc)})

    return results
