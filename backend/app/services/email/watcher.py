from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from email import message_from_bytes
from email.message import Message
from email.utils import parseaddr
from email.utils import parsedate_to_datetime
from pathlib import Path

from imapclient import IMAPClient

from app.core.config import settings


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IncomingDocument:
    filename: str
    file_path: Path
    sender_email: str
    received_at: datetime
    file_size_bytes: int
    checksum_sha256: str


class EmailWatcher:
    def __init__(self) -> None:
        self.imap_host = settings.imap_host
        self.imap_user = settings.imap_user
        self.imap_password = settings.imap_password
        self.imap_folder = settings.imap_folder
        self.staging_dir = Path("data/staging")
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.poll_interval_seconds = 60

    def connect(self) -> IMAPClient:
        client = IMAPClient(self.imap_host)
        client.login(self.imap_user, self.imap_password)
        client.select_folder(self.imap_folder)
        return client

    def poll(self) -> list[IncomingDocument]:
        documents: list[IncomingDocument] = []

        try:
            with self.connect() as client:
                message_ids = client.search(["UNSEEN"])
                for msg_id in message_ids:
                    try:
                        message_documents = self._process_message(client, msg_id)
                        documents.extend(message_documents)
                        client.add_flags(msg_id, [b"\\Seen"])
                    except Exception:
                        logger.exception("Failed to process IMAP message %s", msg_id)
        except Exception:
            logger.exception("Email polling failed")
            return []

        return documents

    def _process_message(self, client: IMAPClient, msg_id: int) -> list[IncomingDocument]:
        response = client.fetch([msg_id], ["RFC822", "INTERNALDATE"])
        message_data = response[msg_id]
        raw_message = message_data[b"RFC822"]
        message = message_from_bytes(raw_message)

        sender_email = parseaddr(message.get("From", ""))[1]
        received_at = self._resolve_received_at(
            message=message,
            internal_date=message_data.get(b"INTERNALDATE"),
        )

        documents: list[IncomingDocument] = []
        for part in message.walk():
            if part.get_content_type() != "application/pdf":
                continue

            payload = part.get_payload(decode=True)
            if payload is None:
                continue

            filename = part.get_filename() or "attachment.pdf"
            documents.append(
                self._save_attachment(
                    payload=payload,
                    filename=filename,
                    sender_email=sender_email,
                    received_at=received_at,
                )
            )

        return documents

    def _save_attachment(
        self,
        payload: bytes,
        filename: str,
        sender_email: str,
        received_at: datetime,
    ) -> IncomingDocument:
        sanitized_name = Path(filename).name or "attachment.pdf"
        timestamp = received_at.strftime("%Y%m%d%H%M%S")
        unique_filename = f"{timestamp}_{sanitized_name}"
        file_path = self.staging_dir / unique_filename
        file_path.write_bytes(payload)

        return IncomingDocument(
            filename=unique_filename,
            file_path=file_path,
            sender_email=sender_email,
            received_at=received_at,
            file_size_bytes=len(payload),
            checksum_sha256=self._calculate_checksum(payload),
        )

    def _calculate_checksum(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def run_forever(self) -> None:
        while True:
            try:
                documents = self.poll()
                logger.info("Email poll complete. Found %s document(s).", len(documents))
            except Exception:
                logger.exception("Unexpected error in email watcher loop")

            time.sleep(self.poll_interval_seconds)

    def _resolve_received_at(
        self,
        message: Message,
        internal_date: object,
    ) -> datetime:
        date_header = message.get("Date")
        if date_header:
            try:
                return parsedate_to_datetime(date_header)
            except (TypeError, ValueError, IndexError):
                logger.warning("Failed to parse Date header: %s", date_header)

        if isinstance(internal_date, datetime):
            return internal_date

        return datetime.now()
