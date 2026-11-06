"""Render approved lease DOCX and verify the exact PDF sent for signature."""
from __future__ import annotations

from collections import Counter
from io import BytesIO
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from typing import Any

import pdfplumber
from docxtpl import DocxTemplate

from app.services.minio_financing import get_financing_document, upload_financing_document

TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "leases" / "residential_tenancy_agreement_v1.docx"


def expected_anchors(tenant_count: int) -> Counter[str]:
    anchors = Counter({"\\ll_sig\\": 2, "\\ll_date\\": 2})
    for i in range(1, tenant_count + 1):
        anchors[f"\\t{i}_sig\\"] = 3
        anchors[f"\\t{i}_date\\"] = 3
        for suffix in ("phone", "email", "pref"):
            anchors[f"\\t{i}_{suffix}\\"] = 1
    for prefix, rows, cols in (("oc", 4, 5), ("ec", 2, 4), ("vh", 2, 4), ("pt", 2, 4)):
        for row in range(1, rows + 1):
            for col in range(1, cols + 1):
                anchors[f"\\{prefix}_r{row}_c{col}\\"] = 1
    return anchors


def check_pdf(pdf: bytes, tenant_count: int) -> None:
    with pdfplumber.open(BytesIO(pdf)) as document:
        text = "\n".join(page.extract_text(x_tolerance=1, y_tolerance=1) or "" for page in document.pages)
    if any(token in text for token in ("{{", "}}", "{%")):
        raise ValueError("Unrendered template tag in lease PDF")
    mismatched = {anchor: {"expected": count, "actual": text.count(anchor)}
                  for anchor, count in expected_anchors(tenant_count).items() if text.count(anchor) != count}
    if mismatched:
        raise ValueError(f"Lease PDF DocuSign anchor counts differ: {mismatched}")


def require_fonts() -> None:
    if not shutil.which("fc-match"):
        raise RuntimeError("Fontconfig is required to verify lease fonts")
    for family in ("Liberation Serif", "FreeSerif"):
        matched = subprocess.run(
            ["fc-match", "-f", "%{family}", family], capture_output=True, text=True, check=True,
        ).stdout.split(",", 1)[0].strip()
        if matched != family:
            raise RuntimeError(f"{family} is required for the approved lease layout")


def render(lease_id: str, context: dict[str, Any]) -> tuple[str, str]:
    if not TEMPLATE.is_file():
        raise RuntimeError(f"Approved lease template is missing: {TEMPLATE}")
    if not shutil.which("soffice"):
        raise RuntimeError("LibreOffice Writer is required to render lease PDFs")
    require_fonts()
    with TemporaryDirectory(prefix="lease-") as tmp:
        directory = Path(tmp)
        docx = directory / "draft.docx"
        template = DocxTemplate(TEMPLATE)
        template.render(context, autoescape=True)
        template.save(docx)
        result = subprocess.run(
            ["soffice", "-env:UserInstallation=" + (directory / "lo-profile").as_uri(),
             "--headless", "--convert-to", "pdf", "--outdir", str(directory), str(docx)],
            capture_output=True, text=True, timeout=90, check=False,
        )
        pdf_path = directory / "draft.pdf"
        if result.returncode or not pdf_path.is_file():
            raise RuntimeError(f"LibreOffice lease conversion failed: {result.stderr or result.stdout}")
        pdf = pdf_path.read_bytes()
        check_pdf(pdf, len(context["tenants"]))
        docx_key, pdf_key = f"leases/{lease_id}/draft.docx", f"leases/{lease_id}/draft.pdf"
        upload_financing_document(key=docx_key, content=docx.read_bytes(), content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        upload_financing_document(key=pdf_key, content=pdf, content_type="application/pdf")
        return docx_key, pdf_key


def draft_pdf(key: str) -> bytes:
    return get_financing_document(key=key)
