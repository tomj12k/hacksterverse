"""Character library service functions."""

from __future__ import annotations

import json

from sqlmodel import Session, select

from ..models import Character, utc_now


NIKO_CONSISTENCY_PHRASE = (
    "small friendly learning robot, glossy white ceramic shell, rounded helmet-like head, "
    "smooth dark glass LED face with expressive glowing blue eyes only and no mouth, "
    "tiny antenna with glowing blue tip, blank blue hoodie with a plain circular glowing cyan Core Crystal, "
    "floating magnetic backpack, blank cuffs, blank chunky sneakers, utility belt, child-friendly rounded shapes."
)


def list_characters(session: Session) -> list[Character]:
    return list(session.exec(select(Character).order_by(Character.name)).all())


def get_character(session: Session, character_id: int) -> Character | None:
    return session.get(Character, character_id)


def get_character_by_slug(session: Session, slug: str) -> Character | None:
    return session.exec(select(Character).where(Character.slug == slug)).first()


def upsert_hackster_niko(session: Session) -> Character:
    colors = {
        "Hackster Blue": "#47C7FF",
        "Core Crystal": "#63DFFF",
        "Hoodie Blue": "#2E8CFF",
        "Friendly White": "#F8FCFF",
        "Dark Outline": "#394A63",
        "Golden Gear": "#F2C94C",
    }
    character = get_character_by_slug(session, "hackster_niko")
    if character is None:
        character = Character(name="Hackster Niko", slug="hackster_niko")

    character.role = "Junior Hackster"
    character.description = (
        "A small friendly learning robot who solves problems with kindness, curiosity, "
        "creativity, teamwork, and responsible technology."
    )
    character.appearance = NIKO_CONSISTENCY_PHRASE
    character.personality = "curious, kind, optimistic, brave, funny, inventive, patient, never gives up."
    character.colors_json = json.dumps(colors, indent=2)
    character.style_notes = (
        "Catchphrase: Every problem has a clever fix! Use rounded friendly shapes, "
        "soft cinematic lighting, saturated colors, no weapons, and no scary imagery."
    )
    character.updated_at = utc_now()
    session.add(character)
    session.commit()
    session.refresh(character)
    return character
