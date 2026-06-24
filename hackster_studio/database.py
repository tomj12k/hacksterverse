"""SQLite database setup for Hackster Studio."""

from __future__ import annotations

from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

from .config import DATABASE_PATH, ensure_project_dirs


def database_url() -> str:
    return f"sqlite:///{DATABASE_PATH}"


engine = create_engine(database_url(), connect_args={"check_same_thread": False})


def init_db() -> None:
    """Create the SQLite database and all tables."""
    ensure_project_dirs()
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session

