"""Environment library service functions."""

from __future__ import annotations

import json

from sqlmodel import Session, select

from ..models import Environment, utc_now


def list_environments(session: Session) -> list[Environment]:
    return list(session.exec(select(Environment).order_by(Environment.name)).all())


def get_environment_by_slug(session: Session, slug: str) -> Environment | None:
    return session.exec(select(Environment).where(Environment.slug == slug)).first()


def upsert_cyber_forest(session: Session) -> Environment:
    palette = {
        "Hackster Blue": "#47C7FF",
        "Core Crystal": "#63DFFF",
        "Forest Green": "#3FAF64",
        "Friendly White": "#F8FCFF",
        "Dark Outline": "#394A63",
    }
    environment = get_environment_by_slug(session, "cyber_forest")
    if environment is None:
        environment = Environment(name="Cyber Forest", slug="cyber_forest")

    environment.description = (
        "A whimsical friendly forest filled with glowing circuit vines, soft green trees, "
        "blue crystals, lock flowers, data streams, rounded stones, tiny helper robots, "
        "and hidden digital creatures."
    )
    environment.visual_language = (
        "Bright, whimsical cyber forest style with rounded stones, gentle light, layered depth, "
        "and clear space for children's book text."
    )
    environment.palette_json = json.dumps(palette, indent=2)
    environment.updated_at = utc_now()
    session.add(environment)
    session.commit()
    session.refresh(environment)
    return environment

