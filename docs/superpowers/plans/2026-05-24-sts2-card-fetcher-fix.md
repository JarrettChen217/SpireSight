# StS2 Card Fetcher/Parser Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the StS2 card fetcher so `data/sts2_cards/cards.json` becomes a reliable packaged knowledge base — descriptions preserve keyword nouns (Block, Common, Skill, …), mechanics lists contain only the card's own keywords, and fetch failures hard-fail instead of silently dropping cards.

**Architecture:** Single-file refactor of `tools/fetch_sts2_cards.py`. Decompose parsing into four pure helpers (`expand_templates`, `extract_lead`, `parse_structured_fields`, `extract_mechanics`), all driven by `mwparserfromhell`. Replace the brittle wikitext fetcher with redirect-following + typed-error API client + exponential-backoff retry wrapper. Delete the broken HTML fallback path. `main()` exits non-zero on any unrecoverable fetch error so `cards.json` is never overwritten with a partial result.

**Tech Stack:** Python 3.11+, `httpx` (HTTP), `mwparserfromhell` (wikitext AST), `pydantic` v2 (`CardKnowledge`), `pytest` + `respx` (tests), `uv` (runner), `ruff` (lint).

**Spec:** `docs/superpowers/specs/2026-05-24-sts2-card-fetcher-fix-design.md`

---

## Context for the executing agent

You are modifying a Python repo at the project root. All commands assume CWD is the project root.

**Always run Python via `uv`** (the project uses uv, not bare pip / bare python). Examples:
- `uv run pytest tests/test_fetch_sts2_cards.py -v`
- `uv run python -m tools.fetch_sts2_cards --output data/sts2_cards`
- `uv run ruff check`

**Do not stage or commit `.DS_Store` files.** macOS may sprinkle them around; the repo's `.gitignore` covers them but double-check `git status` before each commit.

**Never invent card data.** Generated `cards.json` must come from the live wiki.gg API or deterministic in-test wikitext fixtures. No LLM synthesis of card descriptions.

**Files you will create or modify:**

| Path | Change |
|---|---|
| `tools/fetch_sts2_cards.py` | Heavy refactor — split into helpers, new API client, new error type, removed HTML path |
| `tests/test_fetch_sts2_cards.py` | Add 9 new tests, keep all existing tests passing |
| `data/sts2_cards/cards.json` | Regenerated (final task) |
| `data/sts2_cards/metadata.json` | Regenerated (final task) |
| `data/sts2_cards/cards.sqlite` | Regenerated (final task) |
| `data/sts2_cards/zh_aliases.yaml` | **Untouched — must be byte-identical before/after** |

**Reference for `CardKnowledge` shape** (in `src/spiresight/knowledge/models.py`, do NOT modify):

```python
class CardKnowledge(BaseModel):
    id: str
    name_en: str
    aliases: list[str] = Field(default_factory=list)
    character: str | None = None
    rarity: str | None = None
    card_type: str | None = None
    cost: str | None = None
    description: str
    upgraded_description: str | None = None
    mechanics: list[str] = Field(default_factory=list)
    source_name: str = ""
    source_url: str = ""
    fetched_at: datetime  # accepts ISO string via pydantic coercion
```

**Wiki API contract** (all calls to `https://slaythespire.wiki.gg/api.php`):

```
GET /api.php?action=parse&page=Slay%20the%20Spire%202:Cards%20List&prop=links&format=json
→ {"parse": {"links": [{"ns": 3000, "*": "Slay the Spire 2:Deflect"}, ...]}}

GET /api.php?action=parse&page=<title>&prop=wikitext&format=json&redirects=1
→ {"parse": {"wikitext": {"*": "<raw wikitext>"}}}        on success
→ {"error": {"code": "missingtitle", "info": "..."}}      on failure
```

---

## Test fixtures (used by multiple tasks)

These string constants live at the top of `tests/test_fetch_sts2_cards.py`. The existing file already has `WIKITEXT`, `STS2_WIKITEXT`, and `HTML`. Keep `WIKITEXT` and `STS2_WIKITEXT`. **Delete** `HTML` once the HTML-fallback path is removed (Task 6). Add the new fixtures shown below in the task where they are first needed.

---

## Commit style

Use Conventional Commits. After each task, run `git status` to confirm no `.DS_Store` is staged, then commit with the message shown in the step. The repo enforces no-skip-hooks; if a pre-commit hook fails, **fix the underlying issue and create a new commit** — do not `--amend` and do not `--no-verify`.

---

## Task 1: Add `expand_templates` helper

**Files:**
- Modify: `tools/fetch_sts2_cards.py` (add new function)
- Modify: `tests/test_fetch_sts2_cards.py` (add new test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fetch_sts2_cards.py`:

```python
def test_expand_templates_preserves_keyword_labels():
    from tools.fetch_sts2_cards import expand_templates

    wikitext = (
        "{{C|Deflect||2}} is a 0 {{Icon|SE|2}} cost "
        "{{QueryLink|Cards|rarity:Common&color:Silent|Common|2}} "
        "{{QueryLink|Cards|type:Skill&color:Silent|Skill|2}} "
        "Card for the {{KW|Silent||2}}. It gives 4 (7 if upgraded) {{KW|Block||2}}."
    )
    out = expand_templates(wikitext)
    assert "Deflect" in out
    assert "Common" in out
    assert "Skill" in out
    assert "Silent" in out
    assert "Block" in out
    # Icon templates are dropped to empty
    assert "SE" not in out
    assert "Icon" not in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fetch_sts2_cards.py::test_expand_templates_preserves_keyword_labels -v`
Expected: FAIL with `ImportError` (cannot import name `expand_templates`).

- [ ] **Step 3: Implement `expand_templates` in `tools/fetch_sts2_cards.py`**

Add this function near the other parsing helpers (after `clean_text` is fine):

```python
def expand_templates(wikitext: str) -> str:
    """Rewrite StS2-specific MediaWiki templates to their visible text label.

    {{C|Name||2}}              -> "Name"
    {{KW|Word||2}}             -> "Word"
    {{QueryLink|...|label|2}}  -> "label" (param index 2)
    {{Icon|...}}               -> ""        (dropped)
    {{Card Infobox|...}}       -> ""        (dropped)
    {{Sequel Disambiguation}}  -> ""        (dropped)
    <unknown>                  -> mwparserfromhell strip_code default
    """
    parsed = mwparserfromhell.parse(wikitext)
    for template in list(parsed.filter_templates(recursive=True)):
        name = str(template.name).strip().casefold()
        params = list(template.params)
        if name in {"icon", "card infobox", "sequel disambiguation"}:
            replacement = ""
        elif name in {"c", "kw"} and params:
            replacement = clean_text(params[0].value)
        elif name == "querylink" and len(params) >= 3:
            replacement = clean_text(params[2].value)
        else:
            replacement = None  # let strip_code handle it
        if replacement is not None:
            try:
                parsed.replace(template, replacement)
            except ValueError:
                # template already removed by an outer rewrite — skip
                continue
    text = mwparserfromhell.parse(str(parsed)).strip_code()
    return re.sub(r"\s+", " ", text).strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fetch_sts2_cards.py::test_expand_templates_preserves_keyword_labels -v`
Expected: PASS.

- [ ] **Step 5: Run the existing test suite to confirm nothing else broke**

Run: `uv run pytest tests/test_fetch_sts2_cards.py -v`
Expected: all tests pass (the new one + existing ones; some existing tests may already pass even before the orchestrator refactor — that's fine).

- [ ] **Step 6: Commit**

```bash
git add tools/fetch_sts2_cards.py tests/test_fetch_sts2_cards.py
git status   # verify no .DS_Store
git commit -m "feat(fetch_sts2): add expand_templates helper"
```

---

## Task 2: Add `extract_lead` helper

**Files:**
- Modify: `tools/fetch_sts2_cards.py`
- Modify: `tests/test_fetch_sts2_cards.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fetch_sts2_cards.py`:

```python
def test_extract_lead_returns_text_before_first_section_header():
    from tools.fetch_sts2_cards import extract_lead

    wikitext = (
        "{{Sequel Disambiguation}}{{Card Infobox|Deflect||2}}\n"
        "Lead paragraph with {{KW|Block||2}}.\n"
        "== Update History ==\n"
        "* v0.98 added {{KW|Goopy||2}}.\n"
        "== Related Cards ==\n"
        "{{KW|Enchant||2}}\n"
    )
    lead = extract_lead(wikitext)
    assert "Block" in lead
    assert "Goopy" not in lead
    assert "Enchant" not in lead
    assert "Update History" not in lead


def test_extract_lead_returns_whole_wikitext_when_no_headers():
    from tools.fetch_sts2_cards import extract_lead

    wikitext = "Just a one-liner {{KW|Block||2}} with no section header."
    assert extract_lead(wikitext) == wikitext
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_fetch_sts2_cards.py::test_extract_lead_returns_text_before_first_section_header tests/test_fetch_sts2_cards.py::test_extract_lead_returns_whole_wikitext_when_no_headers -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `extract_lead`**

Add to `tools/fetch_sts2_cards.py`:

```python
_SECTION_HEADER_RE = re.compile(r"^==+.*==+\s*$", re.MULTILINE)


def extract_lead(wikitext: str) -> str:
    """Return wikitext up to (but not including) the first '==…==' section header.

    If no section header is found, return the whole text.
    """
    match = _SECTION_HEADER_RE.search(wikitext)
    if match is None:
        return wikitext
    return wikitext[: match.start()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_fetch_sts2_cards.py::test_extract_lead_returns_text_before_first_section_header tests/test_fetch_sts2_cards.py::test_extract_lead_returns_whole_wikitext_when_no_headers -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/fetch_sts2_cards.py tests/test_fetch_sts2_cards.py
git status
git commit -m "feat(fetch_sts2): add extract_lead helper"
```

---

## Task 3: Add `parse_structured_fields` helper

**Files:**
- Modify: `tools/fetch_sts2_cards.py`
- Modify: `tests/test_fetch_sts2_cards.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fetch_sts2_cards.py`:

```python
def test_parse_structured_fields_extracts_rarity_type_character_cost():
    from tools.fetch_sts2_cards import parse_structured_fields

    wikitext = (
        "{{Sequel Disambiguation}}{{Card Infobox|Deflect||2}}\n"
        "{{C|Deflect||2}} is a 0 {{Icon|SE|2}} cost "
        "{{QueryLink|Cards|rarity:Common&color:Silent|Common|2}} "
        "{{QueryLink|Cards|type:Skill&color:Silent|Skill|2}} "
        "Card for the {{KW|Silent||2}}.\n"
        "== Update History ==\n"
        "{{KW|Goopy||2}}\n"
    )
    fields = parse_structured_fields(wikitext)
    assert fields == {
        "rarity": "Common",
        "card_type": "Skill",
        "character": "Silent",
        "cost": "0",
    }


def test_parse_structured_fields_handles_x_cost():
    from tools.fetch_sts2_cards import parse_structured_fields

    wikitext = (
        "{{C|Whirlwind||2}} is a X {{Icon|SE|2}} cost "
        "{{QueryLink|Cards|rarity:Uncommon&color:Ironclad|Uncommon|2}} "
        "{{QueryLink|Cards|type:Attack&color:Ironclad|Attack|2}} "
        "Card for the {{KW|Ironclad||2}}."
    )
    fields = parse_structured_fields(wikitext)
    assert fields["cost"] == "X"
    assert fields["character"] == "Ironclad"


def test_parse_structured_fields_ignores_post_lead_templates():
    from tools.fetch_sts2_cards import parse_structured_fields

    wikitext = (
        "{{C|Card||2}} is a 1 {{Icon|SE|2}} cost "
        "{{QueryLink|Cards|rarity:Common&color:Silent|Common|2}} "
        "{{QueryLink|Cards|type:Skill&color:Silent|Skill|2}} "
        "Card for the {{KW|Silent||2}}.\n"
        "== Related ==\n"
        # These post-lead templates must NOT override the lead values.
        "{{QueryLink|Cards|rarity:Rare&color:Silent|Rare|2}}\n"
        "{{KW|Ironclad||2}}\n"
    )
    fields = parse_structured_fields(wikitext)
    assert fields["rarity"] == "Common"
    assert fields["character"] == "Silent"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_fetch_sts2_cards.py -k parse_structured_fields -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `parse_structured_fields`**

Add to `tools/fetch_sts2_cards.py`:

```python
_CHARACTER_VALUES = {"ironclad", "silent", "defect", "watcher", "necrobinder"}


def parse_structured_fields(wikitext: str) -> dict[str, str]:
    """Harvest rarity / card_type / character / cost from lead-paragraph templates.

    Returns a dict with only the keys that were found. Values are the wiki's
    surface form (e.g., "Common", "Silent") — caller is responsible for
    lowercasing where required by the data model.
    """
    lead = extract_lead(wikitext)
    parsed = mwparserfromhell.parse(lead)
    out: dict[str, str] = {}

    for template in parsed.filter_templates(recursive=True):
        name = str(template.name).strip().casefold()
        params = [clean_text(p.value) for p in template.params]
        if name == "querylink" and len(params) >= 3:
            query = params[1].casefold()
            label = params[2]
            if "rarity:" in query and "rarity" not in out:
                out["rarity"] = label
            if "type:" in query and "card_type" not in out:
                out["card_type"] = label
        elif name == "kw" and params and "character" not in out:
            if params[0].casefold() in _CHARACTER_VALUES:
                out["character"] = params[0]

    # Cost: text immediately before the first {{Icon|SE|...}} template in the lead.
    cost = _extract_cost_before_se_icon(lead)
    if cost is not None:
        out["cost"] = cost

    return out


def _extract_cost_before_se_icon(lead: str) -> str | None:
    parsed = mwparserfromhell.parse(lead)
    for template in parsed.filter_templates(recursive=True):
        if str(template.name).strip().casefold() != "icon":
            continue
        params = [clean_text(p.value) for p in template.params]
        if not params or params[0].casefold() != "se":
            continue
        before_raw = str(lead).split(str(template), 1)[0]
        before = mwparserfromhell.parse(before_raw).strip_code()
        before = re.sub(r"\s+", " ", before).strip()
        match = re.search(r"([Xx0-9]+)\s*$", before)
        if match:
            value = match.group(1)
            return "X" if value.casefold() == "x" else value
        return None
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_fetch_sts2_cards.py -k parse_structured_fields -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/fetch_sts2_cards.py tests/test_fetch_sts2_cards.py
git status
git commit -m "feat(fetch_sts2): add parse_structured_fields helper"
```

---

## Task 4: Add `extract_mechanics` helper (lead-scoped, character-excluded)

**Files:**
- Modify: `tools/fetch_sts2_cards.py`
- Modify: `tests/test_fetch_sts2_cards.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fetch_sts2_cards.py`:

```python
def test_extract_mechanics_keeps_lead_kw_keywords():
    from tools.fetch_sts2_cards import extract_mechanics

    wikitext = (
        "{{C|Deflect||2}} gives 4 {{KW|Block||2}} and applies {{KW|Weak||2}}.\n"
        "== Update History ==\n"
    )
    assert extract_mechanics(wikitext) == ["block", "weak"]


def test_extract_mechanics_ignores_post_lead_sections():
    from tools.fetch_sts2_cards import extract_mechanics

    wikitext = (
        "Lead with {{KW|Block||2}}.\n"
        "== Update History ==\n"
        "{{KW|Goopy||2}} {{KW|Enchant||2}}\n"
        "== Related Cards ==\n"
        "{{KW|Orobas||2}}\n"
    )
    assert extract_mechanics(wikitext) == ["block"]


def test_extract_mechanics_excludes_character_keywords():
    from tools.fetch_sts2_cards import extract_mechanics

    wikitext = "{{KW|Silent||2}} card with {{KW|Block||2}} and {{KW|Ironclad||2}}."
    assert extract_mechanics(wikitext) == ["block"]


def test_extract_mechanics_dedups_and_preserves_order():
    from tools.fetch_sts2_cards import extract_mechanics

    wikitext = "{{KW|Block||2}} {{KW|Weak||2}} {{KW|Block||2}}"
    assert extract_mechanics(wikitext) == ["block", "weak"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_fetch_sts2_cards.py -k extract_mechanics -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `extract_mechanics`**

Add to `tools/fetch_sts2_cards.py`:

```python
def extract_mechanics(wikitext: str) -> list[str]:
    """Return lowercased keywords from {{KW|...}} templates in the lead only.

    Character names (Silent, Ironclad, ...) are excluded. Duplicates removed,
    insertion order preserved.
    """
    lead = extract_lead(wikitext)
    parsed = mwparserfromhell.parse(lead)
    out: list[str] = []
    for template in parsed.filter_templates(recursive=True):
        if str(template.name).strip().casefold() != "kw" or not template.params:
            continue
        value = clean_text(template.params[0].value).casefold()
        if not value or value in _CHARACTER_VALUES:
            continue
        if value not in out:
            out.append(value)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_fetch_sts2_cards.py -k extract_mechanics -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/fetch_sts2_cards.py tests/test_fetch_sts2_cards.py
git status
git commit -m "feat(fetch_sts2): add lead-scoped extract_mechanics"
```

---

## Task 5: Refactor `parse_card_wikitext` to use the new helpers

**Files:**
- Modify: `tools/fetch_sts2_cards.py` (replace `parse_card_wikitext` body; delete `_extract_card_sentence`, `_infer_fields_from_sentence`, `_infer_fields_from_templates`, `_extract_mechanics`, `_extract_mechanics_from_templates`, `_merge_mechanics`)
- Modify: `tests/test_fetch_sts2_cards.py` (extend existing STS2 test; add Block-in-description assertion)

- [ ] **Step 1: Write the failing test**

Replace the existing `test_parse_sts2_sentence_wikitext_extracts_description` test in `tests/test_fetch_sts2_cards.py` with this stronger version, and add the second test below it:

```python
def test_parse_sts2_sentence_wikitext_extracts_description():
    from tools.fetch_sts2_cards import parse_card_wikitext

    card = parse_card_wikitext(
        title="Slay the Spire 2:Deflect",
        wikitext=STS2_WIKITEXT,
        source_url="https://example.test/Slay_the_Spire_2:Deflect",
        fetched_at="2026-05-24T00:00:00+00:00",
    )
    assert card.name_en == "Deflect"
    assert card.rarity == "common"
    assert card.card_type == "skill"
    assert card.character == "silent"
    assert card.cost == "0"
    # Description must now preserve the Block keyword from {{KW|Block||2}}.
    assert "Block" in card.description
    assert "block" in card.mechanics


def test_parse_card_wikitext_does_not_leak_post_lead_mechanics():
    from tools.fetch_sts2_cards import parse_card_wikitext

    wikitext = (
        "{{Sequel Disambiguation}}{{Card Infobox|Bash||2}}\n"
        "{{C|Bash||2}} is a 2 {{Icon|SE|2}} cost "
        "{{QueryLink|Cards|rarity:Basic&color:Ironclad|Basic|2}} "
        "{{QueryLink|Cards|type:Attack&color:Ironclad|Attack|2}} "
        "Card for the {{KW|Ironclad||2}}. It deals 8 damage and applies {{KW|Vulnerable||2}}.\n"
        "== Update History ==\n"
        "{{KW|Goopy||2}} {{KW|Enchant||2}} {{KW|Orobas||2}}\n"
    )
    card = parse_card_wikitext(
        title="Slay the Spire 2:Bash",
        wikitext=wikitext,
        source_url="https://example.test/Bash",
        fetched_at="2026-05-24T00:00:00+00:00",
    )
    assert card.mechanics == ["vulnerable"]
    assert "goopy" not in card.mechanics
    assert "Vulnerable" in card.description
```

Also extend the existing `test_parse_card_wikitext_extracts_upgrade_description` to assert mechanics:

```python
def test_parse_card_wikitext_extracts_upgrade_description():
    from tools.fetch_sts2_cards import parse_card_wikitext

    card = parse_card_wikitext(
        title="Deflect",
        wikitext=WIKITEXT,
        source_url="https://example.test/Deflect",
        fetched_at="2026-05-24T00:00:00+00:00",
    )
    assert card.name_en == "Deflect"
    assert card.rarity == "common"
    assert card.card_type == "skill"
    assert card.description == "Gain 4 Block."
    assert card.upgraded_description == "Gain 7 Block."
```

- [ ] **Step 2: Run tests to verify the new assertions fail**

Run: `uv run pytest tests/test_fetch_sts2_cards.py -k "parse_sts2 or does_not_leak or extracts_upgrade" -v`
Expected: existing implementation FAILS the new assertions (`"Block" in card.description` is False because templates are stripped; mechanics contains pollution).

- [ ] **Step 3: Replace `parse_card_wikitext` and delete now-unused helpers**

In `tools/fetch_sts2_cards.py`:

**Delete** these functions entirely: `_extract_card_sentence`, `_infer_fields_from_sentence`, `_infer_fields_from_templates`, `_extract_mechanics`, `_extract_mechanics_from_templates`, `_merge_mechanics`.

**Replace** the body of `parse_card_wikitext` with:

```python
def parse_card_wikitext(
    *,
    title: str,
    wikitext: str,
    source_url: str,
    fetched_at: str,
) -> CardKnowledge:
    parsed = mwparserfromhell.parse(wikitext)

    # 1. Look for an explicit {{Card|...}} infobox (used by the simple test fixture).
    infobox_fields: dict[str, str] = {}
    for template in parsed.filter_templates(recursive=True):
        if str(template.name).strip().casefold() == "card":
            for param in template.params:
                infobox_fields[clean_text(param.name).casefold()] = clean_text(param.value)
            break

    # 2. Harvest structured fields from lead-paragraph templates.
    structured = parse_structured_fields(wikitext)

    # 3. Build the description: prefer explicit infobox description, else the
    #    template-expanded lead text.
    name = infobox_fields.get("name") or _display_title(title)
    description = (
        infobox_fields.get("description")
        or infobox_fields.get("text")
        or _description_from_lead(wikitext)
    )
    upgraded = (
        infobox_fields.get("upgrade")
        or infobox_fields.get("upgraded_description")
        or infobox_fields.get("upgraded description")
    )

    rarity = infobox_fields.get("rarity") or structured.get("rarity")
    card_type = (
        infobox_fields.get("type")
        or infobox_fields.get("card_type")
        or structured.get("card_type")
    )
    character = infobox_fields.get("character") or structured.get("character")
    cost = infobox_fields.get("cost") or structured.get("cost")

    return CardKnowledge(
        id=slugify(name),
        name_en=name,
        aliases=[],
        character=_lower_or_none(character),
        rarity=_lower_or_none(rarity),
        card_type=_lower_or_none(card_type),
        cost=cost or None,
        description=description,
        upgraded_description=upgraded or None,
        mechanics=extract_mechanics(wikitext),
        source_name="wiki.gg",
        source_url=source_url,
        fetched_at=fetched_at,
    )


def _description_from_lead(wikitext: str) -> str:
    """Flatten the lead paragraph to clean inline text with template labels preserved."""
    return expand_templates(extract_lead(wikitext))
```

- [ ] **Step 4: Run the full fetcher test file**

Run: `uv run pytest tests/test_fetch_sts2_cards.py -v`
Expected: all tests pass — the new STS2 + Bash + Deflect assertions, plus the unchanged tests for filtering, alias preservation, and HTML fallback (HTML test still passes; we remove it in Task 6).

- [ ] **Step 5: Commit**

```bash
git add tools/fetch_sts2_cards.py tests/test_fetch_sts2_cards.py
git status
git commit -m "refactor(fetch_sts2): rebuild parse_card_wikitext on new helpers"
```

---

## Task 6: Delete the HTML fallback path

**Files:**
- Modify: `tools/fetch_sts2_cards.py` (delete `parse_card_html`, `_first_text`, `_infobox_value`, the `try/except` block in `fetch_cards` that calls it, and the `BeautifulSoup` import)
- Modify: `tests/test_fetch_sts2_cards.py` (delete `HTML` fixture and `test_parse_card_html_fallback_extracts_basic_fields`)

- [ ] **Step 1: Delete the test first (TDD: prove we don't depend on it)**

In `tests/test_fetch_sts2_cards.py`:
- Remove the `HTML = """..."""` fixture.
- Remove `test_parse_card_html_fallback_extracts_basic_fields`.

- [ ] **Step 2: Confirm the rest of the suite still passes**

Run: `uv run pytest tests/test_fetch_sts2_cards.py -v`
Expected: all remaining tests pass.

- [ ] **Step 3: Delete the HTML code path from `tools/fetch_sts2_cards.py`**

- Remove the `from bs4 import BeautifulSoup` import.
- Delete `parse_card_html`, `_first_text`, `_infobox_value`.
- In `fetch_cards`, replace the entire `try/except` block:

  ```python
  try:
      wikitext = _fetch_wikitext(client, title)
      card = parse_card_wikitext(
          title=title,
          wikitext=wikitext,
          source_url=source_url,
          fetched_at=fetched_at,
      )
  except Exception as exc:  # noqa: BLE001
      warnings.append(f"{title}: wikitext failed ({exc}); trying html")
      html = client.get(source_url).text
      card = parse_card_html(
          title=title,
          html=html,
          source_url=source_url,
          fetched_at=fetched_at,
      )
  if _looks_like_card(card):
      cards.append(card)
  else:
      warnings.append(f"{title}: skipped non-card page")
  ```

  with the straight-line version (no fallback; non-card filtering only):

  ```python
  wikitext = _fetch_wikitext(client, title)
  card = parse_card_wikitext(
      title=title,
      wikitext=wikitext,
      source_url=source_url,
      fetched_at=fetched_at,
  )
  if _looks_like_card(card):
      cards.append(card)
  else:
      warnings.append(f"{title}: skipped non-card page")
  ```

  (Error handling for `_fetch_wikitext` is added in Task 9; for now any exception propagates.)

- [ ] **Step 4: Verify nothing imports the removed symbols**

Run: `grep -nE "parse_card_html|_first_text|_infobox_value|BeautifulSoup|bs4" tools/fetch_sts2_cards.py tests/`
Expected: no matches.

- [ ] **Step 5: Run the suite**

Run: `uv run pytest tests/test_fetch_sts2_cards.py -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add tools/fetch_sts2_cards.py tests/test_fetch_sts2_cards.py
git status
git commit -m "refactor(fetch_sts2): drop broken HTML fallback path"
```

---

## Task 7: Add `WikiApiError` + improve `_fetch_wikitext`

**Files:**
- Modify: `tools/fetch_sts2_cards.py`
- Modify: `tests/test_fetch_sts2_cards.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fetch_sts2_cards.py`. Place the `import respx` and `import httpx` at the top of the file (alongside existing imports) so they're shared:

At the top of the file, add:

```python
import httpx
import pytest
import respx
```

Append to the bottom of the file:

```python
API_URL = "https://slaythespire.wiki.gg/api.php"


@respx.mock
def test_fetch_wikitext_returns_wikitext_on_success():
    from tools.fetch_sts2_cards import _fetch_wikitext

    respx.get(API_URL).mock(
        return_value=httpx.Response(
            200,
            json={"parse": {"title": "Slay the Spire 2:Deflect",
                            "wikitext": {"*": "raw wikitext body"}}},
        )
    )
    with httpx.Client() as client:
        result = _fetch_wikitext(client, "Slay the Spire 2:Deflect")
    assert result == "raw wikitext body"


@respx.mock
def test_fetch_wikitext_sends_redirects_param():
    from tools.fetch_sts2_cards import _fetch_wikitext

    route = respx.get(API_URL).mock(
        return_value=httpx.Response(
            200,
            json={"parse": {"wikitext": {"*": "x"}}},
        )
    )
    with httpx.Client() as client:
        _fetch_wikitext(client, "Slay the Spire 2:Deflect")
    request = route.calls.last.request
    assert request.url.params["redirects"] == "1"
    assert request.url.params["action"] == "parse"
    assert request.url.params["prop"] == "wikitext"
    assert request.url.params["format"] == "json"
    assert request.url.params["page"] == "Slay the Spire 2:Deflect"


@respx.mock
def test_fetch_wikitext_raises_on_api_error():
    from tools.fetch_sts2_cards import WikiApiError, _fetch_wikitext

    respx.get(API_URL).mock(
        return_value=httpx.Response(
            200,
            json={"error": {"code": "missingtitle", "info": "no such page"}},
        )
    )
    with httpx.Client() as client, pytest.raises(WikiApiError) as info:
        _fetch_wikitext(client, "Slay the Spire 2:Nope")
    assert info.value.code == "missingtitle"
    assert "no such page" in info.value.info
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_fetch_sts2_cards.py -k fetch_wikitext -v`
Expected: FAIL — `WikiApiError` doesn't exist; `_fetch_wikitext` doesn't pass `redirects=1`; error response raises `KeyError` not `WikiApiError`.

- [ ] **Step 3: Implement `WikiApiError` and rewrite `_fetch_wikitext`**

In `tools/fetch_sts2_cards.py`:

```python
class WikiApiError(RuntimeError):
    """Raised when the MediaWiki API returns an {"error": ...} response."""

    def __init__(self, code: str, info: str) -> None:
        super().__init__(f"{code}: {info}")
        self.code = code
        self.info = info


def _fetch_wikitext(client: httpx.Client, title: str) -> str:
    params = {
        "action": "parse",
        "page": title,
        "prop": "wikitext",
        "format": "json",
        "redirects": "1",
    }
    response = client.get(API_URL, params=params)
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        err = data["error"]
        raise WikiApiError(
            code=str(err.get("code", "unknown")),
            info=str(err.get("info", "")),
        )
    return data["parse"]["wikitext"]["*"]
```

(Replace the existing `_fetch_wikitext`. The module-level `API_URL` constant is already defined at the top of `tools/fetch_sts2_cards.py`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_fetch_sts2_cards.py -k fetch_wikitext -v`
Expected: 3 PASS.

- [ ] **Step 5: Run the full fetcher suite**

Run: `uv run pytest tests/test_fetch_sts2_cards.py -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add tools/fetch_sts2_cards.py tests/test_fetch_sts2_cards.py
git status
git commit -m "feat(fetch_sts2): typed WikiApiError + redirects=1 on _fetch_wikitext"
```

---

## Task 8: Add `_with_retry` helper

**Files:**
- Modify: `tools/fetch_sts2_cards.py`
- Modify: `tests/test_fetch_sts2_cards.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fetch_sts2_cards.py`:

```python
def test_with_retry_returns_value_on_first_success():
    from tools.fetch_sts2_cards import _with_retry

    calls = {"n": 0}

    def op():
        calls["n"] += 1
        return "ok"

    assert _with_retry(op, retries=3, base_delay=0) == "ok"
    assert calls["n"] == 1


def test_with_retry_retries_on_ratelimited_then_succeeds():
    from tools.fetch_sts2_cards import WikiApiError, _with_retry

    calls = {"n": 0}

    def op():
        calls["n"] += 1
        if calls["n"] < 3:
            raise WikiApiError("ratelimited", "slow down")
        return "ok"

    assert _with_retry(op, retries=3, base_delay=0) == "ok"
    assert calls["n"] == 3


def test_with_retry_does_not_retry_on_missingtitle():
    from tools.fetch_sts2_cards import WikiApiError, _with_retry

    calls = {"n": 0}

    def op():
        calls["n"] += 1
        raise WikiApiError("missingtitle", "no such page")

    with pytest.raises(WikiApiError):
        _with_retry(op, retries=3, base_delay=0)
    assert calls["n"] == 1


def test_with_retry_retries_on_httpx_transport_error():
    from tools.fetch_sts2_cards import _with_retry

    calls = {"n": 0}

    def op():
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ConnectError("boom")
        return "ok"

    assert _with_retry(op, retries=3, base_delay=0) == "ok"
    assert calls["n"] == 2


def test_with_retry_gives_up_after_retries_exhausted():
    from tools.fetch_sts2_cards import WikiApiError, _with_retry

    calls = {"n": 0}

    def op():
        calls["n"] += 1
        raise WikiApiError("ratelimited", "still slow")

    with pytest.raises(WikiApiError):
        _with_retry(op, retries=2, base_delay=0)
    assert calls["n"] == 3  # initial attempt + 2 retries
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_fetch_sts2_cards.py -k with_retry -v`
Expected: FAIL — `_with_retry` doesn't exist.

- [ ] **Step 3: Implement `_with_retry`**

Add to `tools/fetch_sts2_cards.py` (top of file already imports `httpx`; add `import time`):

```python
import time

# ... existing imports ...

_RETRYABLE_API_CODES = {"ratelimited", "internal_api_error_DBError", "readonly"}


def _with_retry(operation, *, retries: int = 3, base_delay: float = 0.5):
    """Call `operation()` with exponential backoff on retryable failures.

    Retries on:
      - httpx.HTTPError (network + 5xx, see _is_retryable_http_error)
      - WikiApiError with a retryable code

    Re-raises immediately on non-retryable WikiApiError codes.
    Total attempts = retries + 1.
    """
    attempt = 0
    while True:
        try:
            return operation()
        except WikiApiError as exc:
            if exc.code not in _RETRYABLE_API_CODES or attempt >= retries:
                raise
        except httpx.HTTPError:
            if attempt >= retries:
                raise
        time.sleep(base_delay * (2 ** attempt))
        attempt += 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_fetch_sts2_cards.py -k with_retry -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/fetch_sts2_cards.py tests/test_fetch_sts2_cards.py
git status
git commit -m "feat(fetch_sts2): add _with_retry exponential backoff wrapper"
```

---

## Task 9: Wire retry into `fetch_cards`, hard-fail `main()` on unrecoverable errors

**Files:**
- Modify: `tools/fetch_sts2_cards.py`
- Modify: `tests/test_fetch_sts2_cards.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fetch_sts2_cards.py`:

```python
@respx.mock
def test_main_exits_nonzero_and_writes_no_output_when_any_card_fails(tmp_path, monkeypatch):
    from tools import fetch_sts2_cards

    # Cards List returns two candidate titles.
    cards_list_payload = {
        "parse": {
            "links": [
                {"ns": 3000, "*": "Slay the Spire 2:Deflect"},
                {"ns": 3000, "*": "Slay the Spire 2:NotARealCard"},
            ]
        }
    }
    deflect_payload = {
        "parse": {
            "wikitext": {
                "*": (
                    "{{C|Deflect||2}} is a 0 {{Icon|SE|2}} cost "
                    "{{QueryLink|Cards|rarity:Common&color:Silent|Common|2}} "
                    "{{QueryLink|Cards|type:Skill&color:Silent|Skill|2}} "
                    "Card for the {{KW|Silent||2}}. It gives 4 {{KW|Block||2}}."
                )
            }
        }
    }

    def respond(request):
        page = request.url.params.get("page")
        if page == "Slay the Spire 2:Cards List":
            return httpx.Response(200, json=cards_list_payload)
        if page == "Slay the Spire 2:Deflect":
            return httpx.Response(200, json=deflect_payload)
        if page == "Slay the Spire 2:NotARealCard":
            return httpx.Response(
                200,
                json={"error": {"code": "missingtitle", "info": "no such page"}},
            )
        raise AssertionError(f"unexpected page: {page}")

    respx.get(fetch_sts2_cards.API_URL).mock(side_effect=respond)

    output = tmp_path / "sts2_cards"
    rc = fetch_sts2_cards.main(["--output", str(output)])
    assert rc == 1
    assert not (output / "cards.json").exists()
    assert not (output / "metadata.json").exists()


@respx.mock
def test_main_exit_zero_when_all_cards_succeed(tmp_path):
    from tools import fetch_sts2_cards

    cards_list_payload = {
        "parse": {
            "links": [{"ns": 3000, "*": "Slay the Spire 2:Deflect"}]
        }
    }
    deflect_payload = {
        "parse": {
            "wikitext": {
                "*": (
                    "{{C|Deflect||2}} is a 0 {{Icon|SE|2}} cost "
                    "{{QueryLink|Cards|rarity:Common&color:Silent|Common|2}} "
                    "{{QueryLink|Cards|type:Skill&color:Silent|Skill|2}} "
                    "Card for the {{KW|Silent||2}}. It gives 4 {{KW|Block||2}}."
                )
            }
        }
    }

    def respond(request):
        page = request.url.params.get("page")
        if page == "Slay the Spire 2:Cards List":
            return httpx.Response(200, json=cards_list_payload)
        return httpx.Response(200, json=deflect_payload)

    respx.get(fetch_sts2_cards.API_URL).mock(side_effect=respond)

    output = tmp_path / "sts2_cards"
    rc = fetch_sts2_cards.main(["--output", str(output)])
    assert rc == 0
    cards = json.loads((output / "cards.json").read_text(encoding="utf-8"))
    assert len(cards) == 1
    assert cards[0]["name_en"] == "Deflect"
    assert "block" in cards[0]["mechanics"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_fetch_sts2_cards.py -k "main_exits_nonzero or main_exit_zero" -v`
Expected: FAIL — current `fetch_cards` swallows errors as warnings and `main()` returns 0 even with partial output; also `cards.json` may get written.

- [ ] **Step 3: Rewrite `fetch_cards` and `main()`**

In `tools/fetch_sts2_cards.py`:

```python
def fetch_cards() -> tuple[list[CardKnowledge], list[str]]:
    fetched_at = datetime.now(tz=timezone.utc).isoformat()
    warnings: list[str] = []
    errors: list[str] = []
    cards: list[CardKnowledge] = []
    with httpx.Client(
        timeout=30.0,
        headers={"User-Agent": "SpireSight card fetcher (https://github.com/HaoChen217/SpireSight)"},
    ) as client:
        try:
            titles = _with_retry(lambda: _fetch_card_list_titles(client))
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"cards-list fetch failed: {exc}") from exc

        for title in titles:
            source_url = f"https://slaythespire.wiki.gg/wiki/{title.replace(' ', '_')}"
            try:
                wikitext = _with_retry(lambda t=title: _fetch_wikitext(client, t))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{title}: {exc}")
                continue
            card = parse_card_wikitext(
                title=title,
                wikitext=wikitext,
                source_url=source_url,
                fetched_at=fetched_at,
            )
            if _looks_like_card(card):
                cards.append(card)
            else:
                warnings.append(f"{title}: skipped non-card page")

    if errors:
        sample = "; ".join(errors[:5])
        more = "" if len(errors) <= 5 else f"; (+{len(errors) - 5} more)"
        raise RuntimeError(f"{len(errors)} card fetches failed: {sample}{more}")
    return cards, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch Slay the Spire 2 card data.")
    parser.add_argument("--output", type=Path, default=Path("data/sts2_cards"))
    args = parser.parse_args(argv)
    try:
        cards, warnings = fetch_cards()
        if not cards:
            raise RuntimeError("no cards fetched")
        write_outputs(args.output, cards, warnings=warnings)
    except Exception as exc:  # noqa: BLE001
        print(f"fetch failed: {exc}", file=sys.stderr)
        return 1
    return 0
```

Key behaviors:
- Cards-list fetch wrapped in `_with_retry` (a transient failure should not kill the whole run).
- Per-card fetch wrapped in `_with_retry` — non-retryable errors (e.g., `missingtitle`) bubble up immediately and append to `errors`.
- If `errors` non-empty, `fetch_cards` raises before any output is written.
- `main()` catches and exits 1 — `write_outputs` is never called on failure.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_fetch_sts2_cards.py -k "main_exits_nonzero or main_exit_zero" -v`
Expected: 2 PASS.

- [ ] **Step 5: Run the full fetcher suite**

Run: `uv run pytest tests/test_fetch_sts2_cards.py -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add tools/fetch_sts2_cards.py tests/test_fetch_sts2_cards.py
git status
git commit -m "feat(fetch_sts2): hard-fail main() on unrecoverable fetch errors"
```

---

## Task 10: Extend `filter_candidate_titles` test coverage

**Files:**
- Modify: `tests/test_fetch_sts2_cards.py`

- [ ] **Step 1: Replace the existing filter test**

Replace `test_filter_candidate_titles_keeps_sts2_cards_and_drops_mechanics` with this stronger version:

```python
def test_filter_candidate_titles_keeps_sts2_cards_and_drops_navigation_pages():
    from tools.fetch_sts2_cards import filter_candidate_titles

    links = [
        # Kept: real StS2 card page in the StS2 namespace.
        {"ns": 3000, "*": "Slay the Spire 2:Deflect"},
        {"ns": 3000, "*": "Slay the Spire 2:Bash"},
        # Dropped: mechanics/keyword pages (in _NON_CARD_TITLES denylist).
        {"ns": 3000, "*": "Slay the Spire 2:Block"},
        {"ns": 3000, "*": "Slay the Spire 2:Strength"},
        {"ns": 3000, "*": "Slay the Spire 2:Vulnerable"},
        # Dropped: the cards list page itself.
        {"ns": 3000, "*": "Slay the Spire 2:Cards List"},
        # Dropped: first-game pages in the main namespace.
        {"ns": 0, "*": "Deflect"},
        # Dropped: duplicates collapse to one entry.
        {"ns": 3000, "*": "Slay the Spire 2:Deflect"},
    ]
    assert filter_candidate_titles(links) == [
        "Slay the Spire 2:Deflect",
        "Slay the Spire 2:Bash",
    ]
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_fetch_sts2_cards.py::test_filter_candidate_titles_keeps_sts2_cards_and_drops_navigation_pages -v`
Expected: PASS (the function already handles these cases; this just locks the behavior).

- [ ] **Step 3: Run the full fetcher suite**

Run: `uv run pytest tests/test_fetch_sts2_cards.py -v`
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_fetch_sts2_cards.py
git status
git commit -m "test(fetch_sts2): expand filter_candidate_titles coverage"
```

---

## Task 11: Verify consumer test suites still pass, run full pytest + ruff

**Files:** None modified — verification only.

- [ ] **Step 1: Run the consumer test suites**

Run: `uv run pytest tests/test_fetch_sts2_cards.py tests/test_card_knowledge_store.py tests/test_knowledge_gateway.py -v`
Expected: all pass.

If `test_card_knowledge_store.py` or `test_knowledge_gateway.py` fail: the failure is on the fetcher side, **not** the consumer side. Read the failing test, identify which `CardKnowledge` field changed shape (most likely a field stayed `None` where the consumer expects a value), and adjust the fetcher to set the missing field correctly. **Do not modify the consumer tests.**

- [ ] **Step 2: Run the full pytest suite**

Run: `uv run pytest -v`
Expected: all pass.

- [ ] **Step 3: Run ruff**

Run: `uv run ruff check`
Expected: no errors. Fix any reported issues in `tools/fetch_sts2_cards.py` or `tests/test_fetch_sts2_cards.py` — these are likely unused-import warnings from Task 6's `bs4` removal or from Task 5's deletion of helpers.

- [ ] **Step 4: Commit any cleanup**

If Step 3 produced fixes:

```bash
git add tools/fetch_sts2_cards.py tests/test_fetch_sts2_cards.py
git status
git commit -m "chore(fetch_sts2): ruff cleanup"
```

If clean, skip this step.

---

## Task 12: Regenerate packaged card data

**Files:**
- Modify: `data/sts2_cards/cards.json` (regenerated)
- Modify: `data/sts2_cards/metadata.json` (regenerated)
- Modify: `data/sts2_cards/cards.sqlite` (regenerated)
- Untouched: `data/sts2_cards/zh_aliases.yaml` (must be byte-identical)

This step makes live HTTP calls to `slaythespire.wiki.gg`. It is the only step in this plan that touches the network.

- [ ] **Step 1: Snapshot `zh_aliases.yaml` for byte-identity verification**

```bash
shasum data/sts2_cards/zh_aliases.yaml > /tmp/zh_aliases.shasum
```

- [ ] **Step 2: Run the fetcher**

Run: `uv run python -m tools.fetch_sts2_cards --output data/sts2_cards`
Expected: process exits 0. If it exits 1, read stderr — the message names the failing titles. Do **not** patch around the failure with retries beyond what `_with_retry` already provides; investigate (likely a wiki page that genuinely doesn't exist under that title) and decide whether to add the title to `_NON_CARD_TITLES`. Re-run.

- [ ] **Step 3: Verify `card_count`**

```bash
uv run python -c "import json; m=json.load(open('data/sts2_cards/metadata.json')); print('card_count:', m['card_count'])"
```
Expected: substantially > 47 — target ~120+ (the visible Cards List page shows roughly that many links). If it's < 80, something is still being filtered out incorrectly; inspect `metadata.json` warnings and adjust before continuing.

- [ ] **Step 4: Spot-check four cards**

```bash
uv run python <<'PY'
import json
cards = {c["name_en"]: c for c in json.load(open("data/sts2_cards/cards.json"))}
for name in ["Deflect", "Bash", "Defend (Silent)", "Inflame"]:
    card = cards.get(name) or cards.get(name.split(" ")[0])
    if card is None:
        print(f"MISSING: {name}"); continue
    print(name)
    print(f"  desc:      {card['description']}")
    print(f"  mechanics: {card['mechanics']}")
    print(f"  rarity:    {card['rarity']}, type: {card['card_type']}, cost: {card['cost']}, char: {card['character']}")
PY
```
Expected per-card checks:
- `Deflect` → description contains "Block"; mechanics includes `"block"`; rarity `common`, type `skill`, cost `0`, character `silent`.
- `Bash` → description contains "Vulnerable"; mechanics includes `"vulnerable"`; character `ironclad`.
- `Defend (Silent)` → description contains "Block"; mechanics includes `"block"`; character `silent`.
- `Inflame` → description contains "Strength"; mechanics includes `"strength"`; character `ironclad`.

**None** of the four should list `goopy`, `enchant`, `spiral`, `ethereal`, `buffer`, `orobas`, or `tezcatara's ember` in mechanics. If any do, the lead-paragraph scoping has a bug and you need to revisit Task 4.

- [ ] **Step 5: Verify `zh_aliases.yaml` is byte-identical**

```bash
shasum -c /tmp/zh_aliases.shasum
```
Expected: `data/sts2_cards/zh_aliases.yaml: OK`. If it fails, `write_outputs` is corrupting the alias file — revisit and fix before continuing.

- [ ] **Step 6: Re-run the full test suite against the new data**

Run: `uv run pytest -v`
Expected: all pass. The store/gateway tests load the new `cards.json`/`cards.sqlite`; if they fail, the new data has a schema-level issue (e.g., a card missing a required field) and needs fixing in the fetcher, not the tests.

- [ ] **Step 7: Verify no `.DS_Store` is staged and commit the data**

```bash
git status
# Confirm only data/sts2_cards/cards.json, metadata.json, cards.sqlite are modified.
# If any .DS_Store appears, do NOT add it — investigate .gitignore.
git add data/sts2_cards/cards.json data/sts2_cards/metadata.json data/sts2_cards/cards.sqlite
git commit -m "data(sts2_cards): regenerate from improved fetcher"
```

- [ ] **Step 8: Final sanity check**

Run: `git status` and `git log --oneline -15`
Expected:
- Working tree clean.
- Recent commits show the Task 1–12 sequence on top of the prior `f0fe175` baseline.

---

## Done criteria (audit checklist)

Before declaring the implementation complete, verify all of these:

- [ ] `uv run pytest tests/test_fetch_sts2_cards.py tests/test_card_knowledge_store.py tests/test_knowledge_gateway.py` passes.
- [ ] `uv run pytest` (full suite) passes.
- [ ] `uv run ruff check` is clean.
- [ ] `data/sts2_cards/metadata.json` shows `card_count` substantially > 47.
- [ ] `data/sts2_cards/zh_aliases.yaml` is byte-identical to the pre-change snapshot.
- [ ] Manual spot-checks of Deflect / Bash / Defend (Silent) / Inflame all show preserved keyword nouns and clean mechanics lists.
- [ ] `git status` is clean. No `.DS_Store` was committed at any point.
- [ ] The full diff touches only: `tools/fetch_sts2_cards.py`, `tests/test_fetch_sts2_cards.py`, `data/sts2_cards/{cards.json,metadata.json,cards.sqlite}`, plus this plan file. **No changes** to `src/spiresight/knowledge/` or to `zh_aliases.yaml`.
