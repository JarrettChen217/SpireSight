# StS2 Card Fetcher/Parser Fix — Design

**Status:** Draft
**Owner:** HaoChen
**Date:** 2026-05-24
**Branch:** `codex-card-knowledge-gateway-design`
**Related:** [2026-05-24-card-knowledge-gateway-design.md](2026-05-24-card-knowledge-gateway-design.md)

## Problem

`tools/fetch_sts2_cards.py` produces a low-quality `data/sts2_cards/cards.json`:

- Only 47 cards survive, despite the source page listing ~150.
- Descriptions lose template keywords. Example output: `"It gives 5 (8 if upgraded) ."` — the `{{KW|Block||2}}` template that should yield "Block" is stripped to an empty string.
- `mechanics` lists are polluted with terms like `orobas`, `enchant`, `goopy`, `tezcatara's ember` — words that come from the Update History / related-cards sections, not the card itself.
- ~30 real cards silently disappear because `_fetch_wikitext` raises `KeyError('parse')` on `{"error": ...}` API responses and the HTML fallback hits a Cloudflare challenge.

Root causes:
1. `clean_text` uses `mwparserfromhell.strip_code()`, which deletes templates wholesale rather than expanding them to their visible label.
2. Mechanics are extracted from every `{{KW|…}}` on the page, including post-lead sections.
3. The wikitext fetcher mistakes API error responses for parse failures, and the HTML fallback is blocked upstream.
4. Partial output silently overwrites the packaged file.

## Goal

`data/sts2_cards/cards.json` becomes a reliable packaged knowledge base for StS2 card selection: real card data, complete coverage, descriptions that include keyword nouns, and mechanics lists that reflect only the card's own keywords.

## Non-Goals

- Scraping `sts2.huijiwiki.com` for Chinese aliases (separate spec later). `zh_aliases.yaml` stays a hand-curated file preserved byte-for-byte on regen.
- Schema changes to `CardKnowledge`.
- Any change to `spiresight/knowledge/` (store, gateway, models).
- Backwards-compatibility shims for the deleted HTML fallback.

## Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Template expansion | Local rewriter using `mwparserfromhell` — no extra API calls. |
| Mechanics scope | Lead paragraph only (text before the first `==` section header). No hardcoded mechanics allowlist. |
| Fetch-failure handling | Retry with exponential backoff + redirect follow + **hard fail**: `main()` exits non-zero if any card cannot be fetched, so partial output never overwrites `cards.json`. |
| zh wiki | Out of scope for this change. |

## Architecture

Single-file change inside `tools/fetch_sts2_cards.py`. No new modules. Current logic is split into small pure functions so the test suite can exercise each piece with wikitext fixtures.

| Function | Purpose | Pure |
|---|---|---|
| `expand_templates(wikitext) -> str` | Per-template rewriter (see Section: Template rewriter). Returns clean inline text. | yes |
| `extract_lead(wikitext) -> str` | Returns wikitext up to the first `==…==` header. Used by sentence extraction and mechanics scoping. | yes |
| `parse_structured_fields(wikitext) -> dict` | Walks templates in the lead only; harvests `rarity`/`card_type` from `QueryLink`, `character` from `KW` when the value matches a known character, `cost` from the text immediately preceding `{{Icon\|SE\|…}}`. | yes |
| `extract_mechanics(wikitext) -> list[str]` | Walks `{{KW\|…}}` templates in the lead only, excluding character names. No hardcoded mechanics allowlist. | yes |
| `parse_card_wikitext(...)` | Orchestrator (existing name). Uses the four helpers above; drops the brittle `is a/is an` regex. | yes |
| `_fetch_wikitext(client, title)` | Adds `redirects=1`; raises typed `WikiApiError` on `{"error": ...}`. | side-effect |
| `_with_retry(callable, *, retries=3, base_delay=0.5)` | Exponential backoff wrapper for retryable HTTP errors and `WikiApiError` codes `{ratelimited, internal_api_error_DBError, readonly}`. | side-effect |
| `parse_card_html` | **Removed.** Cloudflare blocks the HTML path; keeping a dead fallback hides failures. | — |
| `main()` | Exits non-zero if any candidate title fails after retries. `cards.json` is not overwritten on a partial run. | side-effect |

`_NON_CARD_TITLES` stays. `_looks_like_card` stays as a sanity guard (description non-empty AND one of `{card_type, rarity, cost}` present), but the new parser makes it secondary rather than the primary filter.

User-Agent bumped to `"SpireSight card fetcher (https://github.com/HaoChen217/SpireSight)"` per wiki.gg etiquette.

## Template rewriter

`expand_templates` walks `mwparserfromhell` template nodes, replaces them in-place, then calls `strip_code()` on the result. Concrete rules:

```
{{C|Deflect||2}}                                          → "Deflect"
{{KW|Block||2}}                                           → "Block"
{{KW|Silent||2}}                                          → "Silent"
{{QueryLink|Cards|rarity:Common&color:Silent|Common|2}}   → "Common"   (param[2])
{{QueryLink|Cards|type:Skill&color:Silent|Skill|2}}       → "Skill"
{{Icon|SE|2}}                                             → ""          (drop)
{{Icon|<other>|...}}                                      → ""          (drop visual icons)
{{Card Infobox|Deflect||2}}                               → ""
{{Sequel Disambiguation}}                                 → ""
<unknown template>                                        → strip_code default
```

Implementation: rewrite using `parsed.replace(template, replacement)`, then `str(parsed)`, then a final whitespace squeeze. Unknown templates fall through to mwparserfromhell's default — they should not be inserting critical text, and we prefer odd description text over a crashed run.

`parse_structured_fields` does a **second** pass over the lead-only template list to harvest structured data **before** flattening to text. That way both representations come from the same source of truth: `rarity="common"` (structured) and `description="… is a 0 cost Common Skill Card for the Silent. It gives 4 (7 if upgraded) Block."` (flattened).

Character allowlist (kept from current code): `{"ironclad", "silent", "defect", "watcher", "necrobinder"}`.

Cost extraction (replaces the current fragile regex): split the lead at the first `{{Icon|SE|…}}` template; on the left side, find the last integer or `X` token. Concretely: `re.search(r"([Xx0-9]+)\s*$", clean_left_text)`.

## Mechanics scoping

`extract_lead(wikitext)`: return everything before the first line matching `^==+.*==+\s*$`. If no header, the whole page is the lead.

`extract_mechanics(wikitext)`:
1. `lead = extract_lead(wikitext)`
2. Parse `lead` with mwparserfromhell.
3. For each `{{KW|value|…}}`, lowercase `value`.
4. Drop values in the character allowlist.
5. Dedup, preserve insertion order.

Description-side substring scanning is removed — the structured `{{KW|…}}` template is the canonical signal. The old `_extract_mechanics(description, upgraded)` substring scan is deleted.

## API client (retries, redirects, errors)

`_fetch_wikitext(client, title)`:
- Params: `action=parse&page=<title>&prop=wikitext&format=json&redirects=1`.
- If the JSON contains `"error"`, raise `WikiApiError(code, info)`. No more `KeyError('parse')`.
- Otherwise return `data["parse"]["wikitext"]["*"]`.

`_with_retry(callable, *, retries=3, base_delay=0.5)`:
- Retries on `httpx.HTTPError` (network/5xx) and `WikiApiError` where `code in {"ratelimited", "internal_api_error_DBError", "readonly"}`.
- Sleeps `base_delay * 2**attempt` between attempts.
- Re-raises on final failure or non-retryable codes (`missingtitle`, etc.).

`fetch_cards()`:
- For each title, call `_with_retry(lambda: _fetch_wikitext(client, title))`.
- Unrecoverable failures append to `errors` (separate from `warnings`).
- After the loop, if `errors` is non-empty, raise `RuntimeError(f"{len(errors)} cards failed: …")` so `main()` exits non-zero.

`parse_card_html` and the HTML fallback path are deleted entirely.

## Testing

`tests/test_fetch_sts2_cards.py` — keep existing tests, add these:

| Test | What it asserts |
|---|---|
| `test_expand_templates_preserves_keyword_labels` | `{{KW\|Block\|\|2}}` → contains "Block"; `{{C\|Deflect\|\|2}}` → "Deflect"; `{{QueryLink\|Cards\|rarity:Common&color:Silent\|Common\|2}}` → "Common"; `{{Icon\|SE\|2}}` → "". |
| `test_parse_sts2_wikitext_extracts_block_in_description_and_mechanics` | Using `STS2_WIKITEXT`: `card.description` contains "Block"; `"block"` in `card.mechanics`. |
| `test_parse_sts2_wikitext_extracts_rarity_type_character_cost` | rarity=`common`, card_type=`skill`, character=`silent`, cost=`0`. |
| `test_extract_mechanics_ignores_post_lead_sections` | Lead contains `{{KW\|Block\|\|2}}`; post-`== Update History ==` contains `{{KW\|Goopy\|\|2}}` and `{{KW\|Enchant\|\|2}}`. Assert mechanics == `["block"]`. |
| `test_extract_mechanics_excludes_character_kw` | `{{KW\|Silent\|\|2}}` and `{{KW\|Block\|\|2}}` in lead → mechanics == `["block"]`. |
| `test_filter_candidate_titles_drops_navigation_pages` | Extend existing test with `Slay the Spire 2:Buffs`, `Slay the Spire 2:Strength`, and a ns=0 first-game page — all dropped. |
| `test_fetch_wikitext_raises_on_api_error` | Mock httpx returns `{"error": {"code": "missingtitle"}}`; assert `WikiApiError` raised. |
| `test_fetch_wikitext_retries_on_ratelimit` | Mock returns ratelimited twice then success; assert called 3×, returns wikitext. |
| `test_main_exits_nonzero_when_any_card_fails` | Mock fetcher with one good + one fatally-failing title; assert `main()` returns 1 and `cards.json` is **not** written. |
| `test_write_outputs_preserves_existing_alias_file` | Unchanged. |

HTTP tests use `httpx.MockTransport` (no live network). `tests/test_card_knowledge_store.py` and `tests/test_knowledge_gateway.py` should keep passing unchanged — if they break, fix the fetcher, not the tests.

## Regen procedure & exit criteria

After the parser changes:
1. Run `uv run python -m tools.fetch_sts2_cards --output data/sts2_cards`.
2. Verify `metadata.json` `card_count` is substantially > 47 (expectation: ~120+, matching the Cards List page link count).
3. Spot-check `Deflect`, `Bash`, `Defend (Silent)`, `Inflame`: description contains keyword nouns (Block, Strength, …), mechanics list is short and relevant, no `goopy`/`orobas`-style pollution.
4. `zh_aliases.yaml` byte-identical to before (covered by `test_write_outputs_preserves_existing_alias_file`, re-verify on disk).
5. Run the test commands from the brief:
   - `uv run pytest tests/test_fetch_sts2_cards.py tests/test_card_knowledge_store.py tests/test_knowledge_gateway.py`
   - `uv run pytest`
   - `uv run ruff check`
6. `git status` shows only the expected diff under `tools/`, `tests/`, and `data/sts2_cards/{cards.json,metadata.json,cards.sqlite}`. No `.DS_Store` staged.

## API reference

All calls go to `https://slaythespire.wiki.gg/api.php`.

Cards list:
```
GET /api.php?action=parse&page=Slay%20the%20Spire%202:Cards%20List&prop=links&format=json
```
Response shape: `data["parse"]["links"]` is a list of `{"ns": int, "*": "Slay the Spire 2:<Title>"}`. We keep links where `ns == 3000`, title starts with `"Slay the Spire 2:"`, and the title is not in `_NON_CARD_TITLES`.

Per-card wikitext:
```
GET /api.php?action=parse&page=<title>&prop=wikitext&format=json&redirects=1
```
Response shape on success: `data["parse"]["wikitext"]["*"]` is the raw page wikitext. On error: `data["error"]` is `{"code": str, "info": str}` — handled by `WikiApiError`.

If wiki.gg's API surface differs from this contract (e.g., `ns` value drift), document the actual response in the implementation PR and adjust `filter_candidate_titles` to match.
