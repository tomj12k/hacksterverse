from sqlmodel import SQLModel, Session, create_engine

from hackster_studio.services.books import plan_book, upsert_password_dragon_book
from hackster_studio.services.prompts import generate_prompts_for_book
import hackster_studio.services.books as book_service
import hackster_studio.services.prompts as prompt_service


def test_prompt_generation_creates_page_prompts(tmp_path, monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(book_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(prompt_service, "GENERATED_DIR", tmp_path)

    with Session(engine) as session:
        book = upsert_password_dragon_book(session)
        plan_book(session, book.slug)
        prompts = generate_prompts_for_book(session, book.slug)

    assert len(prompts) == 32
    assert "full-bleed 8.75 x 8.75 inch" in prompts[3].prompt_text
    assert (tmp_path / "prompts" / "pages" / "book01_password_dragon").exists()
