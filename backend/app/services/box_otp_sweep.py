from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.documents import BoxSweepEvent
from app.models.documents import Document
from app.services.box import get_box_client
from app.services.ingest import IngestService


PRODUCTION_FOLDER_ID = "194227620822"
DEFAULT_QUERIES = (
    "OTP",
    "offer to purchase",
    "purchase agreement",
    "land agreement",
    "agreement of purchase",
    "vacant land",
)
SUPPORTED_EXTENSIONS = {"pdf", "doc", "docx", "tif", "tiff", "jpg", "jpeg", "png"}
SUPPORTING_LABEL = re.compile(
    r"\b(amend(?:ment|ed)?|rebate|extension|assignment|schedule|statement of title|sot|plans?)\b",
    re.IGNORECASE,
)
SALE_LABEL = re.compile(r"\botp[\s_\-()]*sale\b|\bsale[\s_\-()]*otp\b", re.IGNORECASE)
LAND_LABEL = re.compile(
    r"\botp[\s_\-()]*land\b|\bland[\s_\-()]*otp\b|\bland purchase\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class BoxOtpCandidate:
    file_id: str
    name: str
    path: str
    sha1: str | None
    size: int | None
    classification: str
    matched_queries: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BoxOtpSweepResult:
    run_id: UUID
    candidates_found: int
    ingested_document_ids: tuple[UUID, ...]
    skipped: int
    failed: int


def classify_box_otp_filename(filename: str) -> str:
    """Conservatively classify a Box candidate from its filename.

    Supporting/revision documents are never treated as new agreements. Ambiguous
    purchase wording remains `other` so it is logged for review instead of being
    silently or incorrectly ingested.
    """
    stem = Path(filename).stem
    if SUPPORTING_LABEL.search(stem) and (
        "otp" in stem.casefold() or "purchase" in stem.casefold()
    ):
        return "supporting"
    if SALE_LABEL.search(stem):
        return "sale_otp"
    if LAND_LABEL.search(stem):
        return "land_otp"
    return "other"


class BoxOtpSweepService:
    def __init__(self, db: AsyncSession, *, production_folder_id: str = PRODUCTION_FOLDER_ID) -> None:
        self._db = db
        self._production_folder_id = production_folder_id
        self._client = get_box_client()
        if self._client is None:
            raise RuntimeError("Box is unavailable")

    async def run(
        self,
        *,
        apply: bool = False,
        target_file_ids: set[str] | None = None,
        queries: tuple[str, ...] = DEFAULT_QUERIES,
    ) -> BoxOtpSweepResult:
        run_id = uuid4()
        candidates = self._search_candidates(queries)
        targets = target_file_ids or set()
        missing_targets = targets.difference(candidate.file_id for candidate in candidates)
        if missing_targets:
            missing = ", ".join(sorted(missing_targets))
            raise ValueError(f"Selected Box file IDs were not found by the OTP census: {missing}")
        selected = self._select_representatives(candidates, targets)
        pending: list[BoxOtpCandidate] = []
        skipped = 0

        for candidate in candidates:
            representative = selected[self._binary_key(candidate)]
            if not apply:
                self._db.add(
                    self._event(
                        run_id=run_id,
                        candidate=candidate,
                        outcome="dry_run",
                        reason="candidate_discovered",
                        detail={"representative_file_id": representative.file_id},
                    )
                )
                continue
            if representative.file_id != candidate.file_id:
                skipped += 1
                self._db.add(
                    self._event(
                        run_id=run_id,
                        candidate=candidate,
                        outcome="skipped",
                        reason="exact_box_duplicate",
                        detail={"representative_file_id": representative.file_id},
                    )
                )
                continue
            if candidate.file_id not in targets:
                skipped += 1
                self._db.add(
                    self._event(
                        run_id=run_id,
                        candidate=candidate,
                        outcome="skipped",
                        reason="not_selected_for_apply",
                    )
                )
                continue
            if candidate.classification != "land_otp":
                skipped += 1
                self._db.add(
                    self._event(
                        run_id=run_id,
                        candidate=candidate,
                        outcome="skipped",
                        reason=f"classification_{candidate.classification}",
                    )
                )
                continue
            if Path(candidate.name).suffix.casefold() != ".pdf":
                skipped += 1
                self._db.add(
                    self._event(
                        run_id=run_id,
                        candidate=candidate,
                        outcome="skipped",
                        reason="unsupported_ingestion_format",
                    )
                )
                continue
            pending.append(candidate)

        await self._db.commit()

        ingested: list[UUID] = []
        failed = 0
        for candidate in pending:
            try:
                file_bytes = self._client.file(candidate.file_id).content()
                checksum = hashlib.sha256(file_bytes).hexdigest()
                existing_id = await self._db.scalar(
                    select(Document.id).where(Document.checksum_sha256 == checksum).limit(1)
                )
                if existing_id is not None:
                    skipped += 1
                    self._db.add(
                        self._event(
                            run_id=run_id,
                            candidate=candidate,
                            outcome="skipped",
                            reason="already_ingested_checksum",
                            document_id=existing_id,
                        )
                    )
                    await self._db.commit()
                    continue

                upload = UploadFile(filename=candidate.name, file=BytesIO(file_bytes))
                result = await IngestService(self._db).ingest_pdf(file=upload, doc_type="land_otp")
                ingested.append(result.document_id)
                self._db.add(
                    self._event(
                        run_id=run_id,
                        candidate=candidate,
                        outcome="ingested",
                        reason="staged_for_review",
                        document_id=result.document_id,
                        detail={"status": result.status.value, "summary": result.extraction_summary},
                    )
                )
                await self._db.commit()
            except Exception as exc:
                await self._db.rollback()
                failed += 1
                self._db.add(
                    self._event(
                        run_id=run_id,
                        candidate=candidate,
                        outcome="failed",
                        reason="ingestion_error",
                        detail={"error_type": type(exc).__name__, "message": str(exc)[:1000]},
                    )
                )
                await self._db.commit()

        return BoxOtpSweepResult(
            run_id=run_id,
            candidates_found=len(candidates),
            ingested_document_ids=tuple(ingested),
            skipped=skipped,
            failed=failed,
        )

    def _search_candidates(self, queries: tuple[str, ...]) -> list[BoxOtpCandidate]:
        found: dict[str, dict[str, Any]] = {}
        ancestor = [self._client.folder(self._production_folder_id)]
        for query in queries:
            for result in self._client.search().query(
                query=query,
                type="file",
                ancestor_folders=ancestor,
                content_types=["name"],
                file_extensions=sorted(SUPPORTED_EXTENSIONS),
                fields=["id", "name", "size", "sha1", "parent", "path_collection"],
                limit=200,
            ):
                name = str(result.name)
                extension = name.casefold().rsplit(".", 1)[-1]
                if extension not in SUPPORTED_EXTENSIONS:
                    continue
                file_id = str(result.id)
                path_entries = list(
                    getattr(getattr(result, "path_collection", None), "entries", []) or []
                )
                path_parts = [
                    str(entry.name)
                    for entry in path_entries
                    if str(entry.name) != "All Files"
                ]
                parent = getattr(result, "parent", None)
                parent_id = str(getattr(parent, "id", "unknown"))
                parent_name = str(getattr(parent, "name", "") or "").strip()
                parent_label = (
                    f"[Box folder {parent_id}: {parent_name}]"
                    if parent_name
                    else f"[Box folder {parent_id}]"
                )
                record = found.setdefault(
                    file_id,
                    {
                        "file_id": file_id,
                        "name": name,
                        "size": getattr(result, "size", None),
                        "sha1": getattr(result, "sha1", None),
                        "parent_label": parent_label,
                        "path_parts": path_parts,
                        "matched_queries": [],
                    },
                )
                record["matched_queries"].append(query)

        candidates = [
            BoxOtpCandidate(
                file_id=str(record["file_id"]),
                name=str(record["name"]),
                path="/".join(
                    [
                        *(
                            list(record["path_parts"])
                            if record["path_parts"]
                            else [str(record["parent_label"])]
                        ),
                        str(record["name"]),
                    ]
                ),
                sha1=str(record["sha1"]) if record["sha1"] else None,
                size=int(record["size"]) if record["size"] is not None else None,
                classification=classify_box_otp_filename(str(record["name"])),
                matched_queries=tuple(record["matched_queries"]),
            )
            for record in found.values()
        ]
        return sorted(candidates, key=lambda item: item.path.casefold())

    def _select_representatives(
        self,
        candidates: list[BoxOtpCandidate],
        targets: set[str],
    ) -> dict[str, BoxOtpCandidate]:
        groups: dict[str, list[BoxOtpCandidate]] = defaultdict(list)
        for candidate in candidates:
            groups[self._binary_key(candidate)].append(candidate)
        return {
            key: max(items, key=lambda item: self._representative_score(item, targets))
            for key, items in groups.items()
        }

    @staticmethod
    def _binary_key(candidate: BoxOtpCandidate) -> str:
        return candidate.sha1 or f"box-file:{candidate.file_id}"

    @staticmethod
    def _representative_score(candidate: BoxOtpCandidate, targets: set[str]) -> tuple[int, int, str]:
        score = 100 if candidate.file_id in targets else 0
        if "/z - " in candidate.path:
            score += 20
        if "signed" in candidate.name.casefold():
            score += 5
        return score, -candidate.path.count("/"), candidate.path.casefold()

    @staticmethod
    def _event(
        *,
        run_id: UUID,
        candidate: BoxOtpCandidate,
        outcome: str,
        reason: str,
        document_id: UUID | None = None,
        detail: dict[str, Any] | None = None,
    ) -> BoxSweepEvent:
        return BoxSweepEvent(
            run_id=run_id,
            box_file_id=candidate.file_id,
            box_sha1=candidate.sha1,
            box_path=candidate.path,
            classification=candidate.classification,
            outcome=outcome,
            reason=reason,
            document_id=document_id,
            detail={"matched_queries": list(candidate.matched_queries), **(detail or {})},
        )


__all__ = [
    "BoxOtpCandidate",
    "BoxOtpSweepResult",
    "BoxOtpSweepService",
    "classify_box_otp_filename",
]
