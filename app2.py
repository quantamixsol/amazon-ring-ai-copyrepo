# app.py
# Streamlit app: Generate Ring copy (TEXT variations) from an Excel template + Product Unique Identifier dropdown
# Deps: streamlit, pandas, openpyxl, (optional) xlrd==1.2.0 for .xls, python-dotenv, openai

import os
import json
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from io import BytesIO

# ---- Load .env (optional) ----
load_dotenv()

# ---- Constants ----
DEFAULT_MODEL = "gpt-4o-mini-2024-07-18"   # fast + good for copy
PDF_CONTEXT_CHARS_DEFAULT = 16000          # char cap for large fields
NUM_VARIATIONS = 3                         # fixed number of variations to return

# ---- Helpers ----
def safe_get(d, key, fallback=""):
    """Return d[key] or fallback; supports keys with _ / space variants and case-insensitive matching."""
    if not isinstance(d, dict):
        return fallback
    if key in d:
        return d.get(key, fallback)
    alt_keys = {key.replace("_", " "), key.replace(" ", "_")}
    for k in alt_keys:
        if k in d:
            return d.get(k, fallback)
    lower_map = {str(k).lower(): k for k in d.keys()}
    if key.lower() in lower_map:
        return d.get(lower_map[key.lower()], fallback)
    for k in alt_keys:
        if k.lower() in lower_map:
            return d.get(lower_map[k.lower()], fallback)
    return fallback

def coerce_str(x):
    if x is None:
        return ""
    if isinstance(x, (float, int)):
        return str(x)
    if isinstance(x, str):
        return x
    try:
        return str(x)
    except Exception:
        return ""

def try_autodetect_long_text(df_dict):
    """
    Heuristics to auto-detect Brand Guidelines and Approved Copy Template
    from any uploaded sheet. Returns (ring_brand_guidelines, approved_copy_template).
    """
    ring_brand_guidelines = ""
    approved_copy_template = ""

    prob_guideline_cols = {"brand_guidelines", "ring_brand_guidelines", "guidelines"}
    prob_template_cols = {"approved_copy_template", "copy_template", "template"}

    for sheet_name, df in df_dict.items():
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue

        # search by columns
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

        # fallback: if a sheet has a small grid with a long blob
        if df.shape[0] <= 5 and df.shape[1] <= 5:
            concatenated = " ".join([coerce_str(v) for v in df.astype(str).values.flatten().tolist()])
            if "brand" in sheet_name.lower() and len(concatenated) > len(ring_brand_guidelines):
                ring_brand_guidelines = concatenated
            if ("template" in sheet_name.lower() or "approved" in sheet_name.lower()) and len(concatenated) > len(approved_copy_template):
                approved_copy_template = concatenated

    return ring_brand_guidelines, approved_copy_template

def row_to_content_data(row: pd.Series) -> dict:
    """Normalize row -> content_data dict with expected keys (best-effort)."""
    keys = [
        "Primary_Category", "Secondary_Category", "Product_Line",
        "Channel_Optimization", "Target_Audience", "Brand_Voice_Tag",
        "Tone", "Message_Type", "Content_Type", "Content_Length",
        "Character_Count", "CTA_Type", "Feature_Focus",
        "Benefit_Highlight", "Pain_Point_Addressed", "Emotional_Appeal",
        "Technical_Level", "Customer_Journey_Stage", "Use_Case",
        "Related_Content_IDs", "Amazon_Q_Tags"
    ]
    cd = {}
    rd = row.to_dict()
    for k in keys:
        cd[k] = coerce_str(safe_get(rd, k, ""))
    return cd

def build_system_prompt_text(
    ring_brand_guidelines: str,
    approved_copy_template: str,
    content_data: dict,
    user_context: str,
    PDF_CONTEXT_CHARS: int
) -> str:
    # Trim oversized context to keep prompt lean
    ring_brand_guidelines = (ring_brand_guidelines or "")[:PDF_CONTEXT_CHARS]
    approved_copy_template = (approved_copy_template or "")[:PDF_CONTEXT_CHARS]
    user_context = user_context or ""

    # Compose a TEXT-focused system prompt (no JSON output)
    system_prompt = (
        "You are a senior copywriter for Ring. "
        "Use the brand guidelines and the approved template patterns as non-negotiable constraints. "
        "Write copy that is channel-appropriate, concise, and strictly consistent with Ring's voice.\n\n"
        f"BRAND GUIDELINES:\n{ring_brand_guidelines}\n\n"
        f"APPROVED TEMPLATE PATTERNS:\n{approved_copy_template}\n\n"
        "CONTENT CLASSIFICATION (from the Excel row):\n"
        f"- Primary Category: {content_data.get('Primary_Category','')}\n"
        f"- Secondary Category: {content_data.get('Secondary_Category','')}\n"
        f"- Product Line: {content_data.get('Product_Line','')}\n"
        f"- Channel Optimization: {content_data.get('Channel_Optimization','')}\n"
        f"- Target Audience: {content_data.get('Target_Audience','')}\n"
        f"- Brand Voice Tag: {content_data.get('Brand_Voice_Tag','')}\n"
        f"- Tone: {content_data.get('Tone','')}\n"
        f"- Message Type: {content_data.get('Message_Type','')}\n"
        f"- Content Type: {content_data.get('Content_Type','')}\n"
        f"- Content Length: {content_data.get('Content_Length','')}\n"
        f"- Character Count limit: {content_data.get('Character_Count','No limit')}\n"
        f"- CTA Type: {content_data.get('CTA_Type','')}\n"
        f"- Feature Focus: {content_data.get('Feature_Focus','')}\n"
        f"- Benefit Highlight: {content_data.get('Benefit_Highlight','')}\n"
        f"- Pain Point Addressed: {content_data.get('Pain_Point_Addressed','')}\n"
        f"- Emotional Appeal: {content_data.get('Emotional_Appeal','')}\n"
        f"- Technical Level: {content_data.get('Technical_Level','')}\n"
        f"- Customer Journey Stage: {content_data.get('Customer_Journey_Stage','')}\n"
        f"- Use Case: {content_data.get('Use_Case','')}\n"
        f"- Reference Content IDs: {content_data.get('Related_Content_IDs','')}\n"
        f"- Amazon Q Tags: {content_data.get('Amazon_Q_Tags','')}\n\n"
        f"ADDITIONAL USER CONTEXT:\n{user_context}\n\n"
        """OUTPUT REQUIREMENTS:
            Return ONLY a valid JSON object with these exact fields:
            {
                "Content_Title": "generated title",
                "Content_Body": "generated body copy", 
                "Headline_Variants": "variant1|variant2|variant3",
                "Keywords_Primary": "primary keywords",
                "Keywords_Secondary": "secondary keywords"
            }"""
    )
    return system_prompt

def get_openai_client(api_key: str = None):
    from openai import OpenAI
    if api_key:
        return OpenAI(api_key=api_key)
    return OpenAI()

def call_openai_text_variations(client, model, system_prompt, n=3, seed=None):
    """
    Uses Chat Completions to return 'n' pure-text variations (no JSON).
    """
    params = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Write {n} distinct variations. Output only the text for each variation."},
        ],
        "n": int(n),
    }
    if seed is not None:
        params["seed"] = int(seed)

    resp = client.chat.completions.create(**params)

    outputs = []
    for ch in resp.choices:
        content = ch.message.content.strip()
        outputs.append(content)
    return outputs

# ---- Enhanced OpenAI Integration ----
def get_enhanced_openai_response(client, prompt: str, model: str = DEFAULT_MODEL, 
                                n: int = 1, temperature: float = 0.7) :
    """Enhanced OpenAI call with better error handling and validation"""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Generate the Ring copy now following all requirements exactly."}
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
                required_fields = ["Content_Title", "Content_Body", "Headline_Variants", 
                                   "Keywords_Primary", "Keywords_Secondary"]
                if all(field in parsed for field in required_fields):
                    results.append(parsed)
                else:
                    results.append({"error": "Missing required fields", "raw": content})
            except json.JSONDecodeError:
                results.append({"error": "Invalid JSON", "raw": choice.message.content})
        return results
    except Exception as e:
        return [{"error": str(e)}]

def load_excel_sheets(file_buffer: BytesIO, filename: str) -> dict:
    """
    Return dict[str, DataFrame] for all sheets.
    - .xlsx/.xlsm: openpyxl
    - .xls: xlrd (if installed); otherwise raises a helpful error.
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext in [".xlsx", ".xlsm"]:
        return pd.read_excel(file_buffer, sheet_name=None, engine="openpyxl")
    elif ext == ".xls":
        try:
            return pd.read_excel(file_buffer, sheet_name=None, engine="xlrd")
        except Exception as e:
            raise RuntimeError(
                "Reading .xls requires xlrd==1.2.0. Install it with: pip install 'xlrd==1.2.0'"
            ) from e
    else:
        raise RuntimeError(f"Unsupported file extension: {ext}")

# ---- Minimal UI ----
st.set_page_config(page_title="Ring Copy Generator (Text Variations)", page_icon="🛎️", layout="wide")

# Logo at the very top
try:
    st.image("image (1).png", use_column_width=False, width=160)
except Exception:
    pass  # If the image isn't present, just continue silently.

st.title("🛎️ Ring Copy Generator — Text Variations")
st.caption("Upload your Excel template, pick a Product Unique Identifier, provide optional context, and generate copy variations in plain text.")

uploaded = st.file_uploader(
    "Upload Ring Copy Template",
    type=["xlsx", "xlsm"],
    help="Upload your Ring copy solution template"
)

xls = None
if uploaded is not None:
    try:
        xls = load_excel_sheets(BytesIO(uploaded.read()), uploaded.name)
        st.success(f"Loaded {len(xls)} sheet(s) from **{uploaded.name}**.")
    except Exception as e:
        st.error(f"Failed to read Excel: {e}")

# ------------------------- NEW: Excel Preview UI -------------------------
if xls:
    st.markdown("### 👀 Preview Excel Sheets")
    preview_rows = st.slider("Rows to show per sheet", min_value=5, max_value=500, value=50, step=5)
    sheet_names = list(xls.keys())
    tabs = st.tabs(sheet_names)
    for tab, name in zip(tabs, sheet_names):
        with tab:
            df = xls[name]
            st.write(f"**{name}** — {df.shape[0]} rows × {df.shape[1]} columns")
            if df.shape[0] > preview_rows:
                st.info(f"Showing first {preview_rows} rows.")
                st.dataframe(df.head(preview_rows))
            else:
                st.dataframe(df)
# ------------------------------------------------------------------------

def collect_all_ids(xls_dict):
    """
    Gather all possible Product Unique Identifiers from likely columns across all sheets.
    Returns (id_values: list[str], id_index: dict[value] -> (sheet_name, row_index, id_col_used))
    """
    if not xls_dict:
        return [], {}

    id_candidates = ["ID"]
    id_values = []
    id_index = {}

    for sheet_name, df in xls_dict.items():
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue

        # Choose first matching id column if any
        display_cols = [str(c) for c in df.columns]
        chosen_col = None
        for guess in id_candidates:
            if guess in display_cols:
                chosen_col = guess
                break
        if chosen_col is None and len(display_cols) > 0:
            chosen_col = display_cols[0]  # Fallback to first column

        # Record IDs
        for idx, val in df[chosen_col].items():
            sval = coerce_str(val).strip()
            if not sval:
                continue
            if sval not in id_index:
                id_index[sval] = (sheet_name, idx, chosen_col)
                id_values.append(sval)

    id_values_sorted = sorted(set(id_values))
    return id_values_sorted, id_index

product_ids = []
id_lookup = {}
if xls:
    product_ids, id_lookup = collect_all_ids(xls)
    if not product_ids:
        st.warning("No Product Unique Identifiers found. Check your sheet structure.")
    else:
        st.info(f"Detected {len(product_ids)} content ID(s) across {len(xls)} sheet(s).")

# Single dropdown (required) + context input
selected_puid = None
if product_ids:
    selected_puid = st.selectbox("Product Unique Identifier", options=product_ids, index=0)

user_context = st.text_area(
    "Additional context (optional)",
    placeholder="E.g., campaign angle, seasonal hook, target channel emphasis, promo details..."
)

# Generate button
go = st.button("Generate Variations")

# --- Generation flow ---
if go:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        st.error("Missing OPENAI_API_KEY. Set it in your environment or .env file.")
    elif not xls or not selected_puid:
        st.error("Please upload an Excel file and select a Product Unique Identifier.")
    else:
        sheet_name, row_idx, used_col = id_lookup[selected_puid]
        df = xls[sheet_name]
        row = df.loc[row_idx]
        content_data = row_to_content_data(row)

        auto_guidelines, auto_template = try_autodetect_long_text(xls)

        system_prompt = build_system_prompt_text(
            ring_brand_guidelines=auto_guidelines,
            approved_copy_template=auto_template,
            content_data=content_data,
            user_context=user_context,
            PDF_CONTEXT_CHARS=PDF_CONTEXT_CHARS_DEFAULT
        )

        with st.spinner("Generating variations..."):
            try:
                results = get_enhanced_openai_response(
                    client=get_openai_client(api_key=api_key),
                    prompt=system_prompt,
                    model=DEFAULT_MODEL,
                    n=NUM_VARIATIONS,
                    temperature=0.7
                )

                st.success(f"Generated {len(results)} variations")
                for i, result in enumerate(results, 1):
                    if 'error' in result:
                        st.error(f"Variation {i}: {result['error']}")
                        continue

                    with st.expander(f"📝 Variation {i}", expanded=(i == 1)):
                        title = result.get('Content_Title', '')
                        body = result.get('Content_Body', '')
                        st.text_area("Title", title, key=f"title_{i}")
                        st.text_area("Body", body, key=f"body_{i}")
                        st.text_input("Headlines", result.get('Headline_Variants', ''), key=f"headlines_{i}")
                        col1, col2 = st.columns(2)
                        with col1:
                            st.text_input("Primary Keywords", result.get('Keywords_Primary', ''), key=f"kw1_{i}")
                        with col2:
                            st.text_input("Secondary Keywords", result.get('Keywords_Secondary', ''), key=f"kw2_{i}")
            except Exception as e:
                st.error(f"Generation failed: {str(e)}")
