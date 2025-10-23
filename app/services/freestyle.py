# app/services/freestyle.py
from __future__ import annotations
from typing import Optional

# --- OpenAI ---
from app.providers.openai_provider import get_openai_client  # :contentReference[oaicite:0]{index=0}

# --- Bedrock / Claude ---
# Uses boto3 directly (Bedrock Converse) inside this helper.
import boto3  # :contentReference[oaicite:1]{index=1}

# --- Perplexity ---
from perplexity import Perplexity  # :contentReference[oaicite:2]{index=2}
from app.config import PERPLEXITY_API_KEY

def _compose_user_message(task: str, template_excerpt: str, pdf_excerpt: str) -> str:
    blocks = []
    if task.strip():
        blocks.append(f"[TASK]\n{task.strip()}")
    if template_excerpt.strip():
        blocks.append(f"[TEMPLATE EXCERPT]\n{template_excerpt.strip()}")
    if pdf_excerpt.strip():
        blocks.append(f"[GUIDELINES EXCERPT]\n{pdf_excerpt.strip()}")
    return "\n\n".join(blocks) or "No additional context provided."

def freestyle_generate_text(
    provider: str,
    model: str,
    system_prompt,
    user_task,
    template_excerpt: str = "",
    pdf_excerpt: str = "",
) -> str:
    """
    Provider-agnostic text generation for the Free Style tab.
    Returns plain text; robust against Streamlit session values being non-str.
    """
    provider = (str(provider) if provider is not None else "OpenAI").strip()
    system_prompt = str(system_prompt or "")
    user_task = str(user_task or "")
    template_excerpt = str(template_excerpt or "")
    pdf_excerpt = str(pdf_excerpt or "")

    user_msg = _compose_user_message(user_task, template_excerpt, pdf_excerpt)

    if provider == "OpenAI":
        client = get_openai_client()
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt or "You are a helpful writing assistant."},
                {"role": "user", "content": user_msg},
            ],
        )
        return resp.choices[0].message.content or ""

    if provider == "Amazon Claude" or provider.lower().startswith("amazon"):
        br = boto3.client("bedrock-runtime", region_name="us-east-1")
        if not system_prompt:
            system_prompt = "You are a helpful writing assistant"
        resp = br.converse(
            modelId="us.anthropic.claude-sonnet-4-20250514-v1:0",
            system=[{"text": f"{system_prompt} .. Generate response in UK English" }],
            messages=[{"role": "user", "content": [{"text": user_msg}]}],
        )
        return resp["output"]["message"]["content"][0]["text"]

    if provider == "Perplexity":
        client = Perplexity(api_key=PERPLEXITY_API_KEY)
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": [{"type": "text", "text": system_prompt or "You are a helpful writing assistant."}]},
                {"role": "user", "content": [{"type": "text", "text": user_msg}]},
            ],
            temperature=0.7,
        )
        return completion.choices[0].message.content or ""

    raise ValueError(f"Unknown provider: {provider}")
