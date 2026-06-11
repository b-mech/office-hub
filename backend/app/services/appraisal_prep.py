from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp
from zipfile import ZIP_DEFLATED
from zipfile import ZipFile

from app.services.box import get_box_client


class AppraisalPrepError(RuntimeError):
    pass


class AppraisalPrepBoxUnavailableError(AppraisalPrepError):
    pass


@dataclass(frozen=True)
class AppraisalPrepPackage:
    zip_path: Path
    temp_dir: Path
    filename: str
    file_count: int

    def cleanup(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)


def create_appraisal_prep_package(
    *,
    box_file_ids: list[str],
    package_name: str = "appraisal-prep",
) -> AppraisalPrepPackage:
    file_ids = [file_id.strip() for file_id in box_file_ids if file_id.strip()]
    if not file_ids:
        raise AppraisalPrepError("At least one Box file ID is required.")

    client = get_box_client()
    if client is None:
        raise AppraisalPrepBoxUnavailableError("Box is not configured or authenticated.")

    temp_dir = Path(mkdtemp(prefix="office-hub-appraisal-prep-"))
    documents_dir = temp_dir / "documents"
    documents_dir.mkdir(parents=True, exist_ok=True)

    try:
        used_names: set[str] = set()
        downloaded_paths: list[Path] = []
        for file_id in file_ids:
            box_file = client.file(file_id).get(fields=["id", "name"])
            filename = _unique_filename(
                _safe_filename(str(getattr(box_file, "name", "") or f"{file_id}.pdf")),
                used_names,
            )
            destination = documents_dir / filename
            with destination.open("wb") as output:
                box_file.download_to(output)
            downloaded_paths.append(destination)

        zip_filename = f"{_safe_stem(package_name) or 'appraisal-prep'}.zip"
        zip_path = temp_dir / zip_filename
        with ZipFile(zip_path, mode="w", compression=ZIP_DEFLATED) as archive:
            for document_path in downloaded_paths:
                archive.write(document_path, arcname=document_path.name)

        return AppraisalPrepPackage(
            zip_path=zip_path,
            temp_dir=temp_dir,
            filename=zip_filename,
            file_count=len(downloaded_paths),
        )
    except AppraisalPrepError:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise AppraisalPrepError(f"Failed to create appraisal prep package: {exc}") from exc


def _safe_filename(value: str) -> str:
    filename = Path(value).name.strip()
    cleaned = "".join(
        character if character.isalnum() or character in (" ", "-", "_", ".") else "-"
        for character in filename
    ).strip(" .")
    return cleaned or "document.pdf"


def _safe_stem(value: str) -> str:
    filename = _safe_filename(value)
    stem = Path(filename).stem if "." in filename else filename
    return stem.strip(" .")


def _unique_filename(filename: str, used_names: set[str]) -> str:
    candidate = filename
    path = Path(filename)
    counter = 2
    while candidate.lower() in used_names:
        candidate = f"{path.stem}-{counter}{path.suffix}"
        counter += 1
    used_names.add(candidate.lower())
    return candidate
