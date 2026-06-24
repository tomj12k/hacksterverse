from PIL import Image
from sqlmodel import SQLModel, Session, create_engine

from hackster_studio.services.print_validator import validate_image_for_print


def test_print_validator_catches_too_small_images(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    image_path = tmp_path / "small.png"
    Image.new("RGB", (1000, 1000), "white").save(image_path, dpi=(300, 300))

    with Session(engine) as session:
        report = validate_image_for_print(session, image_path)

    assert report.pass_fail is False
    assert report.width_px == 1000
    assert "too small" in report.notes

