import json
from pathlib import Path

import pytest

from signals.contract_mapper import ContractMapper


@pytest.fixture
def map_file(tmp_path: Path) -> Path:
    data = {
        "KXFED": {
            "description": "Fed rate decision",
            "direction": "up",
            "basket": ["JPM", "BAC"],
            "sector_etf": "XLF",
            "confidence": 0.9,
        },
        "KXCPI": {
            "description": "CPI release",
            "direction": "down",
            "basket": ["TLT", "GLD"],
            "sector_etf": "TLT",
            "confidence": 0.85,
        },
    }
    p = tmp_path / "map.json"
    p.write_text(json.dumps(data))
    return p


def test_exact_match(map_file: Path) -> None:
    mapper = ContractMapper(str(map_file))
    result = mapper.get_basket("KXFED")
    assert result is not None
    assert result["basket"] == ["JPM", "BAC"]


def test_prefix_match(map_file: Path) -> None:
    mapper = ContractMapper(str(map_file))
    result = mapper.get_basket("KXFED-25JAN29")
    assert result is not None
    assert result["basket"] == ["JPM", "BAC"]


def test_no_match_returns_none(map_file: Path) -> None:
    mapper = ContractMapper(str(map_file))
    assert mapper.get_basket("KXBTC-25DEC31") is None


def test_get_all_slugs(map_file: Path) -> None:
    mapper = ContractMapper(str(map_file))
    assert set(mapper.get_all_slugs()) == {"KXFED", "KXCPI"}


def test_direction_field(map_file: Path) -> None:
    mapper = ContractMapper(str(map_file))
    assert mapper.get_basket("KXCPI")["direction"] == "down"


def test_confidence_field(map_file: Path) -> None:
    mapper = ContractMapper(str(map_file))
    assert mapper.get_basket("KXFED")["confidence"] == pytest.approx(0.9)
