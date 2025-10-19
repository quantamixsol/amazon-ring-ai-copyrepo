import os
from io import BytesIO
import streamlit as st

from app.config import (
    DEFAULT_PROVIDER,
    OPENAI_DEFAULT_MODEL,
    PERPLEXITY_DEFAULT_MODEL,
    AMAZON_CLAUDE_DEFAULT_MODEL,
    DEFAULT_EXCEL_PATH,
)
from app.io.excel import load_excel_sheets


def init_session_state():
    ss = st.session_state
    ss.setdefault("initialized", False)
    ss.setdefault("file_loaded", False)
    ss.setdefault("preview_visible", False)
    ss.setdefault("xls", None)
    ss.setdefault("first_df", None)
    ss.setdefault("first_sheet_name", None)
    ss.setdefault("uploaded_bytes", None)
    ss.setdefault("uploaded_name", None)
    ss.setdefault("selected_variant", "ring")
    ss.setdefault("use_specific_pui", False)

    # provider/model
    ss.setdefault("provider", DEFAULT_PROVIDER)
    ss.setdefault("model_openai", OPENAI_DEFAULT_MODEL)
    ss.setdefault("model_perplexity", PERPLEXITY_DEFAULT_MODEL)
    ss.setdefault("model_amazon_claude", AMAZON_CLAUDE_DEFAULT_MODEL)

    # PDF source + uploaded bytes
    ss.setdefault("pdf_source", "Default guidelines PDF")
    ss.setdefault("uploaded_pdf_bytes", None)
    ss.setdefault("uploaded_pdf_name", None)

    # feedback
    ss.setdefault("feedback_text", "")

    # last-run
    ss.setdefault("last_results", None)
    ss.setdefault("last_variant", None)
    ss.setdefault("last_prompt", None)
    ss.setdefault("last_expected_fields", None)
    ss.setdefault("last_pdf_file_id", None)
    ss.setdefault("last_pdf_excerpt", "")

    ss.setdefault("ctx_ring_base", "")
    ss.setdefault("ctx_ring_extra", "")
    ss.setdefault("ctx_ring_guard", "")
    ss.setdefault("ctx_social_base", "")
    ss.setdefault("ctx_social_extra", "")
    ss.setdefault("ctx_social_guard", "")
    ss.setdefault("ctx_email_base", "")
    ss.setdefault("ctx_email_extra", "")
    ss.setdefault("ctx_email_guard", "")
    ss.setdefault("ctx_audience_base", "")
    ss.setdefault("ctx_audience_extra", "")
    ss.setdefault("ctx_audience_guard", "")

    # Auto-load default Excel once
    if not ss.initialized:
        try:
            if ss.uploaded_bytes:
                ss.xls = load_excel_sheets(BytesIO(ss.uploaded_bytes), ss.uploaded_name or "uploaded.xlsx")
                ss.first_sheet_name = list(ss.xls.keys())[0]
                ss.first_df = ss.xls[ss.first_sheet_name]
                ss.file_loaded = True
            elif os.path.exists(DEFAULT_EXCEL_PATH):
                with open(DEFAULT_EXCEL_PATH, "rb") as f:
                    data = f.read()
                ss.xls = load_excel_sheets(BytesIO(data), os.path.basename(DEFAULT_EXCEL_PATH))
                ss.first_sheet_name = list(ss.xls.keys())[0]
                ss.first_df = ss.xls[ss.first_sheet_name]
                ss.file_loaded = True
        except Exception as e:
            st.info(f"Could not auto-load default Excel. Upload from the sidebar. ({e})")
        finally:
            ss.initialized = True