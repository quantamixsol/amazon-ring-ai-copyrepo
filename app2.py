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
        # Avoid ".0" look for ints
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
    # for k in keys:
    #     cd[k] = coerce_str(safe_get(rd, k, ""))
    return rd

def build_system_prompt_text(
    ring_brand_guidelines: str,
    approved_copy_template: str,
    content_data: dict,
    base_prompt: str,
    additional_context: str,
    guardrails: str,
    PDF_CONTEXT_CHARS: int
) -> str:
    # Trim oversized context to keep prompt lean
    ring_brand_guidelines = (ring_brand_guidelines or "")[:PDF_CONTEXT_CHARS]
    approved_copy_template = (approved_copy_template or "")[:PDF_CONTEXT_CHARS]
    base_prompt = base_prompt or ""
    additional_context = additional_context or ""
    guardrails = guardrails or ""
    system_prompt = (
        "You are a senior copywriter for Ring. "
        "Use the brand guidelines and the approved template patterns as non-negotiable constraints. "
        "Write copy that is channel-appropriate, concise, and strictly consistent with Ring's voice.\n\n"
        f"BRAND GUIDELINES:\n{ring_brand_guidelines}\n\n"
        f"APPROVED TEMPLATE PATTERNS:\n{approved_copy_template}\n\n"
        "CONTENT CLASSIFICATION (from the Excel row):\nFULL_ROW_RECORD (authoritative, use all fields below as ground truth for content generation):\n"
        f"{content_data}\n\n"
        "AUTHORING CONTEXT:\n"
        f"- Base Prompt (overall objective): {base_prompt}\n"
        f"- Additional Context (extras/nuance): {additional_context}\n"
        f"- Guardrails (what NOT to do): {guardrails}\n\n"
        """OUTPUT REQUIREMENTS:
            Return ONLY a valid JSON object with these exact fields:
            {
                "Content_Title": "generated title",
                "Content_Body": "generated body copy", 
                "Headline_Variants": "variant1|variant2|variant3",
                "Keywords_Primary": "primary keywords",
                "Keywords_Secondary": "secondary keywords",
                "Description": "compelling summary (3-5 sentences) "

            }"""
    )
    return system_prompt

def get_openai_client(api_key: str = None):
    from openai import OpenAI
    if api_key:
        return OpenAI(api_key=api_key)
    return OpenAI()

def get_enhanced_openai_response(client, prompt: str, model: str = DEFAULT_MODEL, 
                                n: int = 1, temperature: float = 0.7):
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
                                   "Keywords_Primary", "Keywords_Secondary","Description"]
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
    st.image("image (1).png", use_container_width=False, width=160)
except Exception:
    pass  # If the image isn't present, just continue silently.

st.title("🛎️ Ring Copy Generator — Text Variations")
st.caption("Upload your Excel template, pick a Product Unique Identifier (column + value) from the FIRST sheet, add context, and generate copy variations.")

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

# ------------------------- Preview: FIRST SHEET ONLY -------------------------
first_sheet_name = None
first_df = None
if xls:
    first_sheet_name = list(xls.keys())[0]
    first_df = xls[first_sheet_name]
    st.markdown("### 👀 Preview (First Sheet Only)")
    preview_rows = st.slider("Rows to show", min_value=5, max_value=500, value=50, step=5, key="preview_rows_first")
    st.write(f"**{first_sheet_name}** — {first_df.shape[0]} rows × {first_df.shape[1]} columns")
    if first_df.shape[0] > preview_rows:
        st.info(f"Showing first {preview_rows} rows.")
        st.dataframe(first_df.head(preview_rows))
    else:
        st.dataframe(first_df)

# ------------------------- NEW: Product Unique Identifier selection -------------------------
selected_id_col = None
selected_id_val = None

if first_df is not None and not first_df.empty:
    st.markdown("### 🔎 Select Product Unique Identifier")
    # 1) Dropdown: show ALL columns from the FIRST sheet
    selected_id_col = st.selectbox(
        "Product Unique Identifier (column)",
        options=[str(c) for c in first_df.columns],
        index=0
    )

    # 2) Dropdown: show ALL values present in that column
    # Clean values: drop NaN, convert to string, strip, unique, non-empty
    id_vals = (
        first_df[selected_id_col]
        .apply(coerce_str)
        .apply(lambda s: s.strip())
        .replace("", pd.NA)
        .dropna()
        .unique()
        .tolist()
    )
    id_vals_sorted = sorted(id_vals, key=lambda x: (x.lower(), x)) if id_vals else []
    if not id_vals_sorted:
        st.warning("No values detected in the selected column.")
    else:
        selected_id_val = st.selectbox(
            "Product Unique Identifier (value)",
            options=id_vals_sorted,
            index=0
        )

# ------------------------- NEW: Context fields -------------------------
st.markdown("### ✍️ Authoring Context")
base_prompt = st.text_area(
    "Base Prompt (overall objective)",
    placeholder="E.g., create a crisp product spotlight post optimized for LinkedIn with a subtle brand voice..."
)
additional_context = st.text_area(
    "Additional Context (optional)",
    placeholder="E.g., seasonal hook, promo details, target channel emphasis, competitor positioning..."
)
guardrails = st.text_area(
    "Guardrails (what NOT to do)",
    placeholder="E.g., avoid mentioning pricing, no negative comparisons, do not overpromise battery life..."
)

# Generate button
go = st.button("Generate Variations")

# --- Generation flow ---
if go:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        st.error("Missing OPENAI_API_KEY. Set it in your environment or .env file.")
    elif not xls or first_df is None:
        st.error("Please upload an Excel file.")
    elif not selected_id_col or not selected_id_val:
        st.error("Please select both Product Unique Identifier column and value.")
    else:
        # Locate the first matching row in FIRST sheet by selected column/value
        try:
            # ensure string compare
            mask = first_df[selected_id_col].apply(coerce_str).str.strip() == coerce_str(selected_id_val).strip()
            if not mask.any():
                st.error("No matching row found for the selected value.")
            else:
                row = first_df[mask].iloc[0]
                content_data = row_to_content_data(row)

                # auto-detect big text fields across ALL sheets (brand guidelines & template)
                auto_guidelines, auto_template = try_autodetect_long_text(xls)
                system_prompt = build_system_prompt_text(
                    ring_brand_guidelines=auto_guidelines,
                    approved_copy_template=auto_template,
                    content_data=content_data,
                    base_prompt=base_prompt,
                    additional_context=additional_context,
                    guardrails=guardrails,
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
                                if 'raw' in result:
                                    with st.expander(f"Raw response {i}"):
                                        st.code(result['raw'])
                                continue

                            with st.expander(f"📝 Variation {i}", expanded=(i == 1)):
                                title = result.get('Content_Title', '')
                                body = result.get('Content_Body', '')
                                st.text_area("Title", title, key=f"title_{i}")
                                st.text_area("Body", body, key=f"body_{i}")
                                st.text_input("Headlines (pipe-separated)", result.get('Headline_Variants', ''), key=f"headlines_{i}")
                                col1, col2 = st.columns(2)
                                with col1:
                                    st.text_input("Primary Keywords", result.get('Keywords_Primary', ''), key=f"kw1_{i}")
                                with col2:
                                    st.text_input("Secondary Keywords", result.get('Keywords_Secondary', ''), key=f"kw2_{i}")

                                st.text_area("Description", result.get('Description', ''), key=f"description_{i}")

                    except Exception as e:
                        st.error(f"Generation failed: {str(e)}")
        except Exception as e:
            st.error(f"Failed to locate row for the selected Product Unique Identifier: {e}")
