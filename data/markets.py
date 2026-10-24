"""Shared market registry: our internal code -> display name + Yahoo Finance ticker."""

MARKETS = {
    "DAX40": {"name": "DAX 40", "yahoo_ticker": "^GDAXI", "tz": "Europe/Berlin"},
    "GOLD_F": {"name": "Gold Futures (GC)", "yahoo_ticker": "GC=F", "tz": "America/New_York"},
    "JAPAN225": {"name": "Japan 225 (Nikkei)", "yahoo_ticker": "^N225", "tz": "Asia/Tokyo"},
    "NIKKEI_F": {"name": "Nikkei Futures", "yahoo_ticker": "NKD=F", "tz": "Europe/Berlin"},
    "UK100": {"name": "FTSE 100 (UK100)", "yahoo_ticker": "^FTSE", "tz": "Europe/London"},
    "US30": {"name": "Dow Jones (Wall Street 30)", "yahoo_ticker": "^DJI", "tz": "America/New_York"},
    "US100": {"name": "Nasdaq (US Tech 100)", "yahoo_ticker": "^NDX", "tz": "America/New_York"},
    "YM_F": {"name": "Dow Jones Futures (YM)", "yahoo_ticker": "YM=F", "tz": "America/New_York"},
    "NQ_F": {"name": "US Tech 100 Futures (NQ)", "yahoo_ticker": "NQ=F", "tz": "America/New_York"},
    # No DAX 40 futures entry: Yahoo Finance does not host real Eurex FDAX
    # futures data under any ticker (verified -- "DAX=F" is an unrelated
    # NYMEX instrument, and Yahoo's own symbol search only returns leveraged
    # ETN products, not the futures contract). Use DAX40 (cash index) above,
    # or add an entry here if you have another data source for it.
}
