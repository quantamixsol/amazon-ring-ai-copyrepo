from typing import Dict, List, Type
from pydantic import BaseModel, Field

# ---------- Pydantic models for strict structure ----------

class RingCopy(BaseModel):
    Content_Title: str = Field(...)
    Content_Body: str = Field(...)
    Headline_Variants: str = Field(...)          # pipe-separated
    Keywords_Primary: str = Field(...)
    Keywords_Secondary: str = Field(...)
    Description: str = Field(...)

class SocialCopy(BaseModel):
    Hashtags: str = Field(...)                    # "#foo #bar #baz"
    Engagement_Hook: str = Field(...)
    Value_Prop: str = Field(...)
    Address_Concerns: str = Field(...)
    Content: str = Field(...)

class EmailCopy(BaseModel):
    Subject_Line: str = Field(...)
    Greeting: str = Field(...)
    Main_Content: str = Field(...)
    Reference: str = Field(...)

class AudienceCopy(BaseModel):
    Easy_Installation_Self_Setup: str = Field(...)
    Technical_Features_and_Control: str = Field(...)
    Technical_Specifications: str = Field(...)
    Security_Benefits_Messaging: str = Field(...)

# Map variant -> fields (kept for UI char counting)
VARIANT_FIELDS: Dict[str, List[str]] = {
    "ring": [
        "Content_Title", "Content_Body", "Headline_Variants",
        "Keywords_Primary", "Keywords_Secondary", "Description",
    ],
    "social": ["Hashtags", "Engagement_Hook", "Value_Prop", "Address_Concerns", "Content"],
    "email": ["Subject_Line", "Greeting", "Main_Content", "Reference"],
    "audience": [
        "Easy_Installation_Self_Setup", "Technical_Features_and_Control",
        "Technical_Specifications", "Security_Benefits_Messaging",
    ],
}

# Map variant -> Pydantic model
VARIANT_MODELS: Dict[str, Type[BaseModel]] = {
    "ring": RingCopy,
    "social": SocialCopy,
    "email": EmailCopy,
    "audience": AudienceCopy,
}
