from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import pdfplumber
import pytesseract
from PIL import ImageEnhance
from PIL import ImageFilter
from PIL import ImageOps
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
            pages = [
                self._extract_best_page(page_number=index + 1, page=page)
                for index, page in enumerate(pdf.pages)
            ]

        return ExtractionResult(
            pages=pages,
            total_pages=len(pages),
            overall_confidence=self._calculate_overall_confidence(pages),
            method_used=self._determine_method(pages),
            raw_text="\n\n".join(
                f"--- PAGE {page.page_number} ({page.method}) ---\n{page.text}"
                for page in pages
                if page.text.strip()
            ),
        )

    def _extract_best_page(
        self,
        page_number: int,
        page: pdfplumber.page.Page,
    ) -> PageResult:
        plumber_result = self._extract_page_pdfplumber(page_number=page_number, page=page)
        if self._should_use_tesseract(plumber_result):
            tesseract_result = self._extract_page_tesseract(page_number=page_number, page=page)
            if tesseract_result.text.strip():
                return tesseract_result
        return plumber_result

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
        source_image = self._render_page_image(page)
        image = self._prepare_ocr_image(source_image)
        ocr_config = "--psm 4 -c preserve_interword_spaces=1"
        data = pytesseract.image_to_data(
            image,
            output_type=pytesseract.Output.DICT,
            config=ocr_config,
        )
        text = pytesseract.image_to_string(
            image,
            config=ocr_config,
        ).replace("\x0c", "").strip()
        schedule_rows = self._extract_land_schedule_rows(source_image)
        if schedule_rows:
            text = (
                f"{text}\n\n"
                "LOT SCHEDULE ROWS (normalized OCR)\n"
                f"{schedule_rows}"
            ).strip()

        confidence_values: list[float] = []
        confidences = data.get("conf", [])

        for confidence in confidences:
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
            text=text,
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

    def _should_use_tesseract(self, plumber_result: PageResult) -> bool:
        return plumber_result.confidence < 0.5 or not plumber_result.text.strip()

    def _render_page_image(self, page: pdfplumber.page.Page) -> Image:
        return page.to_image(resolution=400).original

    def _prepare_ocr_image(self, image: Image) -> Image:
        grayscale = ImageOps.grayscale(image)
        boosted = ImageEnhance.Contrast(grayscale).enhance(2.5)
        return boosted.filter(ImageFilter.SHARPEN)

    def _extract_land_schedule_rows(self, image: Image) -> str:
        if image.width <= image.height:
            return ""

        crop = image.crop(
            (
                0,
                int(image.height * 0.24),
                int(image.width * 0.38),
                int(image.height * 0.48),
            )
        )
        processed_crop = self._prepare_ocr_image(crop)
        crop_width, crop_height = processed_crop.size
        column_ratios = [0.072, 0.357, 0.492, 0.693, 0.779, 0.997]
        row_ratios = [0.211, 0.268, 0.329, 0.388, 0.448, 0.506, 0.567]
        columns = [int(crop_width * ratio) for ratio in column_ratios]
        rows = [int(crop_height * ratio) for ratio in row_ratios]

        lines: list[str] = []
        for row_index in range(len(rows) - 1):
            y1 = rows[row_index] + 2
            y2 = rows[row_index + 1] - 2
            if y2 <= y1:
                continue

            values = [
                self._ocr_cell(processed_crop.crop((columns[col_index] + 2, y1, columns[col_index + 1] - 2, y2)))
                for col_index in range(len(columns) - 1)
            ]
            block = self._extract_digits(values[0])
            lot_number = self._extract_digits(values[1])
            plan = self._extract_digits(values[2])
            street_number = self._extract_digits(values[3])
            street_name = self._normalize_street_name(values[4])

            present_fields = [block, lot_number, plan, street_number, street_name]
            if sum(1 for value in present_fields if value) < 3:
                continue

            civic_address = None
            if street_number and street_name:
                civic_address = f"{street_number} {street_name}"
            elif street_name:
                civic_address = street_name

            parts = [
                f"row {len(lines) + 1}",
                f"block: {block or 'null'}",
                f"lot_number: {lot_number or 'null'}",
                f"plan: {plan or 'null'}",
                f"street_number: {street_number or 'null'}",
                f"street_name: {street_name or 'null'}",
                f"civic_address: {civic_address or 'null'}",
            ]
            lines.append(" | ".join(parts))

        return "\n".join(lines)

    def _ocr_cell(self, image: Image) -> str:
        text = pytesseract.image_to_string(
            image,
            config="--psm 7 -c preserve_interword_spaces=1",
        )
        return self._clean_cell_text(text)

    def _clean_cell_text(self, text: str) -> str:
        cleaned = text.replace("\x0c", " ").replace("|", " ")
        cleaned = re.sub(r"[_`~]+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _extract_digits(self, text: str) -> str | None:
        matches = re.findall(r"\d+", text)
        if not matches:
            return None
        return matches[-1]

    def _normalize_street_name(self, text: str) -> str | None:
        cleaned = re.sub(r"[^A-Za-z ]+", " ", text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            return None
        words = [word.capitalize() for word in cleaned.split()]
        return " ".join(words)

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
