import os
import base64
import streamlit as st
from typing import Optional

from app.config import (
    PDF_FILENAME,
    ENABLE_PDF_ATTACHMENT,
    ENABLE_PDF_TEXT_FALLBACK,
)

# Single, central base64 of the default PDF (if present)
_encoded_file: str | None = None
if os.path.exists(PDF_FILENAME):
    try:
        with open(PDF_FILENAME, "rb") as f:
            _encoded_file = base64.b64encode(f.read()).decode("utf-8")
    except Exception:
        _encoded_file = None


def get_default_pdf_b64() -> str:
    return _encoded_file or ""


def upload_pdf_and_get_file_id(client, pdf_path: str) -> Optional[str]:
    try:
        if not (ENABLE_PDF_ATTACHMENT and os.path.exists(pdf_path)):
            return None
        file_obj = client.files.create(file=open(pdf_path, "rb"), purpose="user_data")
        return getattr(file_obj, "id", None)
    except Exception as e:
        st.info(f"PDF upload skipped: {e}")
        return None


def extract_pdf_text_fallback(pdf_path: str, max_chars: int = 12000) -> str:
    if not (ENABLE_PDF_TEXT_FALLBACK and os.path.exists(pdf_path)):
        return ""
    try:
        import PyPDF2
        text = []
        with open(pdf_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                try:
                    text.append(page.extract_text() or "")
                except Exception:
                    continue
        joined = "\n".join(text).strip()
        if len(joined) > max_chars:
            joined = joined[:max_chars]
        return joined
    except Exception:
        return ""


def get_pdf_b64_from_bytes(pdf_bytes: bytes | None) -> str:
    import base64
    return base64.b64encode(pdf_bytes).decode("utf-8") if pdf_bytes else ""