from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import mwparserfromhell
from bs4 import BeautifulSoup

from spiresight.knowledge.models import CardKnowledge, normalize_query

API_URL = "https://slaythespire.wiki.gg/api.php"
SCRIPT_VERSION = "1"
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
    fields: dict[str, str] = {}
    for template in parsed.filter_templates(recursive=True):
        if "card" not in str(template.name).casefold():
            continue
        for param in template.params:
            fields[clean_text(param.name).casefold()] = clean_text(param.value)
        break

    name = fields.get("name") or _display_title(title)
    sentence = _extract_card_sentence(wikitext)
    description = fields.get("description") or fields.get("text") or sentence
    upgraded = (
        fields.get("upgrade")
        or fields.get("upgraded_description")
        or fields.get("upgraded description")
    )
    inferred = _infer_fields_from_sentence(sentence)
    inferred.update(_infer_fields_from_templates(wikitext))
    return CardKnowledge(
        id=slugify(name),
        name_en=name,
        aliases=[],
        character=_lower_or_none(fields.get("character") or inferred.get("character")),
        rarity=_lower_or_none(fields.get("rarity") or inferred.get("rarity")),
        card_type=_lower_or_none(fields.get("type") or fields.get("card_type") or inferred.get("card_type")),
        cost=fields.get("cost") or inferred.get("cost") or None,
        description=description,
        upgraded_description=upgraded or None,
        mechanics=_merge_mechanics(
            _extract_mechanics(description, upgraded),
            _extract_mechanics_from_templates(wikitext),
        ),
        source_name="wiki.gg",
        source_url=source_url,
        fetched_at=fetched_at,
    )


def parse_card_html(
    *,
    title: str,
    html: str,
    source_url: str,
    fetched_at: str,
) -> CardKnowledge:
    soup = BeautifulSoup(html, "html.parser")
    name = _first_text(soup, [".pi-title", "h1"]) or title
    fields = {
        key: _infobox_value(soup, key)
        for key in ("character", "rarity", "type", "card_type", "cost")
    }
    paragraphs = [
        p.get_text(" ", strip=True)
        for p in soup.find_all("p")
        if p.get_text(" ", strip=True)
    ]
    description = paragraphs[0] if paragraphs else ""
    return CardKnowledge(
        id=slugify(name),
        name_en=name,
        aliases=[],
        character=_lower_or_none(fields.get("character")),
        rarity=_lower_or_none(fields.get("rarity")),
        card_type=_lower_or_none(fields.get("type") or fields.get("card_type")),
        cost=fields.get("cost") or None,
        description=description,
        upgraded_description=None,
        mechanics=_extract_mechanics(description, None),
        source_name="wiki.gg",
        source_url=source_url,
        fetched_at=fetched_at,
    )


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
    warnings: list[str] = ["secondary source verification skipped"]
    with httpx.Client(timeout=30.0, headers={"User-Agent": "SpireSight card fetcher"}) as client:
        titles = _fetch_card_list_titles(client)
        cards: list[CardKnowledge] = []
        for title in titles:
            source_url = f"https://slaythespire.wiki.gg/wiki/{title.replace(' ', '_')}"
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
    }
    data = client.get(API_URL, params=params).json()
    return data["parse"]["wikitext"]["*"]


def _first_text(soup: BeautifulSoup, selectors: list[str]) -> str:
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            text = node.get_text(" ", strip=True)
            if text:
                return text
    return ""


def _infobox_value(soup: BeautifulSoup, key: str) -> str | None:
    node = soup.select_one(f'[data-source="{key}"] .pi-data-value')
    if node is None:
        return None
    text = node.get_text(" ", strip=True)
    return text or None


def _lower_or_none(value: str | None) -> str | None:
    return value.casefold() if value else None


def _display_title(title: str) -> str:
    return title.split(":", 1)[1] if title.startswith("Slay the Spire 2:") else title


def _extract_card_sentence(wikitext: str) -> str:
    text = clean_text(wikitext)
    gives_match = re.search(r"(?:It|They|This card) .+?(?:\.\s|$)", text)
    if gives_match:
        return gives_match.group(0).strip()
    match = re.search(r"\b is a[n]? .+?(?:\.\s|$)", text)
    if not match:
        return ""
    sentence = match.group(0).strip()
    return sentence[1:].strip() if sentence.startswith(" ") else sentence


def _infer_fields_from_sentence(sentence: str) -> dict[str, str]:
    out: dict[str, str] = {}
    cost_match = re.search(r"is a[n]? ([Xx0-9]+) .*? cost", sentence)
    if cost_match:
        out["cost"] = cost_match.group(1)
    rarity_match = re.search(r"cost ([A-Za-z]+) ([A-Za-z]+) Card", sentence)
    if rarity_match:
        out["rarity"] = rarity_match.group(1)
        out["card_type"] = rarity_match.group(2)
    character_match = re.search(r"Card for the ([A-Za-z ]+?)\.", sentence)
    if character_match:
        out["character"] = character_match.group(1)
    return out


def _infer_fields_from_templates(wikitext: str) -> dict[str, str]:
    out: dict[str, str] = {}
    parsed = mwparserfromhell.parse(wikitext)
    for template in parsed.filter_templates(recursive=True):
        name = str(template.name).strip().casefold()
        parts = [clean_text(p.value) for p in template.params]
        if name == "querylink" and len(parts) >= 3:
            query = parts[1].casefold()
            value = parts[2]
            if "rarity:" in query:
                out["rarity"] = value
            if "type:" in query:
                out["card_type"] = value
        elif name == "kw" and parts:
            value = parts[0]
            if value.casefold() in {"ironclad", "silent", "defect", "watcher", "necrobinder"}:
                out["character"] = value
        elif name == "icon" and parts and "cost" not in out:
            # Cost is usually the plain number immediately before the Icon template
            before = str(wikitext).split(str(template), 1)[0]
            match = re.search(r"is a[n]? ([Xx0-9]+)\s*$", clean_text(before))
            if match:
                out["cost"] = match.group(1)
    return out


def _extract_mechanics(description: str, upgraded: str | None) -> list[str]:
    haystack = f"{description} {upgraded or ''}".casefold()
    known = [
        "block",
        "poison",
        "intangible",
        "strength",
        "dexterity",
        "vulnerable",
        "weak",
        "draw",
        "discard",
        "exhaust",
    ]
    return [term for term in known if term in haystack]


def _extract_mechanics_from_templates(wikitext: str) -> list[str]:
    mechanics: list[str] = []
    parsed = mwparserfromhell.parse(wikitext)
    for template in parsed.filter_templates(recursive=True):
        if str(template.name).strip().casefold() != "kw" or not template.params:
            continue
        value = clean_text(template.params[0].value).casefold()
        if value not in {"ironclad", "silent", "defect", "watcher", "necrobinder"}:
            mechanics.append(value)
    return mechanics


def _merge_mechanics(*groups: list[str]) -> list[str]:
    out: list[str] = []
    for group in groups:
        for item in group:
            if item and item not in out:
                out.append(item)
    return out


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
