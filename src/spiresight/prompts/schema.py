# src/spiresight/prompts/schema.py
from __future__ import annotations
from pydantic import BaseModel, Field, field_validator
from spiresight.llm.capabilities import Capability


class SystemPrompt(BaseModel):
    id: str
    description: str = ""
    content: str


class QuickAction(BaseModel):
    id: str
    label: str
    icon: str | None = None
    system_prompt_id: str
    user_template: str
    requires_screenshot: bool = True
    required_capabilities: list[Capability] = Field(default_factory=list)

    @field_validator("required_capabilities", mode="before")
    @classmethod
    def normalize_capabilities(cls, v):
        if isinstance(v, list):
            return [c.lower() if isinstance(c, str) else c for c in v]
        return v
