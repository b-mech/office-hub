from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pdfplumber
import pytesseract
from PIL.Image import Image


@dataclass(slots=True)
class PageResult:
    page_number: int
    text: str
    confidence: float
    method: str


@dataclass(slots=True)
class ExtractionResult:
    pages: list[PageResult]
    total_pages: int
    overall_confidence: float
    method_used: str
    raw_text: str


class PDFExtractor:
    def extract(self, pdf_path: str | Path) -> ExtractionResult:
        path = Path(pdf_path)

        with pdfplumber.open(path) as pdf:
            plumber_pages = [
                self._extract_page_pdfplumber(page_number=index + 1, page=page)
                for index, page in enumerate(pdf.pages)
            ]

        overall_confidence = self._calculate_overall_confidence(plumber_pages)
        if overall_confidence < 0.5:
            with pdfplumber.open(path) as pdf:
                pages = [
                    self._extract_page_tesseract(page_number=index + 1, page=page)
                    for index, page in enumerate(pdf.pages)
                ]
        else:
            pages = plumber_pages

        return ExtractionResult(
            pages=pages,
            total_pages=len(pages),
            overall_confidence=self._calculate_overall_confidence(pages),
            method_used=self._determine_method(pages),
            raw_text="\n".join(page.text for page in pages),
        )

    def _extract_page_pdfplumber(
        self,
        page_number: int,
        page: pdfplumber.page.Page,
    ) -> PageResult:
        text_parts: list[str] = []

        page_text = page.extract_text() or ""
        if page_text.strip():
            text_parts.append(page_text.strip())

        table_text = self._extract_table_text(page.extract_tables() or [])
        if table_text:
            text_parts.append(table_text)

        text = "\n".join(text_parts).strip()
        text_length = len(text)
        if text_length > 100:
            confidence = 1.0
        elif text_length >= 20:
            confidence = 0.5
        else:
            confidence = 0.1

        return PageResult(
            page_number=page_number,
            text=text,
            confidence=confidence,
            method="pdfplumber",
        )

    def _extract_page_tesseract(
        self,
        page_number: int,
        page: pdfplumber.page.Page,
    ) -> PageResult:
        image: Image = page.to_image(resolution=300).original
        data = pytesseract.image_to_data(
            image,
            output_type=pytesseract.Output.DICT,
        )

        words: list[str] = []
        confidence_values: list[float] = []
        texts = data.get("text", [])
        confidences = data.get("conf", [])

        for word, confidence in zip(texts, confidences, strict=False):
            cleaned_word = word.strip()
            if cleaned_word:
                words.append(cleaned_word)

            try:
                confidence_value = float(confidence)
            except (TypeError, ValueError):
                continue

            if confidence_value >= 0:
                confidence_values.append(confidence_value)

        average_confidence = (
            sum(confidence_values) / len(confidence_values)
            if confidence_values
            else 0.0
        )

        return PageResult(
            page_number=page_number,
            text=" ".join(words),
            confidence=average_confidence / 100.0,
            method="tesseract",
        )

    def _calculate_overall_confidence(self, pages: list[PageResult]) -> float:
        if not pages:
            return 0.0

        return sum(page.confidence for page in pages) / len(pages)

    def _determine_method(self, pages: list[PageResult]) -> str:
        methods = {page.method for page in pages}
        if methods == {"pdfplumber"}:
            return "pdfplumber"
        if methods == {"tesseract"}:
            return "tesseract"
        return "mixed"

    def _extract_table_text(self, tables: list[list[list[str | None]]]) -> str:
        rendered_tables: list[str] = []
        for table in tables:
            rows: list[str] = []
            for row in table:
                if not row:
                    continue
                rendered_row = " | ".join((cell or "").strip() for cell in row)
                if rendered_row.strip(" |"):
                    rows.append(rendered_row)
            if rows:
                rendered_tables.append("\n".join(rows))

        return "\n\n".join(rendered_tables)


if __name__ == "__main__":
    print("Usage example:")
    print("from app.services.ocr import PDFExtractor")
    print("result = PDFExtractor().extract('path/to/document.pdf')")
    print("print(result.raw_text)")
