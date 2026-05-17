"""Markdown → HTML pipeline for OutputView and HelpTab.

Pure Python, no Qt. The returned HTML embeds an inline <style> block
so it is safe to feed directly to QTextBrowser.setHtml without needing
an external stylesheet resource.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from markdown_it import MarkdownIt
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

_STYLE_PATH = Path(__file__).with_name("style.css")


def _highlight_code(code: str, lang: str | None, _attrs: object) -> str:
    """markdown-it-py highlight callback. Falls back to <pre> for unknown langs."""
    if lang:
        try:
            lexer = get_lexer_by_name(lang, stripall=False)
        except ClassNotFound:
            return ""  # let markdown-it render the default <pre><code> wrapper
    else:
        return ""
    formatter = HtmlFormatter(nowrap=False, noclasses=False, cssclass="highlight")
    return highlight(code, lexer, formatter)


@lru_cache(maxsize=1)
def _style_tag() -> str:
    css = _STYLE_PATH.read_text(encoding="utf-8")
    return f"<style>{css}</style>"


@lru_cache(maxsize=1)
def _md() -> MarkdownIt:
    # "gfm-like" preset = commonmark + tables + strikethrough.
    # linkify disabled — linkify-it-py is not a project dependency.
    return MarkdownIt("gfm-like", {"html": False, "linkify": False, "highlight": _highlight_code})


def _postprocess_badges(html: str) -> str:
    """v2 hook for game-term badges ({{card:...}}, {{relic:...}}, etc.).

    Currently identity. Do not remove — callers expect this to be the
    last transformation before returning HTML.
    """
    return html


def render(md_text: str) -> str:
    """Convert a Markdown fragment to a self-contained HTML document.

    Tolerant of mid-stream truncated input (streaming flushes). Never raises.
    """
    try:
        body = _md().render(md_text or "")
    except Exception:
        # Defensive: keep streaming output flowing even if markdown-it
        # trips on a partial structure.
        body = f"<pre>{(md_text or '').replace('<', '&lt;')}</pre>"
    body = _postprocess_badges(body)
    return f"{_style_tag()}<body>{body}</body>"
