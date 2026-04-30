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
os.environ.setdefault("ENVIRONMENT", "test")

from app.services.extraction.claude_provider import ClaudeProvider


class ClaudeProviderParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = ClaudeProvider.__new__(ClaudeProvider)

    def test_parse_plain_json_object(self) -> None:
        parsed = self.provider._parse_json_response(
            '{"agreement": {"development_name": "Parkview"}, "field_confidences": {}}'
        )

        self.assertEqual(parsed["agreement"]["development_name"], "Parkview")

    def test_parse_fenced_json_object(self) -> None:
        parsed = self.provider._parse_json_response(
            '```json\n{"agreement": {}, "field_confidences": {}}\n```'
        )

        self.assertEqual(parsed["agreement"], {})

    def test_parse_json_object_with_prefix_and_suffix(self) -> None:
        parsed = self.provider._parse_json_response(
            'Here is the extraction:\n{"agreement": {}, "field_confidences": {}}\nDone.'
        )

        self.assertEqual(parsed["field_confidences"], {})

    def test_parse_json_object_with_trailing_commas(self) -> None:
        parsed = self.provider._parse_json_response(
            (
                '{"agreement": {"development_name": "Parkview",}, '
                '"lots": [], "field_confidences": {},}'
            )
        )

        self.assertEqual(parsed["agreement"]["development_name"], "Parkview")

    def test_non_object_json_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.provider._parse_json_response('["not", "an", "object"]')


if __name__ == "__main__":
    unittest.main()
