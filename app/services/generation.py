from typing import List, Optional, Type
from pydantic import BaseModel

from app.providers.openai_provider import get_enhanced_openai_response
from app.providers.perplexity_provider import get_enhanced_perplexity_response, repair_to_json as ppx_repair
from app.providers.bedrock_provider import get_enhanced_amazon_response, repair_to_json as bedrock_repair

def _repair_if_needed(provider: str, result: dict, model: Type[BaseModel]) -> dict:
    if "error" not in result or "raw" not in result:
        return result
    raw = result["raw"]
    try:
        if provider == "Perplexity":
            fixed = ppx_repair(raw, model)
        elif provider == "Amazon Claude":
            fixed = bedrock_repair(raw, model)
        else:
            # OpenAI: rely on structured output first; if still broken, try a minimal fallback?
            # (Keeping simple: return original error)
            return result
        if isinstance(fixed, dict) and "error" not in fixed:
            return fixed
        return result
    except Exception:
        return result

def get_enhanced_response(
    provider: str,
    openai_client,
    prompt: str,
    expected_fields: List[str],
    model: str,
    n: int = 1,
    pdf_file_id: Optional[str] = None,
    pdf_bytes: Optional[bytes] = None,
    pdf_name: Optional[str] = None,
    pydantic_model: Optional[Type[BaseModel]] = None,
):
    if provider == "Perplexity":
        results = get_enhanced_perplexity_response(
            prompt=prompt,
            expected_fields=expected_fields,
            n=n,
            pdf_bytes=pdf_bytes,
            pdf_name="document.pdf",
        )
        if pydantic_model:
            results = [ _repair_if_needed(provider, r, pydantic_model) for r in results ]
        return results

    elif provider == "Amazon Claude":
        results = get_enhanced_amazon_response(
            prompt=prompt,
            expected_fields=expected_fields,
            n=n,
            pdf_bytes=pdf_bytes,
            pdf_name="document.pdf",
        )
        if pydantic_model:
            results = [ _repair_if_needed(provider, r, pydantic_model) for r in results ]
        return results

    # OpenAI with structured outputs when possible
    return get_enhanced_openai_response(
        client=openai_client,
        prompt=prompt,
        expected_fields=expected_fields,
        model=model,
        n=n,
        pdf_file_id=pdf_file_id,
        pydantic_model=pydantic_model,
    )
