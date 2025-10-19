from app.prompts.variants import build_variant_opening, build_output_requirements_json


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