from sqlalchemy import inspect
from sqlmodel import SQLModel, Session, create_engine

from hackster_studio.models import Book, Character, Project
from hackster_studio.services.books import upsert_password_dragon_book, upsert_project
from hackster_studio.services.characters import upsert_hackster_niko


def test_database_initialization_creates_tables() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    table_names = set(inspect(engine).get_table_names())

    assert "project" in table_names
    assert "character" in table_names
    assert "book" in table_names
    assert "page" in table_names


def test_seed_data_creation() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        project = upsert_project(session)
        character = upsert_hackster_niko(session)
        book = upsert_password_dragon_book(session)

        assert project.name == "Hackster Niko Universe"
        assert character.name == "Hackster Niko"
        assert book.slug == "book01_password_dragon"
