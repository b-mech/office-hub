from __future__ import annotations

import os
import unittest


os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("MINIO_URL", "http://localhost:9000")
os.environ.setdefault("MINIO_ROOT_USER", "minio")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "minio123")
os.environ.setdefault("IMAP_HOST", "localhost")
os.environ.setdefault("IMAP_USER", "test")
os.environ.setdefault("IMAP_PASSWORD", "test")
os.environ.setdefault("IMAP_FOLDER", "INBOX")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("ACTIVE_MODEL_PROVIDER", "claude")
os.environ.setdefault("SECRET_KEY", "test")
os.environ.setdefault("OFFICE_HUB_API_KEY", "test")
os.environ.setdefault("DEFAULT_ORG_ID", "00000000-0000-0000-0000-000000000001")
os.environ.setdefault("ENVIRONMENT", "test")

from app.services.extraction.prompts import SALE_OTP_PROMPT
from app.services.ocr.extractor import PDFExtractor


class SaleOtpPaymentExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.extractor = PDFExtractor()

    def test_payment_form_page_gets_image_ocr_supplement(self) -> None:
        text = """
        5. PAYMENTS: Purchase price paid as follows
        a) Deposit
        b) Additional Deposit
        c) Land payment
        d) Basement stage
        e) Roof stage
        f) Drywall Stage
        g) Possession Date
        """

        self.assertTrue(self.extractor._should_supplement_with_image_ocr(text))

    def test_unrelated_contract_page_does_not_get_supplement(self) -> None:
        self.assertFalse(
            self.extractor._should_supplement_with_image_ocr(
                "Schedule C standard specifications and finishes"
            )
        )

    def test_prompt_protects_payment_schedule_semantics(self) -> None:
        self.assertIn("- percent", SALE_OTP_PROMPT)
        self.assertIn("A dash means no amount is stated", SALE_OTP_PROMPT)
        self.assertIn("Never copy the", SALE_OTP_PROMPT)
        self.assertIn("reconcile all non-null payment amounts", SALE_OTP_PROMPT)


if __name__ == "__main__":
    unittest.main()
