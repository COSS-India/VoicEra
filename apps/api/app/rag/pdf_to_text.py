"""Extract plain text from text-based PDFs."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


def extract_text_from_pdf(pdf_path: str | Path) -> str:
    """Read a text-based PDF from disk; return all page text joined with blank lines."""
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(f"Not a file: {path}")

    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        raw = page.extract_text()
        if raw:
            parts.append(raw.strip())

    return "\n\n".join(parts).strip()
