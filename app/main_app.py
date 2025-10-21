# main_app.py — Tabs layout: "Setup" (all config) + "Generate Copy" (creative flow)
# Unified config control, Excel/PDF fallbacks, filenames shown, Excel preview,
# Advanced settings in Setup tab, generation & feedback in "Generate Copy" tab.

import os
from io import BytesIO
import streamlit as st

import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(__file__, "..", "..")))

from app.config import (
    PDF_CONTEXT_CHARS_DEFAULT,
    NUM_VARIATIONS,
    PDF_FILENAME,
    DEFAULT_EXCEL_PATH,
)
from app.state import init_session_state
from app.ui.layout import setup_page, footer_disclaimer
from app.ui.renderers import render_results
from app.utils.notify import notify, do_rerun
from app.io.excel import (
    load_excel_sheets,
    try_autodetect_long_text,
    row_to_content_data,
    workbook_excerpt_for_llm,
)
from app.io.pdf import upload_pdf_and_get_file_id, extract_pdf_text_fallback
from app.prompts.variants import DEFAULT_CONTEXT
from app.prompts.builder import build_system_prompt_text_variant
from app.services.generation import get_enhanced_response
from app.providers.openai_provider import get_openai_client
from app.schemas import VARIANT_FIELDS, VARIANT_MODELS

# ---------- Boot ----------
setup_page()
init_session_state()
ss = st.session_state

# ---------- Helpers ----------
def _load_excel_from_bytes(data: bytes, name: str) -> bool:
    """Load excel into session; return True on success."""
    try:
        ss.xls = load_excel_sheets(BytesIO(data), name)
        ss.first_sheet_name = list(ss.xls.keys())[0]
        ss.first_df = ss.xls[ss.first_sheet_name]
        ss.file_loaded = True
        return True
    except Exception as e:
        st.error(f"Failed to load Excel: {e}")
        ss.file_loaded = False
        return False

def _try_load_default_excel(mark_name=True) -> bool:
    """Load DEFAULT_EXCEL_PATH if present. Returns True if loaded."""
    if not os.path.exists(DEFAULT_EXCEL_PATH):
        return False
    try:
        with open(DEFAULT_EXCEL_PATH, "rb") as f:
            data = f.read()
        ok = _load_excel_from_bytes(data, os.path.basename(DEFAULT_EXCEL_PATH))
        if ok and mark_name:
            ss.uploaded_name = os.path.basename(DEFAULT_EXCEL_PATH)
        return ok
    except Exception as e:
        st.error(f"Could not auto-load default Excel. ({e})")
        return False

def _label(name: str | None, source: str | None) -> str:
    if not name:
        return "—"
    suffix = " (uploaded)" if source == "uploaded" else (" (default)" if source == "default" else "")
    return f"{name}{suffix}"


# =============================== Tabs ===============================
tab_setup, tab_generate = st.tabs(["🧩 Setup", "✍️ Generate Copy"])

# =============================== Setup Tab ===============================
with tab_setup:
    st.markdown("## ⚙️ Configuration")

    config_mode = st.selectbox(
        "Setup Mode",
        ["Use default Ring assets (Excel + PDF)", "Upload custom Excel & Guidelines PDF"],
        help="Choose whether to use the default Ring workbook and guidelines or upload your own versions.",
    )

    use_custom_assets = config_mode == "Upload custom Excel & Guidelines PDF"

    # Track effective sources
    excel_source = None   # "uploaded" | "default" | None
    pdf_source = None     # "uploaded" | "default" | None
    attached_excel_name = None
    attached_pdf_name = None

    if use_custom_assets:
        st.markdown("### 📁 Upload your assets")

        # Excel (optional — fallback to default if missing)
        uploaded_excel = st.file_uploader("Upload Excel (.xlsx)", type=["xlsx"], key="excel_u")
        if uploaded_excel is not None:
            ss.uploaded_bytes = uploaded_excel.getvalue()
            ss.uploaded_name = uploaded_excel.name
            if _load_excel_from_bytes(ss.uploaded_bytes, ss.uploaded_name or "uploaded.xlsx"):
                excel_source = "uploaded"
                attached_excel_name = uploaded_excel.name
                notify(f"Loaded Excel: {uploaded_excel.name}", icon="✅")

        # PDF (optional — fallback to default if missing)
        uploaded_pdf = st.file_uploader("Upload guidelines PDF", type=["pdf"], key="pdf_u")
        if uploaded_pdf is not None:
            ss.uploaded_pdf_bytes = uploaded_pdf.getvalue()
            ss.uploaded_pdf_name = uploaded_pdf.name
            pdf_source = "uploaded"
            attached_pdf_name = uploaded_pdf.name

        # Excel fallback
        if excel_source is None:
            if not ss.get("file_loaded"):
                if _try_load_default_excel(mark_name=True):
                    excel_source = "default"
                    attached_excel_name = os.path.basename(DEFAULT_EXCEL_PATH)
                    st.caption(f"Using default Excel: {attached_excel_name}")
                else:
                    st.warning("Excel not uploaded and default Excel not found.")
            else:
                excel_source = "uploaded" if ss.get("uploaded_bytes") else "default"
                attached_excel_name = ss.get("uploaded_name") or os.path.basename(DEFAULT_EXCEL_PATH)

        # PDF fallback
        if pdf_source is None:
            if os.path.exists(PDF_FILENAME):
                pdf_source = "default"
                attached_pdf_name = os.path.basename(PDF_FILENAME)
                st.caption(f"Using default Guidelines PDF: {attached_pdf_name}")
            else:
                st.warning("Guidelines PDF not uploaded and default PDF not found.")

    else:
        # Defaults mode
        st.markdown("### 📦 Using default Ring assets")
        if not ss.get("file_loaded", False):
            if _try_load_default_excel(mark_name=True):
                excel_source = "default"
                attached_excel_name = os.path.basename(DEFAULT_EXCEL_PATH)
            else:
                st.warning("Default Excel not found. Switch to upload mode to provide a workbook.")
        else:
            excel_source = "uploaded" if ss.get("uploaded_bytes") else "default"
            attached_excel_name = ss.get("uploaded_name") or os.path.basename(DEFAULT_EXCEL_PATH)

        if os.path.exists(PDF_FILENAME):
            pdf_source = "default"
            attached_pdf_name = os.path.basename(PDF_FILENAME)
        else:
            st.warning("Default PDF not found. Switch to upload mode to provide guidelines.")

    # Excel status + slim preview
    if ss.get("file_loaded") and ss.get("first_df") is not None:
        st.success(f"Detected sheet: {ss.first_sheet_name} · rows: {len(ss.first_df)}")
        with st.expander("View details", expanded=False):
            st.dataframe(ss.first_df.head(10), use_container_width=True)

    # Attached filenames
    st.markdown("#### 📎 Attached files")
    st.write(f"- **Excel**: {_label(attached_excel_name, excel_source)}")
    st.write(f"- **Guidelines PDF**: {_label(attached_pdf_name, pdf_source)}")

    # -------- Advanced settings in Setup --------
    st.markdown("## 🧩 Advanced settings")
    with st.expander("Open advanced settings", expanded=False):
        provider_options = ["OpenAI", "Amazon Claude", "Perplexity"]
        default_idx = provider_options.index(ss.provider) if ss.get("provider") in provider_options else 0
        ss.provider = st.selectbox(
            "Provider",
            provider_options,
            index=default_idx,
            help="Default is OpenAI (recommended).",
        )

        if ss.provider == "OpenAI":
            st.text("Model Using : gpt-5")
        elif ss.provider == "Amazon Claude":
            st.text("Model Using : Claude Sonnet 4")
        else:
            st.text("Model Using : sonar-pro")

        st.markdown("---")

        ss.use_specific_pui = st.checkbox(
            "Target a specific Product Unique Identifier",
            value=ss.use_specific_pui,
            help="Enable to specify a column and value; otherwise the LLM sees a compact excerpt of the entire workbook.",
        )

        if ss.use_specific_pui:
            st.markdown("#### 🔎 Select Product Unique Identifier")
            if ss.get("first_df") is not None and not ss.first_df.empty:
                cols_list = [str(c) for c in ss.first_df.columns]
                st.selectbox("Column", cols_list, key="id_col", disabled=not ss.file_loaded)

                selected_col = st.session_state.get("id_col")
                if ss.file_loaded and selected_col:
                    id_vals = (
                        ss.first_df[selected_col]
                        .astype(str)
                        .apply(lambda s: s.strip())
                        .replace("", None)
                        .dropna()
                        .unique()
                        .tolist()
                    )
                    st.selectbox(
                        "Value",
                        sorted(id_vals, key=lambda x: (x.lower(), x)) if id_vals else [],
                        key="id_val",
                        disabled=not ss.file_loaded,
                    )
                else:
                    st.caption("Upload or load a file to enable the selectors.")
            else:
                st.selectbox("Column", [], key="id_col", disabled=True)
                st.selectbox("Value", [], key="id_val", disabled=True)
                st.caption("No data loaded yet.")

    st.info("Done with setup? Switch to the **✍️ Generate Copy** tab to create content.")

# =============================== Generate Tab ===============================
with tab_generate:
    st.markdown("## 🧭 Choose copy type")

    label_map = {
        "ring": "Ring Copywriter",
        "social": "Social Media",
        "email": "Email Campaign",
        "audience": "Audience Adaptation",
    }

    c1, c2, c3, c4 = st.columns(4)

    def prompt_button(label: str, key_mode: str, container):
        with container:
            is_selected = (ss.selected_variant == key_mode)
            clicked = st.button(
                label,
                key=f"btn_{key_mode}",
                type=("primary" if is_selected else "secondary"),
                use_container_width=True,
            )
            if clicked:
                ss[f"ctx_{key_mode}_base"] = DEFAULT_CONTEXT[key_mode]["base_prompt"]
                ss[f"ctx_{key_mode}_extra"] = DEFAULT_CONTEXT[key_mode]["additional_context"]
                ss[f"ctx_{key_mode}_guard"] = DEFAULT_CONTEXT[key_mode]["guardrails"]
                ss.selected_variant = key_mode
                do_rerun()

    prompt_button("Ring Copywriter", "ring", c1)
    prompt_button("Social Media", "social", c2)
    prompt_button("Email Campaign", "email", c3)
    prompt_button("Audience Adaptation", "audience", c4)
    st.caption(f"Selected: **{label_map.get(ss.selected_variant, 'None')}**")

    st.markdown("## ✍️ Authoring context")
    active_mode = ss.selected_variant or "ring"
    base_key = f"ctx_{active_mode}_base"
    extra_key = f"ctx_{active_mode}_extra"
    guard_key = f"ctx_{active_mode}_guard"

    st.text_area("Base Prompt", key=base_key, height=110)
    st.text_area("Additional Context", key=extra_key, height=110)
    st.text_area("Guardrails", key=guard_key, height=110)

    go = st.button("🚀 Generate variations", use_container_width=True)

    def run_generation(user_feedback: str = ""):
        # Pre-flight: ensure setup is complete
        if not (ss.get("file_loaded") and ss.get("first_df") is not None and ss.get("xls") is not None):
            st.error("Please complete the **Setup** tab: Excel must be available (uploaded or default).")
            return
        if not ss.selected_variant:
            st.error("Please choose a copy type above before generating.")
            return

        provider = ss.provider
        # Resolve model name string (kept identical to original logic)
        model = ss.model_amazon_claude
        if provider == "OpenAI":
            model = ss.model_openai
        elif provider == "Perplexity":
            model = ss.model_perplexity

        # API clients / keys
        if provider == "OpenAI":
            api_key = os.getenv("OPENAI_API_KEY", "")
            if not api_key:
                st.error("Missing OPENAI_API_KEY.")
                return
            client = get_openai_client(api_key)
        else:
            if provider == "Perplexity" and not os.getenv("PERPLEXITY_API_KEY", ""):
                st.error("Missing PERPLEXITY_API_KEY.")
                return
            client = None

        # Authoring context
        base_prompt = ss.get(base_key, DEFAULT_CONTEXT[active_mode]["base_prompt"])
        additional_context = ss.get(extra_key, DEFAULT_CONTEXT[active_mode]["additional_context"])
        guardrails = ss.get(guard_key, DEFAULT_CONTEXT[active_mode]["guardrails"])

        auto_guidelines, auto_template = try_autodetect_long_text(ss.xls)

        # Robust PDF selection: uploaded if available else default
        pdf_bytes = None
        chosen_pdf_path = None
        pdf_name = None

        if ss.get("uploaded_pdf_bytes"):
            safe_name = os.path.basename(ss.get("uploaded_pdf_name") or "uploaded_guidelines.pdf")
            chosen_pdf_path = safe_name
            pdf_name = safe_name
            try:
                with open(chosen_pdf_path, "wb") as wf:
                    wf.write(ss.uploaded_pdf_bytes)
            except Exception as e:
                st.error(f"Failed saving uploaded PDF: {e}")
                return
            pdf_bytes = ss.uploaded_pdf_bytes
        else:
            if not os.path.exists(PDF_FILENAME):
                st.error(f"Default PDF not found: {PDF_FILENAME}")
                return
            chosen_pdf_path = PDF_FILENAME
            pdf_name = os.path.basename(PDF_FILENAME)
            with open(PDF_FILENAME, "rb") as f:
                pdf_bytes = f.read()

        # OpenAI-only PDF attach/fallback
        pdf_file_id = None
        pdf_excerpt = ""
        if provider == "OpenAI":
            if chosen_pdf_path:
                pdf_file_id = upload_pdf_and_get_file_id(client, chosen_pdf_path)
            if not pdf_file_id and chosen_pdf_path:
                pdf_excerpt = extract_pdf_text_fallback(chosen_pdf_path, max_chars=8000)

        # Content data (either specific row or compact excerpt)
        if ss.use_specific_pui:
            selected_col = st.session_state.get("id_col")
            selected_val = st.session_state.get("id_val")
            if not selected_col or not selected_val:
                st.error("Advanced targeting is enabled. Please select both a Product Unique Identifier column and value.")
                return
            mask = ss.first_df[selected_col].astype(str).str.strip() == str(selected_val).strip()
            if not mask.any():
                st.error("No matching row found for the selected Product Unique Identifier.")
                return
            row = ss.first_df[mask].iloc[0]
            content_data = row_to_content_data(row)
        else:
            content_data = workbook_excerpt_for_llm(ss.xls, rows_per_sheet=50, char_limit=PDF_CONTEXT_CHARS_DEFAULT)

        system_prompt = build_system_prompt_text_variant(
            variant=ss.selected_variant,
            ring_brand_guidelines=auto_guidelines,
            approved_copy_template=auto_template,
            content_data=content_data,
            base_prompt=base_prompt,
            additional_context=additional_context,
            guardrails=guardrails,
            PDF_CONTEXT_CHARS=PDF_CONTEXT_CHARS_DEFAULT,
            user_feedback=user_feedback.strip(),
            pdf_text_excerpt=(pdf_excerpt if provider == "OpenAI" else ""),
        )

        with st.spinner(f"Generating with {provider}"):
            results = get_enhanced_response(
                provider=provider,
                openai_client=client,
                prompt=system_prompt,
                expected_fields=VARIANT_FIELDS[ss.selected_variant],
                model=model,
                n=NUM_VARIATIONS,
                pdf_file_id=(pdf_file_id if provider == "OpenAI" else None),
                pdf_bytes=pdf_bytes,
                pdf_name=pdf_name,
                pydantic_model=VARIANT_MODELS[ss.selected_variant],
            )

        st.success(f"{label_map[ss.selected_variant]}: Generated {len(results)} variation(s) via {provider}")
        ss.last_results = results
        ss.last_variant = ss.selected_variant
        ss.last_prompt = system_prompt
        ss.last_expected_fields = VARIANT_FIELDS[ss.selected_variant]
        ss.last_pdf_file_id = (pdf_file_id if provider == "OpenAI" else None)
        ss.last_pdf_excerpt = (pdf_excerpt if provider == "OpenAI" else "")

        render_results(label_map[ss.selected_variant], ss.selected_variant, results, ss.last_expected_fields)

    if go:
        run_generation("")

    # ---------- Feedback & Regenerate ----------
    if ss.get("last_results") is not None:
        st.markdown("## 🗣️ Feedback")
        st.caption(
            "Provide specific, text-only feedback (tone, length, messaging priorities, compliance notes, "
            "headlines constraints, etc.). Then click **Regenerate with feedback**."
        )
        ss.feedback_text = st.text_area(
            "Feedback for the next run",
            value=ss.feedback_text,
            height=120,
            placeholder="Example: Shorter body, emphasise privacy, headlines under 6 words, no exclamation marks.",
        )

        if st.button("Regenerate with feedback", use_container_width=True):
            fb = (ss.feedback_text or "").strip()
            run_generation(user_feedback=fb)

# ---------- Footer ----------
footer_disclaimer()
