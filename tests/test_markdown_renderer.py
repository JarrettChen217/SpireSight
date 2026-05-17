from spiresight.ui.markdown.renderer import render


def test_render_basic_paragraph_returns_html():
    html = render("Hello **world**.")
    assert "<p>" in html
    assert "<strong>world</strong>" in html


def test_render_includes_inline_style_tag():
    html = render("# Title")
    assert "<style>" in html
    assert "</style>" in html


def test_render_heading_level_one():
    html = render("# Title")
    assert "<h1>" in html
    assert ">Title</h1>" in html


def test_render_fenced_code_block_uses_pygments_classes():
    md = "```python\nx = 1\n```"
    html = render(md)
    assert "highlight" in html  # Pygments highlight container
    assert "<span" in html


def test_render_unknown_code_lang_does_not_raise():
    md = "```bogusLang\nfoo\n```"
    html = render(md)
    assert "<pre" in html


def test_render_gfm_table():
    md = "| A | B |\n|---|---|\n| 1 | 2 |\n"
    html = render(md)
    assert "<table" in html
    assert "<th>A</th>" in html
    assert "<td>1</td>" in html


def test_render_blockquote():
    html = render("> note")
    assert "<blockquote>" in html
    assert "note" in html


def test_render_tolerates_incomplete_midstream_markdown():
    render("```python\nx = 1")
    render("| A | B |\n|---|---|\n| 1 |")
    render("# heading without newline")


def test_render_postprocess_badges_hook_is_identity():
    from spiresight.ui.markdown.renderer import _postprocess_badges
    assert _postprocess_badges("<p>x</p>") == "<p>x</p>"
