"""Page lookup and editing helpers."""

from __future__ import annotations

from sqlmodel import Session, select

from ..models import Page


def get_page(session: Session, page_id: int) -> Page | None:
    return session.get(Page, page_id)


def list_pages_for_book(session: Session, book_id: int) -> list[Page]:
    return list(
        session.exec(select(Page).where(Page.book_id == book_id).order_by(Page.page_number)).all()
    )


def update_page_text(
    session: Session,
    page_id: int,
    story_text: str,
    illustration_direction: str,
) -> Page:
    page = session.get(Page, page_id)
    if page is None:
        raise ValueError(f"Page not found: {page_id}")

    page.story_text = story_text
    page.illustration_direction = illustration_direction
    page.status = "edited"
    session.add(page)
    session.commit()
    session.refresh(page)
    return page

