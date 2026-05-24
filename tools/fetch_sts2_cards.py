from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import mwparserfromhell

from spiresight.knowledge.models import CardKnowledge, normalize_query

API_URL = "https://slaythespire.wiki.gg/api.php"
SCRIPT_VERSION = "1"


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


class WikiApiError(RuntimeError):
    """Raised when the MediaWiki API returns an {"error": ...} response."""

    def __init__(self, code: str, info: str) -> None:
        super().__init__(f"{code}: {info}")
        self.code = code
        self.info = info
CARDS_LIST_PAGE = "Slay the Spire 2:Cards List"
_NON_CARD_TITLES = {
    "Slay the Spire 2:Block",
    "Slay the Spire 2:Strength",
    "Slay the Spire 2:Vulnerable",
    "Slay the Spire 2:Cards List",
}


def slugify(name: str) -> str:
    slug = normalize_query(name).replace(" ", "_")
    return slug or "unknown"


def clean_text(value: Any) -> str:
    text = mwparserfromhell.parse(str(value)).strip_code() if value is not None else ""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


_SECTION_HEADER_RE = re.compile(r"^==+.*==+\s*$", re.MULTILINE)


def extract_lead(wikitext: str) -> str:
    """Return wikitext up to (but not including) the first '==…==' section header.

    If no section header is found, return the whole text.
    """
    match = _SECTION_HEADER_RE.search(wikitext)
    if match is None:
        return wikitext
    return wikitext[: match.start()]


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



def write_outputs(output: Path, cards: list[CardKnowledge], *, warnings: list[str]) -> None:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    alias_text = None
    alias_path = output / "zh_aliases.yaml"
    if alias_path.exists():
        alias_text = alias_path.read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="sts2_cards_", dir=str(output.parent)) as tmp_name:
        tmp = Path(tmp_name)
        cards_json = [card.model_dump(mode="json") for card in cards]
        (tmp / "cards.json").write_text(
            json.dumps(cards_json, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        metadata = {
            "source_name": "wiki.gg",
            "source_urls": sorted({card.source_url for card in cards if card.source_url}),
            "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
            "script_version": SCRIPT_VERSION,
            "card_count": len(cards),
            "warnings": warnings,
        }
        (tmp / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if alias_text is not None:
            (tmp / "zh_aliases.yaml").write_text(alias_text, encoding="utf-8")
        else:
            (tmp / "zh_aliases.yaml").write_text("{}\n", encoding="utf-8")
        _write_sqlite(tmp / "cards.sqlite", cards)

        for name in ("cards.json", "metadata.json", "cards.sqlite"):
            shutil.move(str(tmp / name), str(output / name))
        if alias_text is None and not alias_path.exists():
            shutil.move(str(tmp / "zh_aliases.yaml"), str(alias_path))


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


def filter_candidate_titles(links: list[dict[str, Any]]) -> list[str]:
    titles: list[str] = []
    seen: set[str] = set()
    for link in links:
        title = str(link.get("*", ""))
        if link.get("ns") != 3000:
            continue
        if not title.startswith("Slay the Spire 2:"):
            continue
        if title in _NON_CARD_TITLES:
            continue
        if title in seen:
            continue
        seen.add(title)
        titles.append(title)
    return titles


def _fetch_card_list_titles(client: httpx.Client) -> list[str]:
    params = {
        "action": "parse",
        "page": CARDS_LIST_PAGE,
        "prop": "links",
        "format": "json",
    }
    data = client.get(API_URL, params=params).json()
    return filter_candidate_titles(data.get("parse", {}).get("links", []))


def _fetch_category_titles(client: httpx.Client) -> list[str]:
    params = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": "Category:Cards",
        "cmlimit": "500",
        "format": "json",
    }
    data = client.get(API_URL, params=params).json()
    return [item["title"] for item in data.get("query", {}).get("categorymembers", [])]


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



def _lower_or_none(value: str | None) -> str | None:
    return value.casefold() if value else None


def _display_title(title: str) -> str:
    return title.split(":", 1)[1] if title.startswith("Slay the Spire 2:") else title



def _write_sqlite(path: Path, cards: list[CardKnowledge]) -> None:
    con = sqlite3.connect(path)
    try:
        con.execute(
            "CREATE VIRTUAL TABLE cards_fts USING fts5(id, name_en, description, mechanics)"
        )
        con.executemany(
            "INSERT INTO cards_fts(id, name_en, description, mechanics) VALUES (?, ?, ?, ?)",
            [
                (
                    card.id,
                    card.name_en,
                    card.description,
                    " ".join(card.mechanics),
                )
                for card in cards
            ],
        )
        con.commit()
    except sqlite3.OperationalError:
        path.unlink(missing_ok=True)
    finally:
        con.close()


def _looks_like_card(card: CardKnowledge) -> bool:
    return bool(card.description and (card.card_type or card.rarity or card.cost))


if __name__ == "__main__":
    raise SystemExit(main())
