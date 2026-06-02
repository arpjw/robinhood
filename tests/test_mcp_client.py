import json
from pathlib import Path

import pytest

import execution.mcp_client as module
from execution.mcp_client import LiveMCPClient, MockMCPClient


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MockMCPClient:
    monkeypatch.setattr(module, "ORDER_LOG_PATH", tmp_path / "orders.jsonl")
    return MockMCPClient()


def test_submit_order_returns_required_fields(client: MockMCPClient) -> None:
    order = client.submit_order("AAPL", "buy", 100.0, "s1")
    assert order["ticker"] == "AAPL"
    assert order["side"] == "buy"
    assert order["size"] == 100.0
    assert order["strategy_id"] == "s1"
    assert order["status"] == "filled"
    assert order["mode"] == "mock"
    assert "id" in order
    assert "timestamp" in order


def test_submit_order_logs_to_file(
    client: MockMCPClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path = tmp_path / "orders.jsonl"
    monkeypatch.setattr(module, "ORDER_LOG_PATH", log_path)
    fresh = MockMCPClient()
    fresh.submit_order("TSLA", "buy", 50.0, "s2")
    assert log_path.exists()
    record = json.loads(log_path.read_text().strip())
    assert record["ticker"] == "TSLA"


def test_buy_adds_position(client: MockMCPClient) -> None:
    client.submit_order("AAPL", "buy", 100.0, "s1")
    positions = client.get_positions()
    assert len(positions) == 1
    assert positions[0]["ticker"] == "AAPL"


def test_sell_removes_position(client: MockMCPClient) -> None:
    client.submit_order("AAPL", "buy", 100.0, "s1")
    client.submit_order("AAPL", "sell", 100.0, "s1")
    assert client.get_positions() == []


def test_sell_without_position_is_noop(client: MockMCPClient) -> None:
    client.submit_order("AAPL", "sell", 100.0, "s1")
    assert client.get_positions() == []


def test_get_positions_multiple(client: MockMCPClient) -> None:
    client.submit_order("AAPL", "buy", 100.0, "s1")
    client.submit_order("GOOG", "buy", 200.0, "s1")
    assert len(client.get_positions()) == 2


def test_cancel_all_removes_strategy_positions(client: MockMCPClient) -> None:
    client.submit_order("AAPL", "buy", 100.0, "s1")
    client.submit_order("GOOG", "buy", 200.0, "s1")
    client.submit_order("TSLA", "buy", 300.0, "s2")
    removed = client.cancel_all("s1")
    assert removed == 2
    positions = client.get_positions()
    assert len(positions) == 1
    assert positions[0]["ticker"] == "TSLA"


def test_cancel_all_returns_zero_when_no_match(client: MockMCPClient) -> None:
    client.submit_order("AAPL", "buy", 100.0, "s1")
    assert client.cancel_all("nonexistent") == 0
    assert len(client.get_positions()) == 1


def test_make_client_raises_for_live_mode_without_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXECUTION_MODE", "live")
    monkeypatch.delenv("ROBINHOOD_MCP_URL", raising=False)
    with pytest.raises(RuntimeError, match="ROBINHOOD_MCP_URL"):
        module.make_client()


def test_make_client_returns_live_client_when_url_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXECUTION_MODE", "live")
    monkeypatch.setenv("ROBINHOOD_MCP_URL", "https://agent.robinhood.com/mcp/trading")
    client = module.make_client()
    assert isinstance(client, LiveMCPClient)


def test_make_client_returns_mock_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EXECUTION_MODE", raising=False)
    client = module.make_client()
    assert isinstance(client, MockMCPClient)
