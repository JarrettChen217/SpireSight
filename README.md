# SpireSight

AI visual assistant for *Slay the Spire II*. Captures a screenshot, runs a
selected prompt through a vision-capable LLM, streams markdown advice back.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate    # macOS / Linux
# .venv\Scripts\activate                              # Windows

pip install -e ".[dev]"
python -m spiresight
```

On first run, open **App → Settings → API Keys** and paste your OpenAI key.

## macOS: Accessibility permission

The global hotkey (`Ctrl/Cmd + Shift + S` by default) needs Accessibility
permission. If registration fails, a dialog opens System Settings — toggle
SpireSight on, then relaunch.

## Layout

- `src/spiresight/` — application code
- `prompts/` — user-editable system prompts and locale-specific quick actions
- `tests/` — pytest suite (`pytest -q`, runs in <2s, no display required)
- `docs/superpowers/specs/` — design document for the MVP

## Adding a provider

1. Drop a file at `src/spiresight/llm/providers/<name>_provider.py` implementing
   the `LLMProvider` Protocol (`name`, `list_models()`, `stream(...)`).
2. Register the factory in `src/spiresight/llm/registry.py::_PROVIDERS`.
3. Done — UI picks it up automatically.

## Security note

API keys are stored in **plaintext** in the app's config directory in this
MVP. Migration to the OS keyring is tracked in the design doc.
