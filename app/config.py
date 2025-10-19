import os
from dotenv import load_dotenv

# Load env once
load_dotenv()

# ---------------- Constants ----------------
DEFAULT_PROVIDER = "OpenAI"  # "OpenAI" | "Perplexity" | "Amazon Claude"
OPENAI_DEFAULT_MODEL = "gpt-5"
PERPLEXITY_DEFAULT_MODEL = "sonar-pro"
AMAZON_CLAUDE_DEFAULT_MODEL = "Claude Sonnet 4"

PDF_CONTEXT_CHARS_DEFAULT = 16000
NUM_VARIATIONS = 3

# Default Excel path fallback
DEFAULT_EXCEL_PATH = "Ring_Copy_Solution_Enhanced_with_Clownfish_Jellyfish_and_Needlefish.xlsx"

# PDF attachment settings (OpenAI only)
PDF_FILENAME = "Ring Copy Guidelines International 2025.pdf"
ENABLE_PDF_ATTACHMENT = True
ENABLE_PDF_TEXT_FALLBACK = True

# Misc
LOGO_CANDIDATES = ["image (1).png"]

# Env accessors (optional convenience)
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")