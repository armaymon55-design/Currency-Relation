"""The data client attaches to a real trading account. It must never be able to trade."""
from pathlib import Path

FORBIDDEN = [
    "order_send", "order_check", "order_calc", "positions_get", "positions_total",
    "history_orders", "history_deals", "TRADE_ACTION", "ORDER_TYPE",
]


def test_mt5_client_has_no_trading_calls():
    src = (Path(__file__).resolve().parents[1] / "src" / "data" / "mt5_client.py").read_text(encoding="utf-8")
    hits = [word for word in FORBIDDEN if word in src.replace("tests/test_readonly.py", "")]
    assert not hits, f"trading calls found in the read-only client: {hits}"
