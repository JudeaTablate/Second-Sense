"""
Central config, loaded from environment variables (12-factor style).
In docker-compose these are set in the `environment:` block; in
production (ECS/Fly.io) they'd come from the platform's secret store.
"""

import os


class Settings:
    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "postgresql://secondsense:secondsense@localhost:5432/secondsense"
    )

    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Auth
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-secret-change-me")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

    # Scoring engine
    EWMA_LAMBDA: float = float(os.getenv("EWMA_LAMBDA", "0.2"))
    EWMA_SHRINKAGE: float = float(os.getenv("EWMA_SHRINKAGE", "0.1"))
    RISK_ALERT_THRESHOLD: float = float(os.getenv("RISK_ALERT_THRESHOLD", "70.0"))

    # Third-party integrations (leave blank to run in "mocked" mode)
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM_NUMBER: str = os.getenv("TWILIO_FROM_NUMBER", "")
    ALERT_SMS_TO: str = os.getenv("ALERT_SMS_TO", "")

    SENDGRID_API_KEY: str = os.getenv("SENDGRID_API_KEY", "")
    ALERT_EMAIL_FROM: str = os.getenv("ALERT_EMAIL_FROM", "alerts@secondsense.dev")
    ALERT_EMAIL_TO: str = os.getenv("ALERT_EMAIL_TO", "")

    IP_ENRICHMENT_API_URL: str = os.getenv(
        "IP_ENRICHMENT_API_URL", "https://ipapi.co"
    )

    # CORS - comma separated list of allowed origins
    CORS_ORIGINS: list[str] = os.getenv("CORS_ORIGINS", "http://localhost:5500").split(",")


settings = Settings()
