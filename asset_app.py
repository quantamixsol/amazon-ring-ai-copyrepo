import streamlit as st
import pandas as pd
import io
from PyPDF2 import PdfReader
from dotenv import load_dotenv
import re, json, os, textwrap

# Optional: OpenAI client (needed for generation)
try:
    from openai import OpenAI
    OPENAI_CLIENT = OpenAI()
except Exception:
    OPENAI_CLIENT = None  # App will warn if generation is attempted without client

# ============================
# Setup
# ============================
load_dotenv()
st.set_page_config(page_title="Ring CopyRepo Intelligence — Preserve Excel Columns", layout="wide")

PDF_CONTEXT_CHARS = 1500
DEFAULT_TEMPLATE_PATH = "Ring_Copy_Solution_Enhanced_with_Clownfish_Jellyfish_and_Needlefish.xlsx"

# ============================
# Styles
# ============================
st.markdown(
    """
    <style>
      .stButton>button, .stDownloadButton>button { background-color:#0057A4; color:white; border:none; }
      .stApp { font-family: Arial, sans-serif; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Ring CopyRepo Intelligence — Append PUI (Preserve ALL Excel Columns)")

# ============================
# Helpers
# ============================
def parse_char_limit(val):
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, str):
        m = re.search(r"(\d+)", val)
        if m:
            return int(m.group(1))
    return None

def extract_text_from_pdf(uploaded_file):
    try:
        reader = PdfReader(uploaded_file)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as e:
        st.warning(f"Could not read PDF: {e}")
        return ""

def ensure_openai():
    if OPENAI_CLIENT is None:
        st.error("OpenAI client not available. Install `openai` and set OPENAI_API_KEY.")
        return False
    return True

def pick_field_col(df):
    # No mapping UI; auto-detect common variants and fall back to first column
    for c in ["Field_Name", "Field Name", "Field"]:
        if c in df.columns:
            return c
    return df.columns[0]

def build_json_template(field_names):
    """Keys = every row's Field_Name (exactly as in Excel)."""
    return {name: "" for name in field_names}

def make_system_prompt(product_desc, branding_text, product_text, claims_text):
    blurb = textwrap.dedent("""
    You are a Ring copywriter working with an Excel template that defines content fields as rows.
    Your task: generate NEW COPY for EVERY FIELD in the JSON skeleton using ONLY the provided inputs.

    STRICT RULES:
    - Base claims on PRODUCT INFORMATION; align tone with BRAND GUIDELINES/PRODUCT DETAILS.
    - Only reference Ring products/features present in the inputs.
    - Respect character limits exactly when provided.
    - Return ONE valid JSON object with values for EVERY KEY in the skeleton.
    - Do NOT add or omit keys. Do NOT include markdown or commentary.
    """).strip()

    blocks = []
    if product_desc:
        blocks.append(f"PRODUCT INFORMATION (source of truth):\n{product_desc[:PDF_CONTEXT_CHARS]}")
    if branding_text:
        blocks.append(f"BRAND GUIDELINES (truncated):\n{branding_text[:PDF_CONTEXT_CHARS]}")
    if product_text:
        blocks.append(f"PRODUCT DETAILS (truncated):\n{product_text[:PDF_CONTEXT_CHARS]}")
    if claims_text:
        blocks.append(f"APPROVED CLAIMS (truncated):\n{claims_text[:PDF_CONTEXT_CHARS]}")

    return blurb + "\n\n" + ("\n\n".join(blocks) if blocks else "")

def make_user_prompt(skeleton, char_limits):
    lim_lines = "\n".join([f"- {name}: {limit if limit else 'no limit'} chars" for name, limit in char_limits])
    skeleton_str = json.dumps(skeleton, ensure_ascii=False)
    return textwrap.dedent(f"""
    Fill the following JSON skeleton with on-brand copy for each key.
    Return ONLY a single valid JSON object. No markdown, no extra keys.

    JSON skeleton:
    {skeleton_str}

    Character limits (stay under when provided):
    {lim_lines}
    """).strip()

# ============================
# Sidebar: Inputs/Assets
# ============================
st.sidebar.header("Inputs & Assets")
uploaded_template = st.sidebar.file_uploader(
    "Upload Template (XLSX/XLSM)", type=["xlsx", "xlsm"], key="upl_temp",
    help="We preserve ALL columns (structure) exactly as in this Excel."
)
branding_pdf = st.sidebar.file_uploader("Brand Guidelines (PDF)", type=["pdf"], key="brand_pdf")
product_pdf = st.sidebar.file_uploader("Product Details (PDF)", type=["pdf"], key="prod_pdf")
acl_file = st.sidebar.file_uploader("Approved Claims List (CSV)", type=["csv"], key="acl_csv")

# Optional model selection
use_finetuned_model = st.sidebar.radio("Model", ["GPT-5 (Standard)", "Fine-tuned"], index=0)
finetuned_model_id = st.sidebar.text_input("Fine-tuned model id", value="", help="ft:gpt-5-... (if using)")

# ============================
# Load template (preserve ALL columns)
# ============================
template_df = None
errors = []

if uploaded_template is not None:
    try:
        with io.BytesIO(uploaded_template.read()) as buf:
            raw = pd.read_excel(buf, sheet_name=0, engine="openpyxl")
        df = raw.dropna(how='all', axis=0).dropna(how='all', axis=1)
        # Lift first row as headers if it looks like headers
        headers = df.iloc[0].astype(str).str.strip().tolist()
        if any(h in headers for h in ["Field_Name", "Field Name", "Field"]):
            df.columns = headers
            df = df[1:]
        df.columns = [str(c).strip() for c in df.columns]
        template_df = df.fillna("").reset_index(drop=True)
    except Exception as e:
        errors.append(f"Error loading uploaded template: {e}")

if template_df is None:
    try:
        template_df = pd.read_excel(DEFAULT_TEMPLATE_PATH).fillna("").reset_index(drop=True)
    except Exception as e:
        errors.append(f"Could not load fallback template at {DEFAULT_TEMPLATE_PATH}: {e}")

for err in errors:
    st.error(err)

if template_df is None or template_df.empty:
    st.stop()

# Fixed expectations (NO mapping UI)
FIELD_COL = pick_field_col(template_df)
CONTENT_TYPE_COL = "Content_Type"
CHAR_COUNT_COL = "Character_Count"

if CONTENT_TYPE_COL not in template_df.columns:
    st.error("Template must include a 'Content_Type' column.")
    st.stop()

if CHAR_COUNT_COL not in template_df.columns:
    st.warning("No 'Character_Count' column found. Character limits will be treated as unlimited.")
    CHAR_COUNT_COL = None

# Preview
st.subheader("Excel Template (Preserved Columns)")
st.caption(f"Field column detected: {FIELD_COL} | Content_Type: yes | Character_Count: {'yes' if CHAR_COUNT_COL else 'no'}")
st.dataframe(template_df, use_container_width=True)

# Build field list and char limits
field_names = [str(x).strip() for x in template_df[FIELD_COL].tolist() if str(x).strip()]
char_limits_map = {}
if CHAR_COUNT_COL:
    for _, row in template_df.iterrows():
        fname = str(row.get(FIELD_COL, "")).strip()
        limit = parse_char_limit(row.get(CHAR_COUNT_COL))
        if fname:
            char_limits_map[fname] = limit

# Optional assets
branding_text = extract_text_from_pdf(branding_pdf) if branding_pdf else ""
product_text_pdf = extract_text_from_pdf(product_pdf) if product_pdf else ""
acl_df = pd.read_csv(acl_file) if acl_file else pd.DataFrame()
claims_text = ""
if not acl_df.empty:
    claim_cols = [c for c in acl_df.columns if c not in ["Pack Contents", "Disclaimer"]]
    if claim_cols:
        claims_text = " ".join(acl_df[claim_cols].fillna("").astype(str).agg(" ".join, axis=1).tolist())

# Preserve the entire template structure in session
if "preserved_df" not in st.session_state:
    st.session_state["preserved_df"] = template_df.copy()

# ============================
# Append PUI column (preserve ALL other columns exactly)
# ============================
st.header("Append NEW PUI Column (fills all rows/fields)")

new_pui = st.text_input("PUI (Content ID) — this will become a NEW COLUMN", placeholder="e.g., PUI-NEW-001")
product_info = st.text_area("Product Information (source of truth for copy)", height=180)

model_choice = finetuned_model_id.strip() if (use_finetuned_model == "Fine-tuned" and finetuned_model_id.strip()) else "gpt-5"

if st.button("Generate & Append PUI Column", type="primary"):
    if not new_pui.strip():
        st.error("Please provide a PUI (Content ID) to create.")
        st.stop()

    preserved = st.session_state["preserved_df"].copy()

    if new_pui in preserved.columns:
        st.error(f"A column named '{new_pui}' already exists. Choose a different PUI.")
        st.stop()

    if not product_info.strip():
        st.error("Please provide Product Information.")
        st.stop()

    if not ensure_openai():
        st.stop()

    # JSON skeleton and limits
    skeleton = build_json_template(field_names)
    char_limits_pairs = [(name, char_limits_map.get(name)) for name in field_names]

    # Prompts
    system_prompt = make_system_prompt(
        product_desc=product_info,
        branding_text=branding_text,
        product_text=product_text_pdf,
        claims_text=claims_text
    )
    user_prompt = make_user_prompt(skeleton, char_limits_pairs)

    try:
        resp = OPENAI_CLIENT.chat.completions.create(
            model=model_choice,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"}
        )
        ai_output = resp.choices[0].message.content
        parsed = json.loads(ai_output)
    except Exception as e:
        st.error(f"AI generation failed: {e}")
        st.stop()

    # Add the new PUI column and populate per row/field
    preserved[new_pui] = ""
    warnings = []
    for i, row in preserved.iterrows():
        fname = str(row.get(FIELD_COL, "")).strip()
        ctype = str(row.get(CONTENT_TYPE_COL, "")).strip()
        val = parsed.get(fname, "")

        # ACL fallback for Pack Contents / Disclaimer
        if not val and not acl_df.empty:
            if ctype == "Pack Contents" and ("Pack Contents" in acl_df.columns):
                val = ", ".join(acl_df["Pack Contents"].dropna().astype(str).unique())
            elif ctype == "Disclaimer" and ("Disclaimer" in acl_df.columns):
                val = "\n".join(acl_df["Disclaimer"].dropna().astype(str).tolist())

        # Enforce char limit
        limit = char_limits_map.get(fname)
        if limit and isinstance(val, str) and len(val) > limit:
            warnings.append(f"{fname} exceeds {limit} characters; truncated.")
            val = val[:limit]

        preserved.at[i, new_pui] = val

    st.session_state["preserved_df"] = preserved
    st.success(f"Appended new PUI column: {new_pui}")
    for w in warnings:
        st.warning(w)

# ============================
# Review & Export (Exact Excel columns preserved)
# ============================
st.header("Template (with ALL original columns, plus any new PUI columns)")
st.dataframe(st.session_state["preserved_df"], use_container_width=True)

st.subheader("Export")
csv_bytes = st.session_state["preserved_df"].to_csv(index=False).encode()
st.download_button("Download CSV (preserved structure)", csv_bytes, file_name="ring_copy_template_preserved.csv")

xlsx_buf = io.BytesIO()
with pd.ExcelWriter(xlsx_buf, engine="openpyxl") as writer:
    st.session_state["preserved_df"].to_excel(writer, index=False)
xlsx_buf.seek(0)
st.download_button("Download Excel (preserved structure)", xlsx_buf, file_name="ring_copy_template_preserved.xlsx")

with st.expander("How to run locally"):
    st.markdown(
        """
        1) Set your OpenAI API key:
           - macOS/Linux: `export OPENAI_API_KEY=sk-...`
           - Windows (PowerShell): `$Env:OPENAI_API_KEY='sk-...'`
        2) Install: `pip install streamlit pandas openpyxl PyPDF2 python-dotenv openai`
        3) Run: `streamlit run ring_copy_app.py`
        """
    )
