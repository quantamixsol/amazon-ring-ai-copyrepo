# app.py
# Streamlit app: Generate Ring copy (TEXT variations) from an Excel template + Product Unique Identifier dropdown
# Deps: streamlit, pandas, openpyxl, (optional) xlrd==1.2.0 for .xls, python-dotenv, openai

import os
import json
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from io import BytesIO
from typing import Optional, List, Dict

# ---- Load .env (optional) ----
load_dotenv()

# ---- Constants ----
DEFAULT_MODEL = "gpt-4o-mini-2024-07-18"
PDF_CONTEXT_CHARS_DEFAULT = 16000
NUM_VARIATIONS = 3

# Default Excel path fallback
DEFAULT_EXCEL_PATH = r"D:\Quantamix solution\amazon-ring-ai-copyrepo\Ring_Copy_Solution_Enhanced_with_Clownfish_Jellyfish_and_Needlefish.xlsx"

# ---- Notification helper ----
def notify(msg: str, icon: Optional[str] = None):
    if hasattr(st, "toast"):
        st.toast(msg, icon=icon)
    else:
        if icon == "✅":
            st.success(msg)
        elif icon == "📄":
            st.info(msg)
        else:
            st.info(msg)

# ---- Helpers ----
def coerce_str(x):
    if x is None:
        return ""
    if isinstance(x, (float, int)):
        if isinstance(x, float) and x.is_integer():
            return str(int(x))
        return str(x)
    if isinstance(x, str):
        return x
    try:
        return str(x)
    except Exception:
        return ""

def try_autodetect_long_text(df_dict):
    ring_brand_guidelines = ""
    approved_copy_template = ""
    prob_guideline_cols = {"brand_guidelines", "ring_brand_guidelines", "guidelines"}
    prob_template_cols = {"approved_copy_template", "copy_template", "template"}

    for sheet_name, df in df_dict.items():
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        for col in df.columns:
            lcol = str(col).strip().lower()
            if lcol in prob_guideline_cols:
                text = " ".join([coerce_str(v) for v in df[col].dropna().tolist()])
                if len(text) > len(ring_brand_guidelines):
                    ring_brand_guidelines = text
            if lcol in prob_template_cols:
                text = " ".join([coerce_str(v) for v in df[col].dropna().tolist()])
                if len(text) > len(approved_copy_template):
                    approved_copy_template = text

        if df.shape[0] <= 5 and df.shape[1] <= 5:
            concatenated = " ".join([coerce_str(v) for v in df.astype(str).values.flatten().tolist()])
            if "brand" in sheet_name.lower() and len(concatenated) > len(ring_brand_guidelines):
                ring_brand_guidelines = concatenated
            if ("template" in sheet_name.lower() or "approved" in sheet_name.lower()) and len(concatenated) > len(approved_copy_template):
                approved_copy_template = concatenated
    return ring_brand_guidelines, approved_copy_template

def row_to_content_data(row: pd.Series) -> dict:
    return row.to_dict()

# ---------- Expected fields per variant ----------
VARIANT_FIELDS: Dict[str, List[str]] = {
    # 1) Ring Copywriter
    "ring": [
        "Content_Title",
        "Content_Body",
        "Headline_Variants",
        "Keywords_Primary",
        "Keywords_Secondary",
        "Description",
    ],
    # 2) Social Media
    "social": [
        "Hashtags",
        "Engagement_Hook",
        "Value_Prop",
        "Address_Concerns",
        "Content",
    ],
    # 3) Email Campaign
    "email": [
        "Subject_Line",
        "Greeting",
        "Main_Content",
        "Reference",
    ],
    # 4) Audience Adaptation (replaces Cross-Channel)
    "audience": [
        "Easy_Installation_Self_Setup",
        "Technical_Features_and_Control",
        "Technical_Specifications",
        "Security_Benefits_Messaging",
    ],
}

# ---------- System prompt variants ----------
def build_output_requirements_json(variant: str) -> str:
    """Return an OUTPUT REQUIREMENTS block with exact JSON schema per variant."""
    if variant == "ring":
        schema = """
Return ONLY a valid JSON object with these exact fields:
{
    "Content_Title": "...",
    "Content_Body": "...",
    "Headline_Variants": "...|...|...",
    "Keywords_Primary": "...",
    "Keywords_Secondary": "...",
    "Description": "..."
}"""
    elif variant == "social":
        schema = """
Return ONLY a valid JSON object with these exact fields:
{
    "Hashtags": "#... #... #...",
    "Engagement_Hook": "...",
    "Value_Prop": "...",
    "Address_Concerns": "Address missed deliveries and home absence concerns ...",
    "Content": "..."
}"""
    elif variant == "email":
        schema = """
Return ONLY a valid JSON object with these exact fields:
{
    "Subject_Line": "...",
    "Greeting": "...",
    "Main_Content": "100-150 words ...",
    "Reference": "..."
}"""
    elif variant == "audience":
        schema = """
Return ONLY a valid JSON object with these exact fields:
{
    "Easy_Installation_Self_Setup": "...",
    "Technical_Features_and_Control": "...",
    "Technical_Specifications": "...",
    "Security_Benefits_Messaging": "..."
}"""
    else:
        schema = """
Return ONLY a valid JSON object with a single key "Note": "Unsupported variant provided."""
    return "OUTPUT REQUIREMENTS:\n" + schema

def build_variant_opening(variant: str) -> str:
    if variant == "ring":
        return (
            "You are a senior copywriter for Ring. "
            "Use the brand guidelines and the approved template patterns as non-negotiable constraints. "
            "Write copy that is channel-appropriate, concise, and strictly consistent with Ring's voice."
        )
    if variant == "social":
        return (
            "You are a Social Media Content Creator for Ring. "
            "Craft platform-native, scroll-stopping copy with clear hooks and CTAs while honoring Ring's brand voice. "
            "Optimize for engagement (thumb-stopping first line, brevity, scannability, hashtags where relevant)."
        )
    if variant == "email":
        return (
            "You are an Email Campaign Generator for Ring. "
            "Create persuasive email copy with a compelling subject line, preview snippet feel, and clear CTA hierarchy. "
            "Maintain brand voice, avoid spammy wording, and keep body copy crisp and conversion-focused."
        )
    if variant == "audience":
        return (
            "You are an Audience Adaptation campaign specialist for Ring. "
            "Develop messaging that emphasizes easy installation and self-setup, highlights technical features and control, "
            "includes technical specifications, and maintains strong security benefits messaging."
        )
    return "You are a senior copywriter for Ring."

def build_system_prompt_text_variant(
    variant: str,
    ring_brand_guidelines: str,
    approved_copy_template: str,
    content_data: dict,
    base_prompt: str,
    additional_context: str,
    guardrails: str,
    PDF_CONTEXT_CHARS: int,
) -> str:
    ring_brand_guidelines = (ring_brand_guidelines or "")[:PDF_CONTEXT_CHARS]
    approved_copy_template = (approved_copy_template or "")[:PDF_CONTEXT_CHARS]

    system_prompt = (
        f"{build_variant_opening(variant)}\n\n"
        f"BRAND GUIDELINES:\n{ring_brand_guidelines}\n\n"
        f"APPROVED TEMPLATE PATTERNS:\n{approved_copy_template}\n\n"
        "CONTENT CLASSIFICATION (from the Excel row):\n"
        f"{content_data}\n\n"
        "AUTHORING CONTEXT:\n"
        f"- Base Prompt: {base_prompt}\n"
        f"- Additional Context: {additional_context}\n"
        f"- Guardrails: {guardrails}\n\n"
        f"{build_output_requirements_json(variant)}"
    )
    return system_prompt

def get_openai_client(api_key: str = None):
    from openai import OpenAI
    return OpenAI(api_key=api_key) if api_key else OpenAI()

def get_enhanced_openai_response(
    client,
    prompt: str,
    expected_fields: List[str],
    model: str = DEFAULT_MODEL,
    n: int = 1,
    temperature: float = 0.7
):
    """Call model and validate that all expected_fields are present."""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Generate the copy now following all requirements exactly."}
            ],
            response_format={"type": "json_object"},
            n=n,
            temperature=temperature,
            max_tokens=4000
        )
        results = []
        for choice in response.choices:
            try:
                content = choice.message.content
                parsed = json.loads(content)
                if all(field in parsed for field in expected_fields):
                    results.append(parsed)
                else:
                    results.append({"error": "Missing fields", "raw": content})
            except json.JSONDecodeError:
                results.append({"error": "Invalid JSON", "raw": choice.message.content})
        return results
    except Exception as e:
        return [{"error": str(e)}]

def load_excel_sheets(file_buffer: BytesIO, filename: str) -> dict:
    ext = os.path.splitext(filename)[1].lower()
    if ext in [".xlsx", ".xlsm"]:
        return pd.read_excel(file_buffer, sheet_name=None, engine="openpyxl")
    elif ext == ".xls":
        try:
            return pd.read_excel(file_buffer, sheet_name=None, engine="xlrd")
        except Exception as e:
            raise RuntimeError("Reading .xls requires xlrd==1.2.0") from e
    else:
        raise RuntimeError(f"Unsupported file extension: {ext}")

# ---- Page config ----
st.set_page_config(page_title="Ring Copy Generator", page_icon="🛎️", layout="wide")

# ---- Session state ----
ss = st.session_state
ss.setdefault("initialized", False)
ss.setdefault("file_loaded", False)      # file loaded & first_df ready
ss.setdefault("preview_visible", False)  # preview visibility
ss.setdefault("xls", None)
ss.setdefault("first_df", None)
ss.setdefault("first_sheet_name", None)
ss.setdefault("uploaded_bytes", None)
ss.setdefault("uploaded_name", None)
ss.setdefault("selected_variant", None)  # "ring"/"social"/"email"/"audience"

# ---------- AUTO-LOAD so PUI shows on first open ----------
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

# ====================== SIDEBAR (Upload & Controls) ======================
with st.sidebar:
    st.header("📁 Source & Controls")

    uploaded = st.file_uploader("Upload (.xlsx / .xlsm)", type=["xlsx", "xlsm"],
                                help="Clear this to fall back to the default Excel")

    if uploaded is None and (ss.uploaded_bytes or ss.uploaded_name):
        ss.uploaded_bytes = None
        ss.uploaded_name = None

    if uploaded is not None:
        ss.uploaded_bytes = uploaded.getvalue()
        ss.uploaded_name = uploaded.name
        st.success(f"Selected: {uploaded.name}")

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
                    if not os.path.exists(DEFAULT_EXCEL_PATH):
                        st.error(f"Default Excel not found at: {DEFAULT_EXCEL_PATH}")
                        ss.xls = None
                    else:
                        with open(DEFAULT_EXCEL_PATH, "rb") as f:
                            data = f.read()
                        ss.xls = load_excel_sheets(BytesIO(data), os.path.basename(DEFAULT_EXCEL_PATH))
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

# ====================== MAIN AREA ======================
st.title("🛎️ Ring Copy Generator — Text Variations")
st.caption("Upload your Excel in the sidebar, pick a Product Unique Identifier, choose a prompt mode, and then generate.")

# Preview
if ss.preview_visible and ss.first_df is not None:
    st.markdown("### 👀 Preview (First Sheet Only)")
    preview_rows = st.slider("Rows to show", 5, 500, 50, 5, key="preview_rows_first")
    st.write(f"**{ss.first_sheet_name}** — {ss.first_df.shape[0]} rows × {ss.first_df.shape[1]} columns")
    st.dataframe(
        ss.first_df.head(preview_rows) if ss.first_df.shape[0] > preview_rows else ss.first_df,
        use_container_width=True
    )
elif not ss.file_loaded:
    st.info("Use the **sidebar** to upload/select a file and click **Show** to preview.")
else:
    st.info("Preview is hidden. Click **Show** in the sidebar to display the Excel preview.")

# ---------- PUI SECTION (always visible) ----------
st.markdown("### 🔎 Select Product Unique Identifier")
if ss.first_df is not None and not ss.first_df.empty:
    cols_list = [str(c) for c in ss.first_df.columns]
    selected_id_col = st.selectbox("Column", cols_list, key="id_col", disabled=not ss.file_loaded)

    if ss.file_loaded:
        id_vals = (
            ss.first_df[selected_id_col]
            .apply(coerce_str)
            .apply(lambda s: s.strip())
            .replace("", pd.NA)
            .dropna()
            .unique()
            .tolist()
        )
        selected_id_val = st.selectbox(
            "Value",
            sorted(id_vals, key=lambda x: (x.lower(), x)) if id_vals else [],
            key="id_val",
            disabled=not ss.file_loaded
        ) if id_vals else None
    else:
        selected_id_val = None
        st.caption("Upload or load a file to enable the selectors.")
else:
    selected_id_col = st.selectbox("Column", [], key="id_col", disabled=True)
    selected_id_val = st.selectbox("Value", [], key="id_val", disabled=True)
    st.caption("No data loaded yet. Use the sidebar to upload or load the default file.")

# ---------- PROMPT MODE PICKER (directly under PUI) ----------
st.markdown("### 🎛️ Choose Prompt Mode")
c1, c2, c3, c4 = st.columns(4)
with c1:
    if st.button("Ring Copywriter", use_container_width=True):
        ss.selected_variant = "ring"
with c2:
    if st.button("Social Media", use_container_width=True):
        ss.selected_variant = "social"
with c3:
    if st.button("Email Campaign", use_container_width=True):
        ss.selected_variant = "email"
with c4:
    if st.button("Audience Adaptation", use_container_width=True):
        ss.selected_variant = "audience"

label_map = {
    "ring": "Ring Copywriter",
    "social": "Social Media",
    "email": "Email Campaign",
    "audience": "Audience Adaptation",
}
st.caption(f"Selected Mode: **{label_map.get(ss.selected_variant, 'None')}**")

# ---------- Authoring context ----------
st.markdown("### ✍️ Authoring Context")
base_prompt = st.text_area("Base Prompt", key="base_prompt")
additional_context = st.text_area("Additional Context", key="additional_context")
guardrails = st.text_area("Guardrails", key="guardrails")

# ---------- SINGLE Generate button (runs the selected mode) ----------
go = st.button("Generate Variations", use_container_width=True)
if go:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        st.error("Missing OPENAI_API_KEY.")
    elif not (ss.file_loaded and ss.first_df is not None):
        st.error("Use the **sidebar**: upload or use default, then click **Show** at least once to load the file.")
    elif not selected_id_col or not selected_id_val:
        st.error("Please select both Product Unique Identifier column and value.")
    elif not ss.selected_variant:
        st.error("Please choose a Prompt Mode above before generating.")
    else:
        mask = ss.first_df[selected_id_col].apply(coerce_str).str.strip() == coerce_str(selected_id_val).strip()
        if not mask.any():
            st.error("No matching row found.")
        else:
            row = ss.first_df[mask].iloc[0]
            content_data = row_to_content_data(row)
            auto_guidelines, auto_template = try_autodetect_long_text(ss.xls)
            system_prompt = build_system_prompt_text_variant(
                variant=ss.selected_variant,
                ring_brand_guidelines=auto_guidelines,
                approved_copy_template=auto_template,
                content_data=content_data,
                base_prompt=base_prompt,
                additional_context=additional_context,
                guardrails=guardrails,
                PDF_CONTEXT_CHARS=PDF_CONTEXT_CHARS_DEFAULT
            )
            with st.spinner(f"Generating ({label_map[ss.selected_variant]})..."):
                results = get_enhanced_openai_response(
                    get_openai_client(api_key),
                    system_prompt,
                    expected_fields=VARIANT_FIELDS[ss.selected_variant],
                    model=DEFAULT_MODEL,
                    n=NUM_VARIATIONS,
                    temperature=0.7
                )
                st.success(f"{label_map[ss.selected_variant]}: Generated {len(results)} variation(s)")

                # ---------- Render by variant ----------
                for i, result in enumerate(results, 1):
                    if 'error' in result:
                        st.error(f"{label_map[ss.selected_variant]} — Variation {i}: {result['error']}")
                        if 'raw' in result:
                            with st.expander(f"{label_map[ss.selected_variant]} — Raw {i}"):
                                st.code(result['raw'])
                        continue

                    if ss.selected_variant == "ring":
                        with st.expander(f"{label_map[ss.selected_variant]} — 📝 Variation {i}", expanded=(i == 1)):
                            st.text_area("Title", result.get("Content_Title", ""), key=f"{ss.selected_variant}_title_{i}")
                            st.text_area("Body", result.get("Content_Body", ""), key=f"{ss.selected_variant}_body_{i}")
                            st.text_input("Headlines (pipe-separated)", result.get("Headline_Variants", ""), key=f"{ss.selected_variant}_head_{i}")
                            cA, cB = st.columns(2)
                            with cA:
                                st.text_input("Primary Keywords", result.get("Keywords_Primary", ""), key=f"{ss.selected_variant}_kw1_{i}")
                            with cB:
                                st.text_input("Secondary Keywords", result.get("Keywords_Secondary", ""), key=f"{ss.selected_variant}_kw2_{i}")
                            st.text_area("Description", result.get("Description", ""), key=f"{ss.selected_variant}_desc_{i}")

                    elif ss.selected_variant == "social":
                        with st.expander(f"{label_map[ss.selected_variant]} — 📣 Variation {i}", expanded=(i == 1)):
                            st.text_area("Hashtags", result.get("Hashtags", ""), key=f"{ss.selected_variant}_hashtags_{i}")
                            st.text_area("Engagement Hook", result.get("Engagement_Hook", ""), key=f"{ss.selected_variant}_hook_{i}")
                            st.text_area("Clear Value Proposition", result.get("Value_Prop", ""), key=f"{ss.selected_variant}_vp_{i}")
                            st.text_area("Address Missed Deliveries & Absence Concerns", result.get("Address_Concerns", ""), key=f"{ss.selected_variant}_concerns_{i}")
                            st.text_area("Content", result.get("Content", ""), key=f"{ss.selected_variant}_content_{i}")

                    elif ss.selected_variant == "email":
                        with st.expander(f"{label_map[ss.selected_variant]} — ✉️ Variation {i}", expanded=(i == 1)):
                            st.text_input("Subject Line", result.get("Subject_Line", ""), key=f"{ss.selected_variant}_subj_{i}")
                            st.text_input("Greeting", result.get("Greeting", ""), key=f"{ss.selected_variant}_greet_{i}")
                            st.text_area("Main Content (100-150 words)", result.get("Main_Content", ""), key=f"{ss.selected_variant}_main_{i}")
                            st.text_input("Reference", result.get("Reference", ""), key=f"{ss.selected_variant}_ref_{i}")

                    elif ss.selected_variant == "audience":
                        with st.expander(f"{label_map[ss.selected_variant]} — 🧩 Variation {i}", expanded=(i == 1)):
                            st.text_area("Emphasize easy installation & self-setup", result.get("Easy_Installation_Self_Setup", ""), key=f"{ss.selected_variant}_install_{i}")
                            st.text_area("Highlight technical features & control", result.get("Technical_Features_and_Control", ""), key=f"{ss.selected_variant}_features_{i}")
                            st.text_area("Include technical specifications", result.get("Technical_Specifications", ""), key=f"{ss.selected_variant}_specs_{i}")
                            st.text_area("Maintain security benefits messaging", result.get("Security_Benefits_Messaging", ""), key=f"{ss.selected_variant}_security_{i}")
