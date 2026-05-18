"""Static model-id → capability map used by provider fetch_remote_models()
to assign capability flags to refreshed model lists. Unknown IDs assume all
capabilities are supported and the caller sets `params.capabilities_inferred`
in the LogRow so the inference is auditable.
"""
from __future__ import annotations

from spiresight.llm.capabilities import Capability

_V, _T, _J, _TH = Capability.VISION, Capability.TOOL_USE, Capability.JSON_MODE, Capability.THINKING

KNOWN_MODEL_CAPS: dict[str, frozenset[Capability]] = {
    # ---- OpenAI ----
    "gpt-5":            frozenset({_V, _T, _J, _TH}),
    "gpt-5.5":          frozenset({_V, _T, _J, _TH}),
    "gpt-5-mini":       frozenset({_V, _T, _J, _TH}),
    "gpt-4o":           frozenset({_V, _T, _J}),
    "gpt-4o-mini":      frozenset({_V, _T, _J}),
    "o4-mini":          frozenset({_V, _T, _TH}),
    "o3":               frozenset({_V, _T, _TH}),
    "gpt-3.5-turbo":    frozenset({_T, _J}),

    # ---- Anthropic ----
    "claude-opus-4-7-20251015":    frozenset({_V, _T, _J, _TH}),
    "claude-sonnet-4-6-20251001":  frozenset({_V, _T, _J, _TH}),
    "claude-haiku-4-5-20251001":   frozenset({_V, _T, _J}),

    # ---- Gemini ----
    "gemini-2.5-pro":         frozenset({_V, _T, _J, _TH}),
    "gemini-2.5-flash":       frozenset({_V, _T, _J, _TH}),
    "gemini-2.5-flash-lite":  frozenset({_V, _T, _J}),

    # ---- OpenRouter aliases ----
    "anthropic/claude-opus-4-7":       frozenset({_V, _T, _J, _TH}),
    "google/gemini-2.5-pro":           frozenset({_V, _T, _J, _TH}),
    "deepseek/deepseek-chat":          frozenset({_T, _J}),
    "deepseek/deepseek-reasoner":      frozenset({_T, _TH}),
    "meta-llama/llama-3.3-70b":        frozenset({_T}),

    # ---- DeepSeek direct ----
    "deepseek-chat":      frozenset({_T, _J}),
    "deepseek-reasoner":  frozenset({_T, _TH}),

    # ---- Groq ----
    "llama-3.3-70b-versatile":        frozenset({_T}),
    "llama-3.1-8b-instant":           frozenset({_T}),
    "mixtral-8x7b-32768":             frozenset({_T}),
}

ASSUME_ALL_CAPS: frozenset[Capability] = frozenset({_V, _T, _J, _TH})


def infer_capabilities(model_id: str) -> tuple[frozenset[Capability], bool]:
    """Return (caps, is_inferred). is_inferred=True when the table missed."""
    if model_id in KNOWN_MODEL_CAPS:
        return KNOWN_MODEL_CAPS[model_id], False
    for known, caps in KNOWN_MODEL_CAPS.items():
        if model_id == known or model_id.startswith(known + "-"):
            return caps, False
    return ASSUME_ALL_CAPS, True
