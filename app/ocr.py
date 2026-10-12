"""OCR: text from images and PDFs. Tesseract is OPTIONAL — without it, PDFs with a text layer still work
and images/scanned pages are marked 'failed' with a message saying how to install it.

Windows: install Tesseract from https://github.com/UB-Mannheim/tesseract/wiki and tick "Arabic" under
Additional language data. No other system software is needed (PDF pages are rendered with pypdfium2).
"""
import os
import shutil
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageOps
from pypdf import PdfReader

WANTED_LANGS = ("ara", "eng")
IMAGE_TYPES = {"image/png", "image/jpeg", "image/tiff", "image/bmp", "image/webp"}
MIN_TEXT_LAYER = 30
WIN_PATHS = [r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
             os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe")]
HOWTO = ("Tesseract OCR is not installed. Install it from https://github.com/UB-Mannheim/tesseract/wiki "
         "(tick Arabic under 'Additional language data'), then press 'Re-run OCR'.")


@lru_cache(maxsize=1)
def tesseract():
    """Returns (pytesseract module, 'ara+eng') or raises RuntimeError with install instructions."""
    import pytesseract
    exe = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract") or next((p for p in WIN_PATHS if os.path.exists(p)), None)
    if not exe:
        raise RuntimeError(HOWTO)
    pytesseract.pytesseract.tesseract_cmd = exe
    have = set(pytesseract.get_languages(config=""))
    use = [l for l in WANTED_LANGS if l in have]
    if not use:
        raise RuntimeError(f"Tesseract has none of {WANTED_LANGS}; installed: {sorted(have)}")
    return pytesseract, "+".join(use)


def _ocr_image(img: Image.Image) -> tuple[str, str]:
    pt, langs = tesseract()
    img = ImageOps.autocontrast(ImageOps.exif_transpose(img).convert("L"))
    return pt.image_to_string(img, lang=langs, config="--psm 6"), langs


def extract_text(path: Path, mime: str):
    """Returns (text, status, langs). Raises RuntimeError/Exception on failure."""
    if mime == "application/dicom":
        return None, "not_applicable", None
    if mime == "application/pdf":
        import pypdfium2 as pdfium
        reader, parts, langs = PdfReader(str(path)), [], None
        pdf = None
        for i, page in enumerate(reader.pages):
            text = (page.extract_text() or "").strip()
            if len(text) < MIN_TEXT_LAYER:                       # scanned page -> render + OCR
                pdf = pdf or pdfium.PdfDocument(str(path))
                text, langs = _ocr_image(pdf[i].render(scale=250 / 72).to_pil())
                text = text.strip()
            parts.append(text)
        return "\n\n".join(parts).strip(), "done", langs
    if mime in IMAGE_TYPES:
        with Image.open(path) as img:
            text, langs = _ocr_image(img)
        return text.strip(), "done", langs
    return None, "not_applicable", None
