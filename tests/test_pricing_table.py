from pathlib import Path

import pytest

from spiresight.core.usage import PricingTable, TokenUsage


def _write_yaml(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_load_valid_yaml(tmp_path: Path):
    p = _write_yaml(tmp_path / "prices.yaml", """
gpt-4o:
  input_per_1m: 2.50
  output_per_1m: 10.00
gpt-4o-mini:
  input_per_1m: 0.15
  output_per_1m: 0.60
""")
    table = PricingTable.load(p)
    cost = table.compute("gpt-4o", TokenUsage(1_000_000, 1_000_000))
    assert cost == pytest.approx(12.50)


def test_compute_returns_none_for_unknown_model(tmp_path: Path):
    p = _write_yaml(tmp_path / "prices.yaml", """
gpt-4o:
  input_per_1m: 2.50
  output_per_1m: 10.00
""")
    table = PricingTable.load(p)
    assert table.compute("mystery-model", TokenUsage(100, 100)) is None


def test_compute_math(tmp_path: Path):
    p = _write_yaml(tmp_path / "prices.yaml", """
m:
  input_per_1m: 5.00
  output_per_1m: 15.00
""")
    table = PricingTable.load(p)
    cost = table.compute("m", TokenUsage(2_000_000, 1_000_000))
    assert cost == pytest.approx(2_000_000 / 1_000_000 * 5.00 + 1_000_000 / 1_000_000 * 15.00)
    assert cost == pytest.approx(25.00)


def test_load_missing_file_returns_empty_table(tmp_path: Path):
    table = PricingTable.load(tmp_path / "nonexistent.yaml")
    assert table.compute("gpt-4o", TokenUsage(100, 100)) is None


def test_load_malformed_yaml_returns_empty_table(tmp_path: Path):
    p = _write_yaml(tmp_path / "bad.yaml", ": ::: not yaml ::: :")
    table = PricingTable.load(p)
    assert table.compute("gpt-4o", TokenUsage(100, 100)) is None


def test_invalid_entries_are_skipped_but_valid_ones_kept(tmp_path: Path):
    p = _write_yaml(tmp_path / "mixed.yaml", """
good:
  input_per_1m: 1.0
  output_per_1m: 2.0
bad_missing_key:
  input_per_1m: 1.0
bad_negative:
  input_per_1m: -1.0
  output_per_1m: 2.0
bad_string_value:
  input_per_1m: "not a number"
  output_per_1m: 2.0
""")
    table = PricingTable.load(p)
    assert table.compute("good", TokenUsage(1_000_000, 0)) == pytest.approx(1.0)
    assert table.compute("bad_missing_key", TokenUsage(100, 100)) is None
    assert table.compute("bad_negative", TokenUsage(100, 100)) is None
    assert table.compute("bad_string_value", TokenUsage(100, 100)) is None


def test_zero_tokens_returns_zero_cost(tmp_path: Path):
    p = _write_yaml(tmp_path / "p.yaml", """
m:
  input_per_1m: 5.0
  output_per_1m: 15.0
""")
    table = PricingTable.load(p)
    assert table.compute("m", TokenUsage(0, 0)) == 0.0
