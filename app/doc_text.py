from __future__ import annotations

import io
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Literal, List, Dict

from pypdf import PdfReader
from pdf2image import convert_from_bytes
from PIL import Image
import pytesseract
from docx import Document
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE


# ---------------- Dosya tespiti -----------------
def detect_file_type(filename: str, content_type: str | None) -> Literal["pdf", "docx", "pptx", "ppt", "unknown"]:
    """Dosya uzantısı ve MIME tipine göre belirleme."""
    name = (filename or "").lower()
    if name.endswith(".pdf") or content_type == "application/pdf":
        return "pdf"
    if name.endswith(".docx") or content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return "docx"
    if name.endswith(".pptx") or content_type == "application/vnd.openxmlformats-officedocument.presentationml.presentation":
        return "pptx"
    if name.endswith(".ppt"):
        return "ppt"
    return "unknown"


# ---------------- PDF -----------------
def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    texts: List[str] = []
    for page in reader.pages:
        texts.append(page.extract_text() or "")
    return "\n".join(texts)


def extract_text_via_ocr(pdf_bytes: bytes, max_pages: int | None = None) -> str:
    images = convert_from_bytes(pdf_bytes, first_page=1, last_page=max_pages)
    ocr_texts = []
    for image in images:
        ocr_texts.append(pytesseract.image_to_string(image))
    return "\n".join(ocr_texts)


def split_pdf_by_pages(pdf_bytes: bytes, max_chars: int) -> List[Dict[str, str]]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    chunks: List[Dict[str, str]] = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        text = normalize_text(text)
        for part in split_text_by_size(text, max_chars):
            chunks.append({"source": f"page:{i}", "text": part})
    return chunks


# ---------------- DOCX -----------------
def extract_text_from_docx_bytes(docx_bytes: bytes) -> List[Dict[str, str]]:
    doc = Document(io.BytesIO(docx_bytes))
    sections: List[Dict[str, str]] = []
    current_name = "section:1"
    current_text = []
    index = 1
    for para in doc.paragraphs:
        if para.style.name.startswith("Heading") and para.text.strip():
            if current_text:
                sections.append({"source": current_name, "text": "\n".join(current_text)})
                current_text = []
                index += 1
            current_name = f"section:{para.text.strip()}"
        else:
            current_text.append(para.text)
    if current_text:
        sections.append({"source": current_name, "text": "\n".join(current_text)})
    if not sections:
        sections.append({"source": "section:1", "text": ""})
    return sections


def extract_images_from_docx(docx_bytes: bytes) -> List[Image.Image]:
    doc = Document(io.BytesIO(docx_bytes))
    images: List[Image.Image] = []
    for rel in doc.part.rels.values():
        if "image" in rel.target_ref:
            img_bytes = rel.target_part.blob
            images.append(Image.open(io.BytesIO(img_bytes)))
    return images


# ---------------- PPTX -----------------
def extract_text_from_pptx_bytes(pptx_bytes: bytes) -> List[Dict[str, str]]:
    prs = Presentation(io.BytesIO(pptx_bytes))
    slides: List[Dict[str, str]] = []
    for i, slide in enumerate(prs.slides, start=1):
        texts: List[str] = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                texts.append(shape.text)
        if getattr(slide, "has_notes_slide", False) and slide.notes_slide:
            texts.append(slide.notes_slide.notes_text_frame.text)
        slides.append({"source": f"slide:{i}", "text": "\n".join(texts)})
    return slides


def extract_images_from_pptx(pptx_bytes: bytes) -> List[Dict[str, Image.Image]]:
    prs = Presentation(io.BytesIO(pptx_bytes))
    images: List[Dict[str, Image.Image]] = []
    for i, slide in enumerate(prs.slides, start=1):
        for shape in slide.shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                images.append({"slide": i, "image": Image.open(io.BytesIO(shape.image.blob))})
    return images


# ---------------- Legacy convert -----------------
def convert_legacy_office_to_modern(tmp_path: str) -> str:
    """LibreOffice ile eski ofis dosyasını modern formata çevirir."""
    outdir = os.path.dirname(tmp_path)
    cmd = ["libreoffice", "--headless", "--convert-to", "pdf", tmp_path, "--outdir", outdir]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode())
    base, _ = os.path.splitext(tmp_path)
    return base + ".pdf"


# ---------------- Ortak -----------------
def normalize_text(s: str) -> str:
    s = s.replace("\r", "\n")
    s = re.sub(r"[\t\v\f]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    s = "".join(ch for ch in s if ch.isprintable())
    return s.strip()


def split_text_by_size(s: str, max_chars: int) -> List[str]:
    return [s[i:i + max_chars] for i in range(0, len(s), max_chars) if s[i:i + max_chars]]


def word_count(s: str) -> int:
    return len(re.findall(r"\w+", s))


def char_count(s: str) -> int:
    return len(s)

