"""Pydantic schemas for app and provider configuration.

NOTE(security): ProviderConfig.api_key holds the key in plaintext.
This is the deliberate MVP choice — migrate to OS keyring later.
See docs/superpowers/specs/2026-05-15-spiresight-mvp-design.md §11.1.
"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelInfoDict(BaseModel):
    """JSON-serializable mirror of llm.models.ModelInfo for ProviderConfig."""
    id: str
    display_name: str
    capabilities: list[Literal["vision", "tool_use", "json_mode", "thinking"]] = Field(
        default_factory=list
    )
    context_window: int = 0


class ProviderConfig(BaseModel):
    api_key: str = ""
    base_url: str | None = None
    cached_models: list[ModelInfoDict] = Field(default_factory=list)


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    active_provider: Literal["openai", "openai_compat", "pixel_api", "anthropic", "gemini"] = "openai"
    active_model: str = "gpt-4o"
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    language: Literal["en", "zh"] = "en"
    theme: str = "dark_fantasy"
    always_on_top: bool = True
    mini_bar_mode: bool = False
    hotkey: str = "<ctrl>+<shift>+s"
    bubble_width:  int = 360
    bubble_height: int = 280
    chat_transcript_mode: Literal["compact", "expanded"] = "compact"
    chat_assistant_max_height: int = 200
    last_used_prompt_id: str | None = None
    include_screenshot_default: bool = False
    quick_action_clear_context: bool = True
    request_timeout_seconds: int = 180
