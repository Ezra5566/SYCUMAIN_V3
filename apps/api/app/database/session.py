"""Database session and engine configuration."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config.settings import get_settings

settings = get_settings()

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    # Statement echo prints bound parameters, which here are personal data. It
    # is a separate opt-in rather than a side effect of DEBUG.
    echo=settings.SQL_ECHO,
    # Even with echo off, SQLAlchemy writes the failing statement *and its
    # parameters* to the log when a database error is raised. Those parameters
    # are the student's name, number and date of birth. This keeps the statement
    # text (useful) and masks the values (personal data).
    hide_parameters=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


def get_db() -> Generator[Session, None, None]:
    """Dependency that provides a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
