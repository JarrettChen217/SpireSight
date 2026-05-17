# SpireSight — Quick Help

## Global hotkey

`Ctrl/Cmd + Shift + S` re-runs your last quick action with the current
screen.

## Mini-bar mode

Click the mini-bar icon in the top-right (or use the **App** menu) to
collapse the main window into a small always-on-top bar that still
fires quick actions. Click it again to restore.

## Inspect flow

1. Press **📷 Capture** in the sidebar to grab one or more deck-view
   frames (up to 6). Thumbnails appear in a strip; the × on each
   thumbnail removes that frame.
2. Press **✓ Done** to send the frames to the LLM for parsing.
3. The parsed run state appears in the **Run State** tab and is
   automatically attached to every subsequent quick action so the
   advice stays context-aware.
4. **✕ Clear** drops the captured frames and the parsed state.

## Adding an API key

**App → Settings → API Keys** — paste your provider key, save. Keys are
stored in plaintext in your local config file for the MVP; switching
to OS keyring is on the roadmap.

## Slay the Spire II terms

- **Archetype**: a deck identity (Frost, Focus, Strength, etc.) the
  Inspect prompt tries to detect.
- **Usefulness**: how the LLM rates a card for the detected archetype
  — Key / Good / Situational / Skip. Rendered as colored groups in
  the Run State tab.
- **Rarity glyphs**: `○` starter · `●` common · `◆` uncommon/rare.
