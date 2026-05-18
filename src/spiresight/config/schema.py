# src/spiresight/config/schema.py
"""Pydantic schemas for app and provider configuration.

NOTE(security): ProviderConfig.api_key holds the key in plaintext.
This is the deliberate MVP choice — migrate to OS keyring later.
See docs/superpowers/specs/2026-05-15-spiresight-mvp-design.md §11.1.
"""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderConfig(BaseModel):
    api_key: str = ""
    base_url: str | None = None


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    active_provider: str = "openai"
    active_model: str = "gpt-4o"
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    language: Literal["en", "zh"] = "en"
    theme: str = "dark_fantasy"
    always_on_top: bool = True
    mini_bar_mode: bool = False
    hotkey: str = "<ctrl>+<shift>+s"
    last_used_prompt_id: str | None = None
    include_screenshot_default: bool = True
    request_timeout_seconds: int = 180
