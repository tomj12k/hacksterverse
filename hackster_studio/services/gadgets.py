"""Gadget library service functions."""

from __future__ import annotations

from sqlmodel import Session, select

from ..models import Gadget, utc_now


def list_gadgets(session: Session) -> list[Gadget]:
    return list(session.exec(select(Gadget).order_by(Gadget.name)).all())


def get_gadget_by_slug(session: Session, slug: str) -> Gadget | None:
    return session.exec(select(Gadget).where(Gadget.slug == slug)).first()


def upsert_code_scanner(session: Session) -> Gadget:
    gadget = get_gadget_by_slug(session, "code_scanner")
    if gadget is None:
        gadget = Gadget(name="Code Scanner", slug="code_scanner")

    gadget.description = (
        "A child-safe handheld scanner that helps Niko understand clues, inspect code patterns, "
        "and find hidden bugs."
    )
    gadget.design_notes = (
        "Rounded handheld scanner with a soft white shell, blue glowing lens, friendly indicator "
        "lights, chunky grip, and small Core Crystal accent."
    )
    gadget.safety_notes = "Must read as a learning tool, never a weapon. Avoid triggers and sharp edges."
    gadget.updated_at = utc_now()
    session.add(gadget)
    session.commit()
    session.refresh(gadget)
    return gadget

