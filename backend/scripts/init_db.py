"""
Creates all tables if they don't exist. Run this once before starting
the app (see docker-compose.yml command / entrypoint).

For a real production system you'd replace this with Alembic
migrations, which give you versioned, reversible schema changes
instead of a blunt create_all. This is intentionally simple for a
portfolio project.
"""

from app.database import Base, engine
from app import models  # noqa: F401 - needed so models register on Base.metadata

if __name__ == "__main__":
    print("Creating tables if they don't exist...")
    Base.metadata.create_all(bind=engine)
    print("Done.")
