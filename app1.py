# app.py
# Streamlit app: Generate Ring copy from an Excel template + Product Unique Identifier
# Deps: streamlit, pandas, openpyxl, openai, python-dotenv, (optional) xlrd==1.2.0 for .xls

import os
import json
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from io import BytesIO

# ---- Load .env (optional) ----
load_dotenv()

# ---- Constants ----
DEFAULT_MODEL = "gpt-4o-mini-2024-07-18"   # fast + strong JSON-mode
PDF_CONTEXT_CHARS_DEFAULT = 16000          # char cap for large fields
MAX_VARIATIONS = 10

# ---- Helpers ----
def safe_get(d, key, fallback=""):
    """Return d[key] or fallback; supports keys with _ / space variants."""
    if not isinstance(d, dict):
        return fallback
    if key in d:
        return d.get(key, fallback)
    # Try underscore/space normalization fallbacks
    alt_keys = {key.replace("_", " "), key.replace(" ", "_")}
    for k in alt_keys:
        if k in d:
            return d.get(k, fallback)
    # Case-insensitive fallback
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

    # Look for probable columns by name
    prob_guideline_cols = {"brand_guidelines", "ring_brand_guidelines", "guidelines"}
    prob_template_cols = {"approved_copy_template", "copy_template", "template"}

    # Scan each sheet
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

        # fallback: if a sheet has a single cell-ish long text blob
        if df.shape[0] <= 5 and df.shape[1] <= 5:
            concatenated = " ".join([coerce_str(v) for v in df.astype(str).values.flatten().tolist()])
            if "brand" in sheet_name.lower() and len(concatenated) > len(ring_brand_guidelines):
                ring_brand_guidelines = concatenated
            if ("template" in sheet_name.lower() or "approved" in sheet_name.lower()) and len(concatenated) > len(approved_copy_template):
                approved_copy_template = concatenated

    return ring_brand_guidelines, approved_copy_template

def row_to_content_data(row: pd.Series) -> dict:
    """Normalize row -> content_data dict with expected keys."""
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
    for k in keys:
        cd[k] = coerce_str(safe_get(row.to_dict(), k, ""))
    return cd

def build_system_prompt(
    ring_brand_guidelines: str,
    approved_copy_template: str,
    content_data: dict,
    user_context: str,
    PDF_CONTEXT_CHARS: int
) -> str:
    ring_brand_guidelines = ring_brand_guidelines[:PDF_CONTEXT_CHARS]
    approved_copy_template = approved_copy_template[:PDF_CONTEXT_CHARS]
    user_inputs = {"context": user_context or ""}

    system_prompt = (
        f"You are a Ring copywriter using the Ring Copy Solution Template system. "
        f"Brand guidelines: {ring_brand_guidelines}. "
        f"Approved copy template: {approved_copy_template}. "
        f"Content classification: Primary Category: {content_data.get('Primary_Category', '')}, "
        f"Secondary Category: {content_data.get('Secondary_Category', '')}, "
        f"Product Line: {content_data.get('Product_Line', '')}. "
        f"Target specifications: Channel Optimization: {content_data.get('Channel_Optimization', '')}, "
        f"Target Audience: {content_data.get('Target_Audience', '')}, "
        f"Brand Voice Tag: {content_data.get('Brand_Voice_Tag', '')}, "
        f"Tone: {content_data.get('Tone', '')}, "
        f"Message Type: {content_data.get('Message_Type', '')}. "
        f"Content requirements: Content Type: {content_data.get('Content_Type', '')}, "
        f"Content Length: {content_data.get('Content_Length', '')}, "
        f"Character Count limit: {content_data.get('Character_Count', 'No limit')}, "
        f"CTA Type: {content_data.get('CTA_Type', '')}. "
        f"Focus areas: Feature Focus: {content_data.get('Feature_Focus', '')}, "
        f"Benefit Highlight: {content_data.get('Benefit_Highlight', '')}, "
        f"Pain Point Addressed: {content_data.get('Pain_Point_Addressed', '')}, "
        f"Emotional Appeal: {content_data.get('Emotional_Appeal', '')}. "
        f"Technical specifications: Technical Level: {content_data.get('Technical_Level', '')}, "
        f"Customer Journey Stage: {content_data.get('Customer_Journey_Stage', '')}, "
        f"Use Case: {content_data.get('Use_Case', '')}. "
        f"Reference Content ID: {content_data.get('Related_Content_IDs', '')}, "
        f"Amazon Q Tags: {content_data.get('Amazon_Q_Tags', '')}. "
        f"Additional context: {user_inputs.get('context', '')}. "
        "Generate new Ring copy based on the approved template patterns while maintaining exact brand voice consistency. "
        "Only reference Ring products and features from the provided template data. "
        "Ensure content adheres to specified channel optimization, character limits, and technical level requirements. "
        "Each variation must be unique while maintaining Ring's brand guidelines and approved messaging patterns. "
        "Return a single valid JSON object with the following fields: "
        "{'Content_Title': 'generated title', 'Content_Body': 'generated body copy', 'Headline_Variants': 'variant1|variant2|variant3', "
        "'Keywords_Primary': 'primary keywords', 'Keywords_Secondary': 'secondary keywords'}. "
        "Do not include any markdown, explanatory text, or fields not specified—only the JSON object."
    )
    return system_prompt

def get_openai_client(api_key: str = None):
    # Uses the modern OpenAI SDK interface (client.chat.completions)
    from openai import OpenAI
    if api_key:
        return OpenAI(api_key=api_key)
    return OpenAI()

def call_openai(client, model, system_prompt, n=1, seed=None):
    """
    Uses Chat Completions with JSON mode to force valid JSON.
    Returns a list of JSON dicts (length == n).
    """
    params = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Generate the JSON object now."},
        ],
        "response_format": {"type": "json_object"},
        "n": int(n),
    }
    if seed is not None:
        params["seed"] = int(seed)

    resp = client.chat.completions.create(**params)

    outputs = []
    for ch in resp.choices:
        content = ch.message.content
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    data = json.loads(content[start:end+1])
                except Exception:
                    data = {"_raw": content}
            else:
                data = {"_raw": content}
        outputs.append(data)
    return outputs

# ---------- NEW: robust Excel loader + preview ----------
def load_excel_sheets(file_buffer: BytesIO, filename: str) -> dict:
    """
    Return dict[str, DataFrame] for all sheets.
    - .xlsx/.xlsm: openpyxl
    - .xls: xlrd (if installed); otherwise raises a helpful error.
    """
    ext = os.path.splitext(filename)[1].lower()
    try:
        if ext in [".xlsx", ".xlsm"]:
            return pd.read_excel(file_buffer, sheet_name=None, engine="openpyxl")
        elif ext == ".xls":
            # xlrd >= 2.0 dropped .xls support; require 1.2.0
            try:
                return pd.read_excel(file_buffer, sheet_name=None, engine="xlrd")
            except Exception as e:
                raise RuntimeError(
                    "Reading .xls requires xlrd==1.2.0. Install it with: pip install 'xlrd==1.2.0'"
                ) from e
        else:
            raise RuntimeError(f"Unsupported file extension: {ext}")
    except Exception as e:
        raise

# ---- UI ----
st.set_page_config(page_title="Ring Copy Generator (Excel + PUID)", page_icon="🛎️", layout="wide")
st.title("🛎️ Ring Copy Generator")
st.caption("Upload your Excel template, preview sheets, select a Product Unique Identifier, and generate JSON outputs that respect brand + template context.")

with st.sidebar:
    st.subheader("⚙️ Configuration")
    api_key = st.text_input("OpenAI API Key", type="password", value=os.getenv("OPENAI_API_KEY", ""))
    model = st.selectbox(
        "OpenAI model",
        options=[DEFAULT_MODEL, "gpt-4o-2024-08-06", "gpt-4.1-mini", "gpt-4.1"],
        index=0
    )
    PDF_CONTEXT_CHARS = st.slider("Context char cap", 2000, 30000, PDF_CONTEXT_CHARS_DEFAULT, 500)
    num_variations = st.number_input("Number of variations", min_value=1, max_value=MAX_VARIATIONS, value=3, step=1)
    seed = st.number_input("Seed (optional, for reproducibility)", min_value=0, max_value=2**31-1, value=0, step=1)
    use_seed = st.checkbox("Use seed", value=False)
    preview_rows = st.slider("Preview rows per sheet (display)", 5, 500, 100, 5)

st.markdown("### 1) Upload Excel Template")
uploaded = st.file_uploader("Excel file (.xlsx / .xls / .xlsm)", type=["xlsx", "xls", "xlsm"])
xls = None
if uploaded is not None:
    try:
        # IMPORTANT: use a BytesIO copy so we can re-read later if needed
        xls = load_excel_sheets(BytesIO(uploaded.read()), uploaded.name)
        st.success(f"Loaded {len(xls)} sheet(s) from **{uploaded.name}**.")
    except Exception as e:
        st.error(f"Failed to read Excel: {e}")

# ---------- NEW: Display Excel contents to the user ----------
if xls:
    st.markdown("### 2) Preview Excel Sheets")
    sheet_names = list(xls.keys())

    # Tabbed preview for all sheets
    tabs = st.tabs(sheet_names)
    for tab, name in zip(tabs, sheet_names):
        with tab:
            df = xls[name]
            st.write(f"**{name}** — shape: {df.shape[0]} rows × {df.shape[1]} columns")
            if df.shape[0] > preview_rows:
                st.info(f"Showing first {preview_rows} rows (use the sidebar to change).")
                st.dataframe(df.head(preview_rows))
            else:
                st.dataframe(df)

    # Continue with your existing workflow
    st.markdown("### 3) Choose Content Sheet and ID Column")
    content_sheet = st.selectbox("Content sheet", options=sheet_names, index=0)
    df_content = xls[content_sheet].copy()

    display_cols = [str(c) for c in df_content.columns]
    id_col_guess = None
    for guess in ["Product Unique Identifier", "Product_Unique_Identifier", "PUID", "SKU", "ID"]:
        if guess in display_cols:
            id_col_guess = guess
            break
    if id_col_guess is None and len(display_cols) > 0:
        id_col_guess = display_cols[0]

    id_col = st.selectbox("Identifier column", options=display_cols,
                          index=display_cols.index(id_col_guess) if id_col_guess in display_cols else 0)
    product_id_value = st.text_input("Product Unique Identifier (exact match)")

    st.markdown("### 4) Brand Guidelines & Approved Template")
    auto_guidelines, auto_template = try_autodetect_long_text(xls)
    colA, colB = st.columns(2)
    with colA:
        ring_brand_guidelines = st.text_area(
            "Ring Brand Guidelines (auto-detected / paste here)",
            value=auto_guidelines,
            height=200,
            placeholder="Paste brand guidelines text if not auto-detected"
        )
    with colB:
        approved_copy_template = st.text_area(
            "Approved Copy Template (auto-detected / paste here)",
            value=auto_template,
            height=200,
            placeholder="Paste approved copy template text if not auto-detected"
        )

    st.markdown("### 5) Additional Context")
    user_context = st.text_area("Optional context to pass through", placeholder="Anything else to consider...")

    st.markdown("### 6) Generate")
    go = st.button("Generate JSON outputs")

    if go:
        if not api_key:
            st.error("Please enter your OpenAI API key in the sidebar.")
        elif not product_id_value:
            st.error("Please provide the Product Unique Identifier.")
        else:
            # Find the matching row(s)
            matches = df_content[df_content[id_col].astype(str) == str(product_id_value)]
            if matches.empty:
                st.warning(f"No rows found where `{id_col}` == {product_id_value}.")
            else:
                if len(matches) > 1:
                    st.info(f"Found {len(matches)} matching rows. Using the first one.")
                row = matches.iloc[0]
                content_data = row_to_content_data(row)

                # Build system prompt
                system_prompt = build_system_prompt(
                    ring_brand_guidelines=ring_brand_guidelines,
                    approved_copy_template=approved_copy_template,
                    content_data=content_data,
                    user_context=user_context,
                    PDF_CONTEXT_CHARS=PDF_CONTEXT_CHARS
                )

                # Call OpenAI
                with st.spinner("Generating..."):
                    try:
                        client = get_openai_client(api_key=api_key)
                        outputs = call_openai(
                            client=client,
                            model=model,
                            system_prompt=system_prompt,
                            n=int(num_variations),
                            seed=int(seed) if use_seed else None
                        )
                    except Exception as e:
                        st.error(f"OpenAI error: {e}")
                        outputs = []

                if outputs:
                    normed = [{
                        "Content_Title": coerce_str(o.get("Content_Title", "")),
                        "Content_Body": coerce_str(o.get("Content_Body", "")),
                        "Headline_Variants": coerce_str(o.get("Headline_Variants", "")),
                        "Keywords_Primary": coerce_str(o.get("Keywords_Primary", "")),
                        "Keywords_Secondary": coerce_str(o.get("Keywords_Secondary", "")),
                    } for o in outputs]

                    st.success(f"Generated {len(normed)} JSON object(s).")
                    for idx, item in enumerate(normed, start=1):
                        with st.expander(f"Variation {idx}", expanded=(len(normed) == 1)):
                            st.json(item)

                    # Table + downloads
                    df_out = pd.DataFrame(normed)
                    st.markdown("#### Download")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.download_button(
                            "Download CSV",
                            data=df_out.to_csv(index=False).encode("utf-8"),
                            file_name=f"ring_copy_{product_id_value}.csv",
                            mime="text/csv"
                        )
                    with col2:
                        st.download_button(
                            "Download JSON Lines",
                            data="\n".join(json.dumps(o, ensure_ascii=False) for o in normed).encode("utf-8"),
                            file_name=f"ring_copy_{product_id_value}.jsonl",
                            mime="application/json"
                        )
                    with col3:
                        st.download_button(
                            "Download Single JSON (array)",
                            data=json.dumps(normed, ensure_ascii=False, indent=2).encode("utf-8"),
                            file_name=f"ring_copy_{product_id_value}.json",
                            mime="application/json"
                        )

                    st.caption("Tip: 'Headline_Variants' is pipe-delimited (variant1|variant2|variant3). Parse it into a list if needed.")
