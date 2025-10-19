from typing import Dict

# Per-mode default Authoring Context
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
        return (
            "You are a senior copywriter for Ring. Use the brand guidelines and the approved template patterns as non-negotiable constraints. "
            "Write copy that is channel-appropriate, concise, and strictly consistent with Ring's voice."
        )
    if variant == "social":
        return (
            "You are a Social Media Content Creator for Ring. Craft platform-native, scroll-stopping copy with clear hooks and CTAs while honouring Ring's brand voice. "
            "Optimise for engagement (thumb-stopping first line, brevity, scannability, hashtags where relevant)."
        )
    if variant == "email":
        return (
            "You are an Email Campaign Generator for Ring. Create persuasive email copy with a compelling subject line, preview snippet feel, and clear CTA hierarchy. "
            "Maintain brand voice, avoid spammy wording, and keep body copy crisp and conversion-focused."
        )
    if variant == "audience":
        return (
            "You are an Audience Adaptation campaign specialist for Ring. Develop messaging that emphasises easy installation and self-setup, highlights technical features and control, "
            "includes technical specifications, and maintains strong security benefits messaging."
        )
    return "You are a senior copywriter for Ring."