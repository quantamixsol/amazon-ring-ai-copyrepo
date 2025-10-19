import json
from typing import List, Optional, Type
from pydantic import BaseModel

from app.config import OPENAI_DEFAULT_MODEL
from app.services.validation import pydantic_json_schema, try_parse_json, validate_with_model

def get_openai_client(api_key: str | None = None):
    from openai import OpenAI
    return OpenAI(api_key=api_key) if api_key else OpenAI()

def get_enhanced_openai_response(
    client,
    prompt: str,
    expected_fields: List[str],
    model: str = OPENAI_DEFAULT_MODEL,
    n: int = 1,
    pdf_file_id: Optional[str] = None,
    pydantic_model: Optional[Type[BaseModel]] = None,
):
    """
    Uses OpenAI structured output if a Pydantic model is provided.
    Fallback: json_object.
    """
    print("calling openai model")
    results = []
    use_schema = pydantic_model is not None

    try:
        if pdf_file_id:
            # Responses API path (no response_format param here, so we validate post-hoc)
            for _ in range(n):
                resp = client.responses.create(
                    model=model,
                    instructions=prompt,
                    input=[{
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "Generate the copy now following all requirements exactly. Return JSON only."},
                            {"type": "input_file", "file_id": pdf_file_id},
                        ],
                    }],
                )
                content_text = resp.output_text
                try:
                    parsed = try_parse_json(content_text)
                    if pydantic_model:
                        parsed = validate_with_model(pydantic_model, parsed)
                    results.append(parsed)
                except Exception:
                    results.append({"error": "Invalid JSON", "raw": content_text})
            return results

        # Chat Completions path with structured output if available
        kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Generate the copy now following all requirements exactly. Return JSON only."},
            ],
            "n": n,
            "max_tokens": 8000,
        }

        if use_schema:
            kwargs["response_format"] = {"type": "json_schema", "json_schema": pydantic_json_schema(pydantic_model)}
        else:
            kwargs["response_format"] = {"type": "json_object"}

        response = client.chat.completions.create(**kwargs)

        for choice in response.choices:
            try:
                content = choice.message.content
                parsed = try_parse_json(content)
                if pydantic_model:
                    parsed = validate_with_model(pydantic_model, parsed)
                results.append(parsed)
            except Exception:
                results.append({"error": "Invalid JSON", "raw": choice.message.content})
        return results

    except Exception as e:
        return [{"error": str(e)}]
