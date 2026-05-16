# UI Internationalization & Icon Prefixes

**Status:** Design
**Date:** 2026-05-16
**Branch:** `main`
**Builds on:** `2026-05-16-multi-frame-capture-design.md` (implemented, commits `1b182f1`..`69c6fed`)

## Problem

The project has language switching (`AppConfig.language: "en" | "zh"`) via Settings dialog,
but only Quick Action labels are translated (YAML per locale). All UI widget strings —
button text, tooltips, status bar messages, placeholders — are hardcoded in English.
After adding the multi-frame capture panel (3 new buttons, ~8 new strings), the gap is
more visible.

Also, the panel buttons are plain text. Unicode prefix icons improve scanability.

## Scope

- **YAML-based UI string storage** — one `ui_strings.yaml` per locale under
  `prompts/locales/{lang}/`, same pattern as `quick_actions.yaml`.
- **Thin `UILocale` class** — loads the YAML, provides `get(key, **kwargs)` with
  `str.format` interpolation, emits a Qt `changed` signal on language switch.
- **Icon prefixes** — unicode symbols embedded in locale string values (e.g.,
  `"📷 Capture"` / `"📷 捕获"`). The locale determines which glyph to use.
- **Widget re-translation** — `RunStatePanel` and `MainWindow` each get a
  `_retranslate()` method that sets every user-visible string. They connect to
  `UILocale.changed` so language switches re-populate automatically.
- **Full coverage** — every hardcoded English string in the inspect + capture
  flow (buttons, tooltips, status bar, empty state, section headers) is covered.

Explicit non-goals:
- Translating system prompts (`sts_inspector`, `sts_decision`) — those remain
  English-only for now (LLM quality depends on English prompts).
- Translating Quick Action `user_template` content — already done.
- Settings dialog, mini-bar, permission dialog — out of scope. Only the inspect
  panel and related MainWindow strings are covered.
- Dynamic label formatting beyond `str.format(**kwargs)` — no plural rules, no
  ICU messageformat.

## Architecture

```
┌────────────────────────────┐
│  prompts/locales/{lang}/   │
│    ui_strings.yaml         │
└──────────┬─────────────────┘
           │ load
┌──────────▼─────────────────┐
│  UILocale                  │
│  - get(key, **kw) -> str   │
│  - changed = Signal()      │
└──────────┬─────────────────┘
           │ subscribe
     ┌─────┴─────┐
     │           │
┌────▼─────┐ ┌───▼──────────┐
│RunState  │ │ MainWindow   │
│Panel     │ │              │
│_retrans- │ │ _retranslate │
│late()    │ │ ()           │
└──────────┘ └──────────────┘
```

## UILocale API

```python
# src/spiresight/prompts/ui_locale.py

class UILocale(QObject):
    """YAML-backed UI string lookup. Emits changed when language switches."""
    changed = Signal()

    def __init__(self, locales_dir: Path, language: str = "en", parent=None): ...

    def set_language(self, language: str) -> None:
        """Reload the YAML for the given language, emit changed if different."""

    def get(self, key: str, **kwargs: object) -> str:
        """Return the formatted string for `key`.
        Raises KeyError if the key is not found in the current locale.
        """
```

Key semantics:
- Constructor loads the YAML immediately.
- `set_language` is a no-op if the language hasn't changed.
- `get` raises `KeyError` on missing key (fail fast — missing translations are bugs).

## YAML Schema

```yaml
# prompts/locales/en/ui_strings.yaml
panel:
  header: "Run State"
  capture: "📷 Capture"
  done: "✓ Done"
  done_busy: "Analyzing…"
  clear: "✕ Clear"
  max_frames: "Maximum {max} frames per session."
  no_frames: "Capture at least one frame first."
  empty_hint: "Press Capture to grab one or more deck-view frames, then Done."
  frame_tooltip: "Frame {n}"

  # section subheaders (rendered dynamically)
  archetype: "Archetype"
  cards: "Cards ({total})"
  relics: "Relics"
  potions: "Potions"
  eval: "Eval"

main:
  capture_failed: "Capture failed: {error}"
  captured_frame: "Captured frame {count}."
  inspecting: "Inspecting {count} frame(s)…"
  run_state_cleared: "Run state cleared."
  run_state_captured: "Run state captured."
  inspect_needs: "Inspect needs {missing} — switch model."
  inspect_malformed: "Inspect failed: malformed response, try again."
  inspect_failed: "Inspect failed: {error}"
  no_provider: "Configure a provider first."
  no_model: "Select a model."
  lacks_caps: "Active model lacks {caps}."
```

```yaml
# prompts/locales/zh/ui_strings.yaml
panel:
  header: "Run State"
  capture: "📷 捕获"
  done: "✓ 完成"
  done_busy: "分析中…"
  clear: "✕ 清除"
  max_frames: "最多 {max} 帧"
  no_frames: "请先捕获至少一帧"
  empty_hint: "按捕获按钮抓取牌组画面，再按完成"
  frame_tooltip: "第 {n} 帧"

  archetype: "流派"
  cards: "卡牌 ({total})"
  relics: "遗物"
  potions: "药水"
  eval: "评估"

main:
  capture_failed: "捕获失败：{error}"
  captured_frame: "已捕获第 {count} 帧。"
  inspecting: "正在分析 {count} 帧…"
  run_state_cleared: "已清除 Run State。"
  run_state_captured: "Run State 已捕获。"
  inspect_needs: "需要 {missing} — 请切换模型。"
  inspect_malformed: "分析失败：响应格式错误，请重试。"
  inspect_failed: "分析失败：{error}"
  no_provider: "请先配置 Provider。"
  no_model: "请选择模型。"
  lacks_caps: "当前模型缺少 {caps}。"
```

## Retranslate pattern

Each widget that holds user-visible strings implements `_retranslate()`:

```python
def _retranslate(self) -> None:
    loc = self._locale                      # UILocale reference
    self._capture_btn.setText(loc.get("panel.capture"))
    self._done_btn.setText(
        loc.get("panel.done_busy") if self._busy else loc.get("panel.done")
    )
    # ... all other strings ...
    self._update_button_states()            # re-evaluate tooltips
```

Called once during construction (after `UILocale` is assigned), then on every
`UILocale.changed` emission.

## Lifecycle

1. `MainWindow.__init__` creates `UILocale(locales_dir, config.language)` as `self._ui_locale`.
2. `MainWindow` passes `ui_locale` to `RunStatePanel` constructor (alongside `store` and `session`).
3. Panel subscribes to `ui_locale.changed` → `_retranslate`.
4. MainWindow subscribes to `ui_locale.changed` → its own `_retranslate`.
5. Settings dialog saves new language → `_loader.reload()` → `self._ui_locale.set_language(config.language)` → `changed` fires → widgets re-translate.

## Testing

- `tests/test_ui_locale.py`: unit tests for `UILocale` — loads YAML, `get` with/without kwargs, `KeyError` on missing key, `set_language` changes locale, `changed` signal.
- No widget-level i18n tests (manual smoke only, same as existing RunStatePanel pattern).

## Files Touched

New:
- `prompts/locales/en/ui_strings.yaml`
- `prompts/locales/zh/ui_strings.yaml`
- `src/spiresight/prompts/ui_locale.py`
- `tests/test_ui_locale.py`

Modified:
- `src/spiresight/ui/widgets/run_state_panel.py` — accept `UILocale`, add `_retranslate()`
- `src/spiresight/ui/windows/main_window.py` — create `UILocale`, pass to panel, add `_retranslate()`, switch language on settings save

## Out of Scope

- Translating system prompts, mini-bar, settings dialog, permission dialog.
- Plural rules or ICU messageformat — `str.format` only.
- RTL layout support.
- Icon customization per-locale beyond unicode prefix choice.
