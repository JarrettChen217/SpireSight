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


def slugify(name: str) -> str:
    slug = normalize_query(name).replace(" ", "_")
    return slug or "unknown"


def clean_text(value: Any) -> str:
    text = mwparserfromhell.parse(str(value)).strip_code() if value is not None else ""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


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

    name = fields.get("name") or title
    description = fields.get("description") or fields.get("text") or ""
    upgraded = (
        fields.get("upgrade")
        or fields.get("upgraded_description")
        or fields.get("upgraded description")
    )
    return CardKnowledge(
        id=slugify(name),
        name_en=name,
        aliases=[],
        character=_lower_or_none(fields.get("character")),
        rarity=_lower_or_none(fields.get("rarity")),
        card_type=_lower_or_none(fields.get("type") or fields.get("card_type")),
        cost=fields.get("cost") or None,
        description=description,
        upgraded_description=upgraded or None,
        mechanics=_extract_mechanics(description, upgraded),
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
        titles = _fetch_category_titles(client)
        cards: list[CardKnowledge] = []
        for title in titles:
            source_url = f"https://slaythespire.wiki.gg/wiki/{title.replace(' ', '_')}"
            try:
                wikitext = _fetch_wikitext(client, title)
                cards.append(
                    parse_card_wikitext(
                        title=title,
                        wikitext=wikitext,
                        source_url=source_url,
                        fetched_at=fetched_at,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{title}: wikitext failed ({exc}); trying html")
                html = client.get(source_url).text
                cards.append(
                    parse_card_html(
                        title=title,
                        html=html,
                        source_url=source_url,
                        fetched_at=fetched_at,
                    )
                )
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
        "action": "query",
        "prop": "revisions",
        "rvprop": "content",
        "rvslots": "main",
        "titles": title,
        "format": "json",
    }
    data = client.get(API_URL, params=params).json()
    pages = data.get("query", {}).get("pages", {})
    page = next(iter(pages.values()))
    revisions = page.get("revisions", [])
    return revisions[0]["slots"]["main"]["*"]


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


if __name__ == "__main__":
    raise SystemExit(main())
