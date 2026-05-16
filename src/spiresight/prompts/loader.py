# src/spiresight/prompts/loader.py
"""YAML-backed prompt loader.

Layout:
  <root>/system_prompts.yaml
  <root>/locales/<lang>/quick_actions.yaml

Reload reads both files into memory and validates cross-references.
Reload is cheap; call it whenever the user changes language.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .schema import QuickAction, SystemPrompt


class PromptReferenceError(ValueError):
    """A QuickAction references a SystemPrompt id that doesn't exist."""


class PromptLoader:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._system: dict[str, SystemPrompt] = {}
        self._actions: dict[str, QuickAction] = {}
        self._action_order: list[str] = []

    def reload(self, language: str) -> None:
        sys_path = self._root / "system_prompts.yaml"
        sys_raw = yaml.safe_load(sys_path.read_text(encoding="utf-8")) or []
        self._system = {sp.id: sp for sp in (SystemPrompt(**r) for r in sys_raw)}

        actions_path = self._root / "locales" / language / "quick_actions.yaml"
        if not actions_path.exists():
            actions_path = self._root / "locales" / "en" / "quick_actions.yaml"
        raw = yaml.safe_load(actions_path.read_text(encoding="utf-8")) or []
        actions = [QuickAction(**r) for r in raw]
        for qa in actions:
            if qa.system_prompt_id not in self._system:
                raise PromptReferenceError(
                    f"QuickAction '{qa.id}' references unknown system_prompt_id "
                    f"'{qa.system_prompt_id}'"
                )
        self._actions = {qa.id: qa for qa in actions}
        self._action_order = [qa.id for qa in actions]

    def get_system_prompt(self, prompt_id: str) -> SystemPrompt:
        return self._system[prompt_id]

    def get_quick_action(self, action_id: str) -> QuickAction:
        return self._actions[action_id]

    def quick_actions(self) -> list[QuickAction]:
        return [self._actions[i] for i in self._action_order]
