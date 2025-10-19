import json
from typing import Any, Type
from pydantic import BaseModel, ValidationError

from app.utils.strings import coerce_str

def total_chars_for_result(result: dict, fields: list[str] | None = None) -> int:
    if not isinstance(result, dict):
        return 0
    if fields:
        return sum(len(coerce_str(result.get(f, ""))) for f in fields)
    return sum(len(coerce_str(v)) for v in result.values() if isinstance(v, (str, int, float)))

def strip_code_fences(text: str) -> str:
    if not isinstance(text, str):
        return text
    t = text.strip()
    # remove ```json ... ``` or ``` ... ```
    if t.startswith("```"):
        # drop first line (``` or ```json) and trailing ```
        parts = t.split("\n")
        if parts and parts[0].startswith("```"):
            parts = parts[1:]
        if parts and parts[-1].strip().startswith("```"):
            parts = parts[:-1]
        t = "\n".join(parts).strip()
    return t

def try_parse_json(text: str) -> Any:
    t = strip_code_fences(text)
    # also trim stray leading/trailing junk before/after braces
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        t = t[start:end+1]
    return json.loads(t)

def validate_with_model(model: Type[BaseModel], payload: Any) -> dict:
    """
    Validate and return a clean dict (model.dict()).
    Raises ValidationError or JSONDecodeError upstream if invalid.
    """
    obj = model.model_validate(payload)
    return obj.model_dump()

def pydantic_json_schema(model: Type[BaseModel]) -> dict:
    """
    JSON Schema to pass into OpenAI structured output.
    """
    return {
        "name": f"{model.__name__}Schema",
        "schema": model.model_json_schema(),  # OpenAI expects Draft 2020-12-like
        "strict": True,
    }
