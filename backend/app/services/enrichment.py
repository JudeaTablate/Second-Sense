"""
Enriches a session with IP/geo context from a third-party API. This
sits alongside the behavioral risk score — a high behavioral anomaly
from a residential IP in the user's usual country is treated
differently than the same anomaly from a datacenter IP in a new
country, which is a classic ATO fraud signal.

Uses ipapi.co's free tier by default (no key required for low volume).
Swap IP_ENRICHMENT_API_URL in config for a paid provider like
IPQualityScore for production-grade fraud signals.
"""

from __future__ import annotations

import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import settings

logger = logging.getLogger("secondsense.enrichment")


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=0.3, min=0.3, max=2),
    retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
    reraise=False,
)
def get_ip_risk_context(ip_address: str) -> dict:
    """Returns geo/risk context for an IP, or a safe empty default on failure."""
    if not ip_address or ip_address in ("127.0.0.1", "testclient", "unknown"):
        return {"country": None, "is_datacenter": None, "note": "local/unknown ip, skipped"}

    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{settings.IP_ENRICHMENT_API_URL}/{ip_address}/json/")
            resp.raise_for_status()
            data = resp.json()
            return {
                "country": data.get("country_name"),
                "region": data.get("region"),
                "org": data.get("org"),
                "is_datacenter": "hosting" in (data.get("org") or "").lower(),
            }
    except Exception as exc:  # noqa: BLE001 - enrichment is best-effort, never fatal
        logger.warning(f"IP enrichment failed for {ip_address}: {exc}")
        return {"country": None, "is_datacenter": None, "error": "enrichment_unavailable"}
