import os
from io import BytesIO
import streamlit as st

from app.config import (
    PDF_CONTEXT_CHARS_DEFAULT,
    NUM_VARIATIONS,
    PDF_FILENAME,
)
from app.state import init_session_state
from app.ui.layout import setup_page, footer_disclaimer
from app.ui.renderers import render_preview, render_results
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

# ---------- Sidebar ----------
with st.sidebar:
    st.header("📁 Source & Controls")

    provider_options = ["Amazon Claude", "OpenAI", "Perplexity"]
    default_idx = provider_options.index(ss.provider) if ss.get("provider") in provider_options else 1
    ss.provider = st.selectbox("Provider", provider_options, index=default_idx)

    if ss.provider == "OpenAI":
        st.text("Model Using : gpt-5")
    elif ss.provider == "Amazon Claude":
        st.text("Model Using : Claude Sonnet 4")
    else:
        st.text("Model Using : sonar-pro")

    uploaded = st.file_uploader(
        "Upload (.xlsx / .xlsm)",
        type=["xlsx", "xlsm"],
        help="Clear this to fall back to the default Excel",
    )

    if uploaded is None and (ss.uploaded_bytes or ss.uploaded_name):
        ss.uploaded_bytes = None
        ss.uploaded_name = None

    if uploaded is not None:
        ss.uploaded_bytes = uploaded.getvalue()
        ss.uploaded_name = uploaded.name
        st.success(f"Selected: {uploaded.name}")

    st.markdown("---")
    ss.pdf_source = st.selectbox(
        "Guidelines PDF",
        ["Default guidelines PDF", "Upload a PDF"],
        help="Choose which PDF to pass to the model",
    )

    if ss.pdf_source == "Upload a PDF":
        uploaded_pdf = st.file_uploader("Upload PDF", type=["pdf"], key="u_pdf")

        if uploaded_pdf is not None:
            # New upload -> persist to session
            ss.uploaded_pdf_bytes = uploaded_pdf.getvalue()
            ss.uploaded_pdf_name = uploaded_pdf.name
            st.success(f"PDF selected: {uploaded_pdf.name}")

        # ELSE: do nothing. Keep whatever was already in ss.uploaded_pdf_bytes/name.
    else:
        # Switching away from upload mode — it's OK to ignore the uploaded bytes
        # (optional) keep them; they won’t be used unless user switches back.
        pass

    # Indicator line
    if ss.pdf_source == "Default guidelines PDF":
        st.text(f"Attached {PDF_FILENAME}")
    elif ss.get("uploaded_pdf_name"):
        st.text(f"Attached: {ss.uploaded_pdf_name}")
    else:
        st.info("No PDF uploaded yet.")

    col_a, col_b = st.columns(2)
    with col_a:
        show_clicked = st.button("👁️ Show", use_container_width=True)
    with col_b:
        hide_clicked = st.button("🙈 Hide", use_container_width=True)

    if show_clicked:
        try:
            if ss.uploaded_bytes:
                ss.xls = load_excel_sheets(BytesIO(ss.uploaded_bytes), ss.uploaded_name or "uploaded.xlsx")
                notify(f"Loaded from upload: {ss.uploaded_name}", icon="✅")
            else:
                if not ss.file_loaded:
                    default_excel_path = "Ring_Copy_Solution_Enhanced_with_Clownfish_Jellyfish_and_Needlefish.xlsx"
                    if not os.path.exists(default_excel_path):
                        st.error("Default Excel not found.")
                        ss.xls = None
                    else:
                        with open(default_excel_path, "rb") as f:
                            data = f.read()
                        ss.xls = load_excel_sheets(BytesIO(data), os.path.basename(default_excel_path))
                        notify("Loaded default Excel", icon="📄")

            if ss.xls is not None:
                ss.first_sheet_name = list(ss.xls.keys())[0]
                ss.first_df = ss.xls[ss.first_sheet_name]
                ss.file_loaded = True
                ss.preview_visible = True
        except Exception as e:
            st.error(f"Failed to load file: {e}")
            ss.preview_visible = False

    if hide_clicked:
        ss.preview_visible = False

    if ss.pdf_source == "Default guidelines PDF":
        st.text(f"Attached {PDF_FILENAME}")
    elif ss.uploaded_pdf_name:
        st.text(f"Attached: {ss.uploaded_pdf_name}")

# ---------- Main: Preview ----------
render_preview(ss.first_sheet_name, ss.first_df, ss.file_loaded, ss.preview_visible)

# ---------- Advanced: PUI ----------
st.markdown("### ⚙️ Advanced")
with st.expander("Advanced options", expanded=False):
    st.caption(
        "Optionally target a specific row by Product Unique Identifier. "
        "If disabled, the entire Excel workbook will be sent as context to the model."
    )
    ss.use_specific_pui = st.checkbox(
        "Select a specific Product Unique Identifier",
        value=ss.use_specific_pui,
        help="Enable to specify a column and value; otherwise the LLM sees a compact excerpt of the entire workbook.",
    )

    if ss.use_specific_pui:
        st.markdown("#### 🔎 Select Product Unique Identifier")
        if ss.first_df is not None and not ss.first_df.empty:
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
            st.caption("No data loaded yet. Use the sidebar to upload or load the default file.")
    else:
        st.session_state.pop("id_col", None)
        st.session_state.pop("id_val", None)
        st.info("Advanced targeting is **off**. The model will receive a compact excerpt of the entire workbook as context.")

# ---------- Mode picker ----------
st.markdown("### 🎛️ Choose Prompt Mode")
c1, c2, c3, c4 = st.columns(4)

label_map = {
    "ring": "Ring Copywriter",
    "social": "Social Media",
    "email": "Email Campaign",
    "audience": "Audience Adaptation",
}

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

st.caption(f"Selected Mode: **{label_map.get(ss.selected_variant, 'None')}**")

# ---------- Authoring context ----------
st.markdown("### ✍️ Authoring Context")
active_mode = ss.selected_variant or "ring"
base_key = f"ctx_{active_mode}_base"
extra_key = f"ctx_{active_mode}_extra"
guard_key = f"ctx_{active_mode}_guard"

st.text_area("Base Prompt", key=base_key, height=110)
st.text_area("Additional Context", key=extra_key, height=110)
st.text_area("Guardrails", key=guard_key, height=110)

# ---------- Generate button ----------
go = st.button("Generate Variations", use_container_width=True)


def run_generation(user_feedback: str = ""):
    provider = ss.provider
    # Resolve model from session
    model = ss.model_amazon_claude
    if provider == "OpenAI":
        model = ss.model_openai
    elif provider == "Perplexity":
        model = ss.model_perplexity

    # API keys / clients
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

    if not (ss.file_loaded and ss.first_df is not None and ss.xls is not None):
        st.error("Use the **sidebar**: upload or use default, then click **Show** at least once to load the file.")
        return
    if not ss.selected_variant:
        st.error("Please choose a Prompt Mode above before generating.")
        return

    base_prompt = ss.get(base_key, DEFAULT_CONTEXT[active_mode]["base_prompt"])  # type: ignore
    additional_context = ss.get(extra_key, DEFAULT_CONTEXT[active_mode]["additional_context"])  # type: ignore
    guardrails = ss.get(guard_key, DEFAULT_CONTEXT[active_mode]["guardrails"])  # type: ignore

    auto_guidelines, auto_template = try_autodetect_long_text(ss.xls)

    # Determine PDF source
    pdf_bytes = None
    chosen_pdf_path = None
    pdf_name = None
    if ss.pdf_source == "Upload a PDF" and ss.uploaded_pdf_bytes:
        pdf_bytes = ss.uploaded_pdf_bytes
        safe_name = os.path.basename(ss.uploaded_pdf_name or "uploaded_guidelines.pdf")
        pdf_name = safe_name
        chosen_pdf_path = safe_name
        try:
            with open(chosen_pdf_path, "wb") as wf:
                wf.write(pdf_bytes)
        except Exception as e:
            st.error(f"Failed saving uploaded PDF: {e}")
            return
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

    # Build content data
    if ss.use_specific_pui:
        selected_col = st.session_state.get("id_col")
        selected_val = st.session_state.get("id_val")
        if not selected_col or not selected_val:
            st.error("Advanced mode is enabled. Please select both a Product Unique Identifier column and value.")
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
            pydantic_model=VARIANT_MODELS[ss.selected_variant],   # <-- NEW
        )

    st.success(f"{label_map[ss.selected_variant]}: Generated {len(results)} variation(s) via {provider}")

    ss.last_results = results
    ss.last_variant = ss.selected_variant
    ss.last_prompt = system_prompt
    ss.last_expected_fields = VARIANT_FIELDS[ss.selected_variant]
    ss.last_pdf_file_id = (pdf_file_id if provider == "OpenAI" else None)
    ss.last_pdf_excerpt = (pdf_excerpt if provider == "OpenAI" else "")

    render_results(label_map[ss.selected_variant], ss.selected_variant, results, ss.last_expected_fields)


# Trigger initial generation
if go:
    run_generation("")

# ---------- Feedback & Regenerate ----------
if ss.last_results is not None:
    st.markdown("### 🗣️ Feedback")
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
