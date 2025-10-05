# app.py
# Streamlit app: Generate Ring copy (TEXT variations) from an Excel template + Product Unique Identifier dropdown
# Deps: streamlit, pandas, openpyxl, (optional) xlrd==1.2.0 for .xls, python-dotenv, openai, requests
# Optional for PDF text fallback: PyPDF2
import base64

import os
import json
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from io import BytesIO
from typing import Optional, List, Dict
from perplexity import Perplexity
import boto3
# ---- Load .env (optional) ----
load_dotenv()
perplexity_api_key=os.getenv("PERPLEXITY_API_KEY")
client = Perplexity(api_key=perplexity_api_key)

# ---- Constants ----
DEFAULT_PROVIDER = "OpenAI"      # "OpenAI" | "Perplexity"
OPENAI_DEFAULT_MODEL = "gpt-5"   # works with Responses + Chat Completions
PERPLEXITY_DEFAULT_MODEL = "sonar-pro"  # Perplexity chat-completions
AMAZON_CLAUDE_DEFAULT_MODEL = "Claude Sonnet 4"
PDF_CONTEXT_CHARS_DEFAULT = 16000
NUM_VARIATIONS = 3

# Default Excel path fallback
DEFAULT_EXCEL_PATH = "Ring_Copy_Solution_Enhanced_with_Clownfish_Jellyfish_and_Needlefish.xlsx"

# --- PDF attachment settings (OpenAI only) ---
PDF_FILENAME = "Ring Copy Guidelines International 2025.pdf"   # expected local file
ENABLE_PDF_ATTACHMENT = True     # try attaching via Files + Responses API (OpenAI only)
ENABLE_PDF_TEXT_FALLBACK = True  # if file upload fails, optionally inline text (requires PyPDF2)

# ---------------- Helpers ----------------
LOGO_CANDIDATES = ["image (1).png"]

def get_logo_path() -> Optional[str]:
    for p in LOGO_CANDIDATES:
        try:
            if os.path.exists(p):
                return p
        except Exception:
            pass
    return None

def do_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    else:
        st.session_state["_force_refresh"] = st.session_state.get("_force_refresh", 0) + 1

def notify(msg: str, icon: Optional[str] = None):
    if hasattr(st, "toast"):
        st.toast(msg, icon=icon)
    else:
        st.info(msg)

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

def workbook_excerpt_for_llm(xls: dict, rows_per_sheet: int = 50, char_limit: int = PDF_CONTEXT_CHARS_DEFAULT) -> dict:
    if not isinstance(xls, dict) or not xls:
        return {"_workbook_excerpt": ""}
    summary = {}
    for sheet_name, df in xls.items():
        try:
            if isinstance(df, pd.DataFrame) and not df.empty:
                summary[sheet_name] = df.astype(str).head(rows_per_sheet).to_dict(orient="records")
        except Exception:
            continue
    text = json.dumps(summary, ensure_ascii=False)
    if len(text) > char_limit:
        text = text[:char_limit]
    return {"_workbook_excerpt": text}

# ---------- Expected fields per variant ----------
VARIANT_FIELDS: Dict[str, List[str]] = {
    "ring": ["Content_Title", "Content_Body", "Headline_Variants", "Keywords_Primary", "Keywords_Secondary", "Description"],
    "social": ["Hashtags", "Engagement_Hook", "Value_Prop", "Address_Concerns", "Content"],
    "email": ["Subject_Line", "Greeting", "Main_Content", "Reference"],
    "audience": ["Easy_Installation_Self_Setup", "Technical_Features_and_Control", "Technical_Specifications", "Security_Benefits_Messaging"],
}

# ---------- Per-mode default Authoring Context ----------
DEFAULT_CONTEXT: Dict[str, Dict[str, str]] = {
    "ring": {
        "base_prompt": "Write clear, benefit-led Ring product copy with a confident, friendly tone. Lead with the problem Ring solves, highlight security and convenience, and include a crisp CTA.",
        "additional_context": "Prioritise clarity, brevity, and trust. Mention app control, real-time alerts, and easy setup. Avoid jargon unless it adds credibility.",
        "guardrails": "No false claims. No sensitive or fear-based messaging. Keep reading level ~Grade 7–9. Avoid overuse of exclamation and ALL CAPS.",
    },
    "social": {
        "base_prompt": "Craft a scannable, thumb-stopping post with a 1-line hook, value, and CTA.",
        "additional_context": "Use crisp sentences and native conventions. Add 3–6 relevant hashtags. Focus on use-cases: missed deliveries, peace of mind, easy install.",
        "guardrails": "No spammy phrasing or clickbait. Respect platform tone. Keep under 100–140 words.",
    },
    "email": {
        "base_prompt": "Write a concise marketing email: clear subject (≤60 chars), friendly greeting, benefit-first body (100–150 words), and a single primary CTA.",
        "additional_context": "Highlight real-time motion alerts, easy installation, and app control. Use short paragraphs and skimmable structure.",
        "guardrails": "Avoid spam-trigger words, all caps, and excessive punctuation. Keep brand voice consistent and trustworthy.",
    },
    "audience": {
        "base_prompt": "Adapt messaging by audience: emphasise easy self-setup, control via app, and strong privacy/security framing.",
        "additional_context": "Include concrete technical specs only when useful (resolution, field of view, connectivity). Stress practical security benefits.",
        "guardrails": "No unrealistic claims or fearmongering. Keep tone reassuring and practical. Use plain language for non-technical readers.",
    },
}

# ---------- System prompt builders ----------
def build_output_requirements_json(variant: str) -> str:
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
        return ("You are a senior copywriter for Ring. Use the brand guidelines and the approved template patterns as non-negotiable constraints. "
                "Write copy that is channel-appropriate, concise, and strictly consistent with Ring's voice.")
    if variant == "social":
        return ("You are a Social Media Content Creator for Ring. Craft platform-native, scroll-stopping copy with clear hooks and CTAs while honouring Ring's brand voice. "
                "Optimise for engagement (thumb-stopping first line, brevity, scannability, hashtags where relevant).")
    if variant == "email":
        return ("You are an Email Campaign Generator for Ring. Create persuasive email copy with a compelling subject line, preview snippet feel, and clear CTA hierarchy. "
                "Maintain brand voice, avoid spammy wording, and keep body copy crisp and conversion-focused.")
    if variant == "audience":
        return ("You are an Audience Adaptation campaign specialist for Ring. Develop messaging that emphasises easy installation and self-setup, highlights technical features and control, "
                "includes technical specifications, and maintains strong security benefits messaging.")
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
    user_feedback: str = "",
    pdf_text_excerpt: str = "",
) -> str:
    ring_brand_guidelines = (ring_brand_guidelines or "")[:PDF_CONTEXT_CHARS]
    approved_copy_template = (approved_copy_template or "")[:PDF_CONTEXT_CHARS]
    feedback_block = f"\nUSER FEEDBACK (must be reflected in output):\n{user_feedback}\n" if user_feedback else ""
    pdf_block = f"\nADDITIONAL CONTEXT (from attached PDF excerpt):\n{pdf_text_excerpt}\n" if pdf_text_excerpt else ""
    system_prompt = (
        f"{build_variant_opening(variant)}\n\n"
        f"BRAND GUIDELINES:\n{ring_brand_guidelines}\n\n"
        f"APPROVED TEMPLATE PATTERNS:\n{approved_copy_template}\n\n"
        "CONTENT CLASSIFICATION (from the Excel row or workbook excerpt):\n"
        f"{content_data}\n"
        f"{feedback_block}"
        "AUTHORING CONTEXT:\n"
        f"- Base Prompt: {base_prompt}\n"
        f"- Additional Context: {additional_context}\n"
        f"- Guardrails: {guardrails}\n"
        f"{pdf_block}\n"
        f"{build_output_requirements_json(variant)}\n\n"
        "LANGUAGE REQUIREMENT: Use UK English spelling, grammar, and phrasing consistently "
        "(e.g., 'organisation' not 'organization', 'colour' not 'color', 'optimise' not 'optimize')."
    )
    return system_prompt

def get_openai_client(api_key: str = None):
    from openai import OpenAI
    return OpenAI(api_key=api_key) if api_key else OpenAI()

# ---------- PDF attach + fallback (OpenAI only) ----------
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
        import PyPDF2  # optional
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

# ---------- Core generation: OpenAI ----------
def get_enhanced_openai_response(
    client,
    prompt: str,
    expected_fields: List[str],
    model: str,
    n: int = 1,
    pdf_file_id: Optional[str] = None
):
    results = []
    try:
        if pdf_file_id:
            # Responses API with file input
            for _ in range(n):
                resp = client.responses.create(
                    model=model,
                    instructions=prompt,
                    input=[{
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "Generate the copy now following all requirements exactly. Return JSON only."},
                            {"type": "input_file", "file_id": pdf_file_id}
                        ]
                    }],
                    # You can also add: response_format={"type": "json_object"}
                )
                content_text = resp.output_text
                try:
                    parsed = json.loads(content_text)
                    if all(field in parsed for field in expected_fields):
                        results.append(parsed)
                    else:
                        results.append({"error": "Missing fields", "raw": content_text})
                except json.JSONDecodeError:
                    results.append({"error": "Invalid JSON", "raw": content_text})
            return results

        # Chat Completions fallback (no file input)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Generate the copy now following all requirements exactly. Return JSON only."}
            ],
            response_format={"type": "json_object"},
            n=n,
            max_tokens=8000  # FIXED: was max_completion_tokens
        )
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

with open("Ring Copy Guidelines International 2025.pdf", "rb") as file:
    file_data = file.read()
    encoded_file = base64.b64encode(file_data).decode('utf-8')


# ---------- Core generation: Perplexity ----------
def get_enhanced_perplexity_response(
    prompt: str,
    expected_fields: List[str],
    n: int = 1
):
    """Perplexity chat.completions; no file inputs supported here."""
   
    print(f"using perplexity model")
    base_messages =[
        {"role": "system", "content": [{"type":"text","text":f"{prompt}\n\n Do NOT wrap the output in markdown or code fences (no \`\`\`json, no backticks, no quotes before/after).Start with {{ and end with }}."}]},

        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Generate the copy now following all requirements exactly. Return JSON only"
                },
                {
                    "type": "file_url",
                    "file_url": {
                        "url": encoded_file,  # Just the base64 string, no prefix
                        "file_name": "Ring Copy Guidelines International 2025.pdf"
                    }
                }
            ]
        }
    ]
    results = []
    for _ in range(max(1, n)):
        try:
            completion = client.chat.completions.create(
                model = "sonar-pro",
                messages = base_messages
            )
            content = completion.choices[0].message.content
            try:
                parsed = json.loads(content)
                if all(field in parsed for field in expected_fields):
                    results.append(parsed)
                else:
                    results.append({"error": "Missing fields", "raw": content})
            except json.JSONDecodeError:
                results.append({"error": "Invalid JSON", "raw": content})
        except Exception as e:
            results.append({"error": str(e)})
    return results

def get_enhanced_openai_response(
    client,
    prompt: str,
    expected_fields: List[str],
    model: str,
    n: int = 1,
    pdf_file_id: Optional[str] = None
):
    print(f"calling openai model")
    results = []
    try:
        if pdf_file_id:
            # Responses API with file input
            for _ in range(n):
                resp = client.responses.create(
                    model=model,
                    instructions=prompt,
                    input=[{
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "Generate the copy now following all requirements exactly. Return JSON only."},
                            {"type": "input_file", "file_id": pdf_file_id}
                        ]
                    }],
                    # You can also add: response_format={"type": "json_object"}
                )
                content_text = resp.output_text
                try:
                    parsed = json.loads(content_text)
                    if all(field in parsed for field in expected_fields):
                        results.append(parsed)
                    else:
                        results.append({"error": "Missing fields", "raw": content_text})
                except json.JSONDecodeError:
                    results.append({"error": "Invalid JSON", "raw": content_text})
            return results

        # Chat Completions fallback (no file input)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Generate the copy now following all requirements exactly. Return JSON only."}
            ],
            response_format={"type": "json_object"},
            n=n,
            max_tokens=8000  # FIXED: was max_completion_tokens
        )
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

with open("Ring Copy Guidelines International 2025.pdf", "rb") as file:
    file_data = file.read()
    encoded_file = base64.b64encode(file_data).decode('utf-8')


# ---------- Core generation: Perplexity ----------
def get_enhanced_amazon_response(
    prompt: str,
    expected_fields: List[str],
    n: int = 1
):
    """Perplexity chat.completions; no file inputs supported here."""
   
    print(f"calling Amazon model ")
    
    with open("Ring Copy Guidelines International 2025.pdf", "rb") as f:
        pdf_bytes = f.read()
   
    system=[{"text":f"{prompt}\n\n Do NOT wrap the output in markdown or code fences (no \`\`\`json, no backticks, no quotes before/after).Start with {{ and end with }}."}]
    message = [ 
               {
                   "role": "user",
                    "content": [
                            {   
                             "document":{"format":"pdf", "name":"Ring Copy Guidelines International 2025", "source":{"bytes":pdf_bytes}}
                            },
                            {
                                "text": "Generate the copy now following all requirements exactly. Return JSON only"
                            } 
                        ]
                    }
               ]

    results = []
    for _ in range(max(1, n)):
        try:
            bedrock_client = boto3.client(service_name="bedrock-runtime", region_name="us-east-1")
            response = bedrock_client.converse(modelId="us.anthropic.claude-sonnet-4-20250514-v1:0",messages=message,system=system)

            output = response["output"]["message"]["content"]        
            content = output[0].get("text", {})
            try:
                parsed = json.loads(content)
                if all(field in parsed for field in expected_fields):
                    results.append(parsed)
                else:
                    results.append({"error": "Missing fields", "raw": content})
            except json.JSONDecodeError:
                results.append({"error": "Invalid JSON", "raw": content})
        except Exception as e:
            results.append({"error": str(e)})
    return results

# ---------- Unified switch ----------
def get_enhanced_response(
    provider: str,
    openai_client,  # may be None for Perplexity
    prompt: str,
    expected_fields: List[str],
    model: str,
    n: int = 1,
    pdf_file_id: Optional[str] = None
):
    if provider == "Perplexity":
        # Perplexity does not support file attach in this flow; ignore pdf_file_id
        return get_enhanced_perplexity_response(
            prompt=prompt,
            expected_fields=expected_fields,
            n=n
        )
     
    elif provider == "Amazon Claude":
        return get_enhanced_amazon_response(
            prompt=prompt,
            expected_fields=expected_fields,
            n=n
        )    
    # OpenAI
    return get_enhanced_openai_response(
        client=openai_client,
        prompt=prompt,
        expected_fields=expected_fields,
        model=model,
        n=n,
        pdf_file_id=pdf_file_id
    )

def total_chars_for_result(result: dict, fields: Optional[List[str]] = None) -> int:
    """
    Sum character lengths of selected JSON fields for a given variation.
    Falls back to all str/int/float values if fields is None.
    """
    if not isinstance(result, dict):
        return 0
    if fields:
        return sum(len(coerce_str(result.get(f, ""))) for f in fields)
    # fallback: count over string-like values
    return sum(len(coerce_str(v)) for v in result.values() if isinstance(v, (str, int, float)))

def get_pdf_b64_from_bytes(pdf_bytes: Optional[bytes]) -> str:
    return base64.b64encode(pdf_bytes).decode("utf-8") if pdf_bytes else ""

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
icon = next((p for p in LOGO_CANDIDATES if os.path.exists(p)), "")
st.set_page_config(page_title="Ring CopyForge", page_icon=icon, layout="wide")

# ---- Session state ----
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

# feedback state (TEXT ONLY)
ss.setdefault("feedback_text", "")

# last-run state
ss.setdefault("last_results", None)
ss.setdefault("last_variant", None)
ss.setdefault("last_prompt", None)
ss.setdefault("last_expected_fields", None)
ss.setdefault("last_pdf_file_id", None)
ss.setdefault("last_pdf_excerpt", "")

# Pre-load defaults for all modes
for _mode, ctx in DEFAULT_CONTEXT.items():
    ss.setdefault(f"ctx_{_mode}_base", ctx["base_prompt"])
    ss.setdefault(f"ctx_{_mode}_extra", ctx["additional_context"])
    ss.setdefault(f"ctx_{_mode}_guard", ctx["guardrails"])

# ---------- AUTO-LOAD ----------
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

# ====================== SIDEBAR ======================
with st.sidebar:
    st.header("📁 Source & Controls")

    # Provider + Model selectors
    ss.provider = st.selectbox("Provider", [ "Amazon Claude", "OpenAI", "Perplexity"])
    if ss.provider == "OpenAI":
        openai_models = "gpt-5"
        ss.model_openai = st.text(f"Model Using : {openai_models}")
    
    elif ss.provider == "Amazon Claude":
        amazon_claude_model = "Claude Sonnet 4"
        ss.model_amazon_claude = st.text(f"Model Using : {amazon_claude_model}")
        
    else:
        perplexity_models = "sonar-pro"
        ss.model_perplexity = st.text(f"Model Using : {perplexity_models}")
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

    # PDF attach line (note: Perplexity path won't use it)
    st.text("Attached Ring Copy Guidelines International 2025.pdf")

# ====================== MAIN ======================

logo_path = get_logo_path()
if logo_path:
    st.image(logo_path, width=200)

st.title("Ring CopyForge")
st.caption("Upload your Excel in the sidebar, pick a Product Unique Identifier (optionally via Advanced), choose a prompt mode, tweak the authoring context, select provider/model, and then generate.")

# Preview
if ss.preview_visible and ss.first_df is not None:
    st.markdown("### 👀 Preview (First Sheet Only)")
    preview_rows = st.slider("Rows to show", 5, 500, 50, 5, key="preview_rows_first")
    st.write(f"**{ss.first_sheet_name}** — {ss.first_df.shape[0]} rows × {ss.first_df.shape[1]} columns")
    st.dataframe(ss.first_df.head(preview_rows) if ss.first_df.shape[0] > preview_rows else ss.first_df, use_container_width=True)
elif not ss.file_loaded:
    st.info("Use the **sidebar** to upload/select a file and click **Show** to preview.")
else:
    st.info("Preview is hidden. Click **Show** in the sidebar to display the Excel preview.")

# ---------- Advanced: PUI ----------
st.markdown("### ⚙️ Advanced")
with st.expander("Advanced options", expanded=False):
    st.caption("Optionally target a specific row by Product Unique Identifier. If disabled, the entire Excel workbook will be sent as context to the model.")
    ss.use_specific_pui = st.checkbox(
        "Select a specific Product Unique Identifier",
        value=ss.use_specific_pui,
        help="Enable to specify a column and value; otherwise the LLM sees a compact excerpt of the entire workbook."
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
                    .apply(coerce_str).apply(lambda s: s.strip()).replace("", pd.NA).dropna().unique().tolist()
                )
                st.selectbox("Value", sorted(id_vals, key=lambda x: (x.lower(), x)) if id_vals else [], key="id_val", disabled=not ss.file_loaded)
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

def prompt_button(label: str, key_mode: str, container):
    with container:
        is_selected = (ss.selected_variant == key_mode)
        clicked = st.button(label, key=f"btn_{key_mode}", type=("primary" if is_selected else "secondary"), use_container_width=True)
        if clicked:
            ss[f"ctx_{key_mode}_base"]  = DEFAULT_CONTEXT[key_mode]["base_prompt"]
            ss[f"ctx_{key_mode}_extra"] = DEFAULT_CONTEXT[key_mode]["additional_context"]
            ss[f"ctx_{key_mode}_guard"] = DEFAULT_CONTEXT[key_mode]["guardrails"]
            ss.selected_variant = key_mode
            do_rerun()

prompt_button("Ring Copywriter", "ring", c1)
prompt_button("Social Media", "social", c2)
prompt_button("Email Campaign", "email", c3)
prompt_button("Audience Adaptation", "audience", c4)

label_map = {"ring": "Ring Copywriter", "social": "Social Media", "email": "Email Campaign", "audience": "Audience Adaptation"}
st.caption(f"Selected Mode: **{label_map.get(ss.selected_variant, 'None')}**")

# ---------- Authoring context ----------
st.markdown("### ✍️ Authoring Context")
active_mode = ss.selected_variant or "ring"
base_key  = f"ctx_{active_mode}_base"
extra_key = f"ctx_{active_mode}_extra"
guard_key = f"ctx_{active_mode}_guard"

st.text_area("Base Prompt", key=base_key, height=110)
st.text_area("Additional Context", key=extra_key, height=110)
st.text_area("Guardrails", key=guard_key, height=110)

# ---------- Generate button (top) ----------
go = st.button("Generate Variations", use_container_width=True)

def run_generation(user_feedback: str = ""):
    provider = ss.provider
    model = ss.model_amazon_claude 
    if provider =="OpenAi":
        model=ss.model_openai
    elif provider == "Perplexity":
        model = ss.model_perplexity    
    print(f"provider is {provider} and model {model}")
    # API key checks
    if provider == "OpenAI":
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            st.error("Missing OPENAI_API_KEY.")
            return
        client = get_openai_client(api_key)
    else:
        if not os.getenv("PERPLEXITY_API_KEY", ""):
            st.error("Missing PERPLEXITY_API_KEY.")
            return
        client = None  # not used for Perplexity

    if not (ss.file_loaded and ss.first_df is not None and ss.xls is not None):
        st.error("Use the **sidebar**: upload or use default, then click **Show** at least once to load the file.")
        return
    if not ss.selected_variant:
        st.error("Please choose a Prompt Mode above before generating.")
        return

    base_prompt = ss.get(base_key, DEFAULT_CONTEXT[active_mode]["base_prompt"])
    additional_context = ss.get(extra_key, DEFAULT_CONTEXT[active_mode]["additional_context"])
    guardrails = ss.get(guard_key, DEFAULT_CONTEXT[active_mode]["guardrails"])

    auto_guidelines, auto_template = try_autodetect_long_text(ss.xls)

    # OpenAI-only PDF attach/fallback (skipped for Perplexity)
    pdf_file_id = None
    pdf_excerpt = ""
    if provider == "OpenAI":
        if ENABLE_PDF_ATTACHMENT:
            pdf_file_id = upload_pdf_and_get_file_id(client, PDF_FILENAME)
        if not pdf_file_id and ENABLE_PDF_TEXT_FALLBACK:
            pdf_excerpt = extract_pdf_text_fallback(PDF_FILENAME, max_chars=8000)

    # Build content data
    if ss.use_specific_pui:
        selected_col = st.session_state.get("id_col")
        selected_val = st.session_state.get("id_val")
        if not selected_col or not selected_val:
            st.error("Advanced mode is enabled. Please select both a Product Unique Identifier column and value.")
            return
        mask = ss.first_df[selected_col].apply(coerce_str).str.strip() == coerce_str(selected_val).strip()
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
        pdf_text_excerpt=(pdf_excerpt if provider == "OpenAI" else "")
    )

    with st.spinner(f"Generating with {provider}"):
        results = get_enhanced_response(
            provider=provider,
            openai_client=client,
            prompt=system_prompt,
            expected_fields=VARIANT_FIELDS[ss.selected_variant],
            model=model,
            n=NUM_VARIATIONS,
            pdf_file_id=(pdf_file_id if provider == "OpenAI" else None)
        )

    st.success(f"{label_map[ss.selected_variant]}: Generated {len(results)} variation(s) via {provider}")

    # Save last run state
    ss.last_results = results
    ss.last_variant = ss.selected_variant
    ss.last_prompt = system_prompt
    ss.last_expected_fields = VARIANT_FIELDS[ss.selected_variant]
    ss.last_pdf_file_id = (pdf_file_id if provider == "OpenAI" else None)
    ss.last_pdf_excerpt = (pdf_excerpt if provider == "OpenAI" else "")

    # Render results
    for i, result in enumerate(results, 1):
        if 'error' in result:
            st.error(f"{label_map[ss.selected_variant]} — Variation {i}: {result['error']}")
            if 'raw' in result:
                with st.expander(f"{label_map[ss.selected_variant]} — Raw {i}"):
                    st.code(result['raw'])
            continue

        if ss.selected_variant == "ring":
            with st.expander(f"{label_map[ss.selected_variant]} — 📝 Variation {i}", expanded=(i == 1)):
                char_count = total_chars_for_result(result, ss.last_expected_fields)

                st.text_area("Title", result.get("Content_Title", ""), key=f"{ss.selected_variant}_title_{i}")
                st.text_area("Body", result.get("Content_Body", ""), key=f"{ss.selected_variant}_body_{i}")
                st.text_input("Headlines (pipe-separated)", result.get("Headline_Variants", ""), key=f"{ss.selected_variant}_head_{i}")
                cA, cB = st.columns(2)
                with cA:
                    st.text_input("Primary Keywords", result.get("Keywords_Primary", ""), key=f"{ss.selected_variant}_kw1_{i}")
                with cB:
                    st.text_input("Secondary Keywords", result.get("Keywords_Secondary", ""), key=f"{ss.selected_variant}_kw2_{i}")
                st.text_area("Description", result.get("Description", ""), key=f"{ss.selected_variant}_desc_{i}")
                st.text(f"Total charaters count : {char_count}")
        elif ss.selected_variant == "social":
            with st.expander(f"{label_map[ss.selected_variant]} — 📣 Variation {i}", expanded=(i == 1)):
                char_count = total_chars_for_result(result, ss.last_expected_fields)

                st.text_area("Hashtags", result.get("Hashtags", ""), key=f"{ss.selected_variant}_hashtags_{i}")
                st.text_area("Engagement Hook", result.get("Engagement_Hook", ""), key=f"{ss.selected_variant}_hook_{i}")
                st.text_area("Clear Value Proposition", result.get("Value_Prop", ""), key=f"{ss.selected_variant}_vp_{i}")
                st.text_area("Address Missed Deliveries & Absence Concerns", result.get("Address_Concerns", ""), key=f"{ss.selected_variant}_concerns_{i}")
                st.text_area("Content", result.get("Content", ""), key=f"{ss.selected_variant}_content_{i}")
                st.text(f"Total charaters count : {char_count}")
        elif ss.selected_variant == "email":
            with st.expander(f"{label_map[ss.selected_variant]} — ✉️ Variation {i}", expanded=(i == 1)):
                char_count = total_chars_for_result(result, ss.last_expected_fields)

                st.text_input("Subject Line", result.get("Subject_Line", ""), key=f"{ss.selected_variant}_subj_{i}")
                st.text_input("Greeting", result.get("Greeting", ""), key=f"{ss.selected_variant}_greet_{i}")
                st.text_area("Main Content (100-150 words)", result.get("Main_Content", ""), key=f"{ss.selected_variant}_main_{i}")
                st.text_input("Reference", result.get("Reference", ""), key=f"{ss.selected_variant}_ref_{i}")
                st.text(f"Total charaters count : {char_count}")
        elif ss.selected_variant == "audience":
            with st.expander(f"{label_map[ss.selected_variant]} — 🧩 Variation {i}", expanded=(i == 1)):
                char_count = total_chars_for_result(result, ss.last_expected_fields)

                st.text_area("Emphasise easy installation & self-setup", result.get("Easy_Installation_Self_Setup", ""), key=f"{ss.selected_variant}_install_{i}")
                st.text_area("Highlight technical features & control", result.get("Technical_Features_and_Control", ""), key=f"{ss.selected_variant}_features_{i}")
                st.text_area("Include technical specifications", result.get("Technical_Specifications", ""), key=f"{ss.selected_variant}_specs_{i}")
                st.text_area("Maintain security benefits messaging", result.get("Security_Benefits_Messaging", ""), key=f"{ss.selected_variant}_security_{i}")
                st.text(f"Total charaters count : {char_count}")
# Trigger initial generation
if go:
    run_generation(user_feedback="")  # first pass, no feedback

# ---------- FEEDBACK (text only) & REGENERATE (after results) ----------
if ss.last_results is not None:
    st.markdown("### 🗣️ Feedback")
    st.caption("Provide specific, text-only feedback (tone, length, messaging priorities, compliance notes, headlines constraints, etc.). Then click **Regenerate with feedback**.")
    ss.feedback_text = st.text_area("Feedback for the next run", value=ss.feedback_text, height=120, placeholder="Example: Shorter body, emphasise privacy, headlines under 6 words, no exclamation marks.")

    if st.button("Regenerate with feedback", use_container_width=True):
        fb = (ss.feedback_text or "").strip()
        run_generation(user_feedback=fb)

# ====================== FOOTER DISCLAIMER ======================
st.markdown("---")
st.warning(
    "DISCLAIMER: All generated copy should be reviewed and approved by one of our "
    "in-house copywriters and, where applicable, legal counsel before publication or use. "
    "This content is provided as a starting point and may require modifications to ensure "
    "accuracy, compliance with relevant regulations, and alignment with our brand voice."
)
