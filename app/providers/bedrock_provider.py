import json
from typing import List, Optional, Type
import boto3
from pydantic import BaseModel

from app.services.validation import try_parse_json, validate_with_model

def get_enhanced_amazon_response(
    prompt: str,
    expected_fields: List[str],
    n: int = 1,
    pdf_bytes: Optional[bytes] = None,
    pdf_name: Optional[str] = None,
):
    print(f"calling Amazon model, file name is {pdf_name} ")

    if pdf_bytes is None:
        with open("Ring Copy Guidelines International 2025.pdf", "rb") as f:
            pdf_bytes = f.read()

    filename = "RingCopyGuidelinesInternational2025"
    if pdf_name:
        filename = "document"

    system = [{"text": f"{prompt}\n\n Do NOT wrap the output in markdown or code fences (no ```json, no backticks, no quotes before/after).Start with {{ and end with }}."}]
    message = [{
        "role": "user",
        "content": [
            {"document": {"format": "pdf", "name": filename, "source": {"bytes": pdf_bytes}}},
            {"text": "Generate the copy now following all requirements exactly. Return JSON only"},
        ],
    }]

    results = []
    for _ in range(max(1, n)):
        try:
            bedrock_client = boto3.client(service_name="bedrock-runtime", region_name="us-east-1")
            response = bedrock_client.converse(
                modelId="us.anthropic.claude-sonnet-4-20250514-v1:0",
                messages=message,
                system=system,
            )
            output = response["output"]["message"]["content"]
            content = output[0].get("text", {})
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
    Use Claude to convert arbitrary text to schema-valid JSON.
    """
    schema = model.model_json_schema()
    system = [{"text": "You convert content into STRICT JSON that validates against the user's JSON Schema. Output ONLY the JSON."}]
    message = [{
        "role": "user",
        "content": [
            {"text": f"SCHEMA:\n{json.dumps(schema, ensure_ascii=False)}\n---\nCONTENT:\n{raw_text}\n---\nReturn ONLY JSON that validates against the schema."}
        ],
    }]
    try:
        bedrock_client = boto3.client(service_name="bedrock-runtime", region_name="us-east-1")
        resp = bedrock_client.converse(
            modelId="us.anthropic.claude-sonnet-4-20250514-v1:0",
            messages=message,
            system=system,
        )
        text = resp["output"]["message"]["content"][0]["text"]
        parsed = try_parse_json(text)
        parsed = validate_with_model(model, parsed)
        return parsed
    except Exception as e:
        return {"error": f"repair_failed: {e}", "raw": raw_text}
