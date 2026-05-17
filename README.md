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

## Installation (unsigned builds)

SpireSight builds are **not code-signed** in this MVP. First-launch
warnings are expected.

### macOS

1. Download `SpireSight-<version>-macos-arm64.dmg` from the [Releases page](https://github.com/JarrettChen217/SpireSight/releases).
2. Open the DMG and drag `SpireSight.app` into `/Applications`.
3. First launch will be blocked by Gatekeeper. Either:
   - **Right-click** `SpireSight.app` in Finder → **Open** → confirm in the dialog, OR
   - Run once: `xattr -dr com.apple.quarantine /Applications/SpireSight.app`

Apple Silicon (M1/M2/M3/M4) only. Intel Macs are not supported.

### Windows

1. Download `SpireSight-<version>-windows-x64.zip` from the Releases page.
2. Extract anywhere (e.g. `C:\Program Files\SpireSight\`).
3. Run `SpireSight.exe`. SmartScreen will warn "Windows protected your PC".
   Click **More info** → **Run anyway**.

## Release process (maintainer)

Releases are fully automated. Tags drive everything; do not edit
`pyproject.toml` version manually.

```bash
# Make sure main is green
git checkout main && git pull

# Tag and push
git tag v0.1.1
git push origin v0.1.1

# Watch https://github.com/JarrettChen217/SpireSight/actions
# After ~8–12 minutes, the new release appears with DMG + zip attached.
```

Pre-release: include a hyphen in the tag (e.g. `v0.2.0-rc.1`). The
workflow auto-flags it as a GitHub pre-release.

Rollback a bad tag (only works before users download):

```bash
git push --delete origin v0.1.1
git tag -d v0.1.1
# Then delete the release in the GitHub Releases UI (if it was created).
```
