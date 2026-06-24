from sqlmodel import SQLModel, Session, create_engine, select

from hackster_studio.models import Page
from hackster_studio.services.books import plan_book, upsert_password_dragon_book
import hackster_studio.services.books as book_service


def test_book_planner_creates_32_pages(tmp_path, monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(book_service, "PROJECT_ROOT", tmp_path)

    with Session(engine) as session:
        book = upsert_password_dragon_book(session)
        pages = plan_book(session, book.slug)

        saved_pages = session.exec(select(Page).where(Page.book_id == book.id)).all()

    assert len(pages) == 32
    assert len(saved_pages) == 32
    assert pages[0].page_type == "front_matter"
    assert pages[30].page_type == "activity"
    assert pages[31].page_type == "teaser"
