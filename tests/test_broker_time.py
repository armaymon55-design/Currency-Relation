import pandas as pd

from src.data.broker_time import server_to_utc, utc_to_server


def _server_epoch(wall: str) -> int:
    """Epoch seconds for a server wall-clock time, labelled as UTC the way MT5 does."""
    return int(pd.Timestamp(wall).tz_localize("UTC").timestamp())


def test_summer_is_utc_plus_3():
    utc = server_to_utc([_server_epoch("2026-09-17 01:00")])[0]
    assert utc == pd.Timestamp("2026-09-16 22:00", tz="UTC")


def test_winter_is_utc_plus_2():
    utc = server_to_utc([_server_epoch("2026-01-15 01:00")])[0]
    assert utc == pd.Timestamp("2026-01-14 23:00", tz="UTC")


def test_vectorised_mixed_seasons():
    idx = server_to_utc([_server_epoch("2026-01-15 01:00"), _server_epoch("2026-09-17 01:00")])
    assert list(idx.hour) == [23, 22]
    assert str(idx.tz) == "UTC"


def test_roundtrip():
    utc = pd.Timestamp("2026-09-16 22:00", tz="UTC")
    server = utc_to_server(utc)
    assert (server.hour, server.day) == (1, 17)
    assert server_to_utc([int(server.timestamp())])[0] == utc
