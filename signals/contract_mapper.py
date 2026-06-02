import json
from pathlib import Path
from typing import Any


class ContractMapper:
    def __init__(self, map_path: str = "data/contract_equity_map.json") -> None:
        self._map: dict[str, Any] = json.loads(Path(map_path).read_text())

    def get_basket(self, contract_slug: str) -> dict | None:
        if contract_slug in self._map:
            return self._map[contract_slug]
        for key, value in self._map.items():
            if contract_slug.startswith(key):
                return value
        return None

    def get_all_slugs(self) -> list[str]:
        return list(self._map.keys())
