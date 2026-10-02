from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image

from app.services.maintenance.errors import InvalidMediaError
from app.services.maintenance.media import (
    MAX_FILE_BYTES,
    create_signed_media_token,
    process_media,
    verify_signed_media_token,
    validate_file_count,
)
from app.models.maintenance import MaintParty


def test_image_is_resaved_without_exif() -> None:
    original = BytesIO()
    image = Image.new("RGB", (20, 20), "red")
    exif = Image.Exif()
    exif[0x010E] = "private metadata"
    image.save(original, format="JPEG", exif=exif)

    processed = process_media(original.getvalue())

    with Image.open(BytesIO(processed.content)) as result:
        assert not result.getexif()


def test_pdf_is_invoice_only() -> None:
    with pytest.raises(InvalidMediaError, match="invoices"):
        process_media(b"%PDF-1.7\n", kind="photo")
    assert process_media(b"%PDF-1.7\n", kind="invoice").content_type == "application/pdf"


def test_oversize_file_is_rejected() -> None:
    with pytest.raises(InvalidMediaError, match="10 MB"):
        process_media(b"x" * (MAX_FILE_BYTES + 1))


def test_party_upload_limits() -> None:
    validate_file_count(5, party=MaintParty.TENANT)
    validate_file_count(10, party=MaintParty.VENDOR)
    with pytest.raises(InvalidMediaError, match="maximum of 5"):
        validate_file_count(6, party=MaintParty.TENANT)
    with pytest.raises(InvalidMediaError, match="maximum of 10"):
        validate_file_count(11, party=MaintParty.VENDOR)


def test_heic_is_converted_to_jpeg_without_exif() -> None:
    pytest.importorskip("pillow_heif")
    from pillow_heif import from_pillow

    image = Image.new("RGB", (12, 12), "blue")
    exif = Image.Exif()
    exif[0x010E] = "private"
    image.info["exif"] = exif.tobytes()
    original = BytesIO()
    from_pillow(image).save(original, save_all=True)

    processed = process_media(original.getvalue())
    assert processed.content_type == "image/jpeg"
    with Image.open(BytesIO(processed.content)) as result:
        assert not result.getexif()


def test_signed_media_token_is_scoped_and_expires() -> None:
    attachment_id = uuid4()
    token = create_signed_media_token(attachment_id, "test-secret", now=100, expires_in_seconds=60)
    assert verify_signed_media_token(token, "test-secret", now=159) == attachment_id
    with pytest.raises(InvalidMediaError):
        verify_signed_media_token(token, "wrong-secret", now=159)
    with pytest.raises(InvalidMediaError):
        verify_signed_media_token(token, "test-secret", now=161)
