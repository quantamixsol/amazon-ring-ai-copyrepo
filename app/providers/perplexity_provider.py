import json
import base64
from typing import List, Optional, Type
from pydantic import BaseModel

from perplexity import Perplexity
from app.config import PERPLEXITY_API_KEY
from app.io.pdf import get_default_pdf_b64
from app.services.validation import try_parse_json, validate_with_model

_client: Perplexity | None = None
def _get_client() -> Perplexity:
    global _client
    if _client is None:
        _client = Perplexity(api_key=PERPLEXITY_API_KEY)
    return _client

def get_enhanced_perplexity_response(
    prompt: str,
    expected_fields: List[str],
    n: int = 1,
    pdf_bytes: Optional[bytes] = None,
    pdf_name: Optional[str] = None,
):
    print("using perplexity model")

    local_encoded = base64.b64encode(pdf_bytes).decode("utf-8") if pdf_bytes else (get_default_pdf_b64() or "")
    local_name = pdf_name or "Ring Copy Guidelines International 2025.pdf"

    base_messages = [
        {"role": "system", "content": [{"type": "text","text": f"{prompt}\n\n Do NOT wrap the output in markdown or code fences (no ```json, no backticks, no quotes before/after).Start with {{ and end with }}."}]},
        {"role": "user", "content": [
            {"type": "text","text": "Generate the copy now following all requirements exactly. Return JSON only"},
            {"type": "file_url","file_url": {"url": local_encoded, "file_name": local_name}}
        ]}
    ]

    client = _get_client()
    results = []
    for _ in range(max(1, n)):
        try:
            completion = client.chat.completions.create(model="sonar-pro", messages=base_messages)
            content = completion.choices[0].message.content
            try:
                parsed = json.loads(content)
                results.append(parsed)
            except json.JSONDecodeError:
                results.append({"error": "Invalid JSON", "raw": content})
        except Exception as e:
            results.append({"error": str(e)})
    return results

def repair_to_json(raw_text: str, model: Type[BaseModel]) -> dict | dict[str, str]:
    """
    One-step repair prompt: convert raw_text into valid JSON matching model.
    """
    client = _get_client()
    schema = model.model_json_schema()
    sys = "You are a formatter. Convert the given content into STRICT JSON matching the provided JSON Schema. Output ONLY the JSON."
    user = f"""SCHEMA:
{json.dumps(schema, ensure_ascii=False)}
---
CONTENT:
{raw_text}
---
Return ONLY JSON that validates against the schema."""
    try:
        fix = client.chat.completions.create(
            model="sonar-pro",
            messages=[{"role": "system", "content": [{"type":"text","text": sys}]},
                      {"role":"user","content":[{"type":"text","text":user}]}]
        )
        text = fix.choices[0].message.content
        parsed = try_parse_json(text)
        parsed = validate_with_model(model, parsed)
        return parsed
    except Exception as e:
        return {"error": f"repair_failed: {e}", "raw": raw_text}
