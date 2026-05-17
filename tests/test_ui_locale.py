import pytest

from spiresight.prompts.ui_locale import UILocale


@pytest.fixture
def locales_dir(tmp_path):
    """Create a minimal locales dir with en+zh ui_strings.yaml."""
    en_dir = tmp_path / "en"
    en_dir.mkdir(parents=True)
    (en_dir / "ui_strings.yaml").write_text("""
panel:
  greeting: "Hello {name}"
  simple: "No placeholders"
main:
  msg: "Status: {code}"
""", encoding="utf-8")

    zh_dir = tmp_path / "zh"
    zh_dir.mkdir()
    (zh_dir / "ui_strings.yaml").write_text("""
panel:
  greeting: "你好 {name}"
  simple: "没有占位符"
main:
  msg: "状态: {code}"
""", encoding="utf-8")
    return tmp_path


def test_get_with_placeholders(locales_dir):
    loc = UILocale(locales_dir, language="en")
    assert loc.get("panel.greeting", name="World") == "Hello World"


def test_get_without_placeholders(locales_dir):
    loc = UILocale(locales_dir, language="en")
    assert loc.get("panel.simple") == "No placeholders"


def test_get_missing_key_raises_keyerror(locales_dir):
    loc = UILocale(locales_dir, language="en")
    with pytest.raises(KeyError):
        loc.get("nonexistent.key")


def test_set_language_switches_locale(locales_dir):
    loc = UILocale(locales_dir, language="en")
    assert loc.get("panel.greeting", name="World") == "Hello World"
    loc.set_language("zh")
    assert loc.get("panel.greeting", name="World") == "你好 World"


def test_set_language_same_is_noop(locales_dir):
    loc = UILocale(locales_dir, language="en")
    calls: list[int] = []
    loc.changed.connect(lambda: calls.append(1))
    loc.set_language("en")  # same language
    assert calls == []


def test_set_language_emits_changed(locales_dir):
    loc = UILocale(locales_dir, language="en")
    calls: list[int] = []
    loc.changed.connect(lambda: calls.append(1))
    loc.set_language("zh")
    assert calls == [1]


def test_falls_back_to_en_for_missing_locale(tmp_path):
    en_dir = tmp_path / "en"
    en_dir.mkdir(parents=True)
    (en_dir / "ui_strings.yaml").write_text('panel:\n  x: "EN"', encoding="utf-8")
    loc = UILocale(tmp_path, language="zz")  # no zz dir
    assert loc.get("panel.x") == "EN"


def test_str_representation(locales_dir):
    loc = UILocale(locales_dir, language="zh")
    assert repr(loc) == "UILocale(language='zh')"
