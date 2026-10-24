"""
Downloads real historical OHLC data for each market in markets.MARKETS from
Yahoo Finance's public chart API and saves it as CSV under data/raw/<code>/.
When CSVs already exist, only a recent window is fetched and merged into them;
older downloaded data is preserved.

Yahoo enforces limits on how far back intraday intervals go, so we pull five
layers at the finest resolution each allows:
  - daily   ("1d")  -> last 2 years   (long history for gap / day-of-week stats)
  - hourly  ("60m") -> last 2 years   (Yahoo's max window for 60m bars)
  - 15-min  ("15m") -> last 60 days   (Yahoo's max window for 15m bars)
  - 5-min   ("5m")  -> last 60 days   (Yahoo's max window for 5m bars)
  - 1-min   ("1m")  -> last 7 days    (Yahoo's max window for 1m bars; this is
                                        also aggregated into real 3-min bars in
                                        build_sessions.py, since Yahoo has no
                                        native 3m interval)

No API key needed, but Yahoo blocks the default python-requests user agent, so
we send a browser-like User-Agent header.
"""
import json
import time
from pathlib import Path

import pandas as pd
import requests

from markets import MARKETS

RAW_DIR = Path(__file__).parent / "raw"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"


def fetch_range(ticker: str, range_: str, interval: str) -> pd.DataFrame:
    params = {"range": range_, "interval": interval, "includePrePost": "false"}
    resp = requests.get(
        CHART_URL.format(ticker=ticker), params=params, headers=HEADERS, timeout=20
    )
    resp.raise_for_status()
    payload = resp.json()

    result = payload.get("chart", {}).get("result")
    if not result:
        err = payload.get("chart", {}).get("error")
        raise RuntimeError(f"Yahoo returned no data for {ticker} ({range_}/{interval}): {err}")

    result = result[0]
    timestamps = result.get("timestamp")
    if not timestamps:
        raise RuntimeError(f"No timestamps for {ticker} ({range_}/{interval})")

    quote = result["indicators"]["quote"][0]
    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": quote["open"],
            "high": quote["high"],
            "low": quote["low"],
            "close": quote["close"],
            "volume": quote["volume"],
        }
    )
    df = df.dropna(subset=["open", "high", "low", "close"])
    df["datetime_utc"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)

    tz = result["meta"].get("exchangeTimezoneName", "America/New_York")
    df["datetime_local"] = df["datetime_utc"].dt.tz_convert(tz)
    df = df.sort_values("datetime_local").reset_index(drop=True)
    return df


def merge_with_existing(incoming: pd.DataFrame, path: Path) -> pd.DataFrame:
    """Merge refreshed bars into an existing file, keeping older history."""
    if not path.exists():
        return incoming

    existing = pd.read_csv(path)
    combined = pd.concat([existing, incoming], ignore_index=True)
    combined = combined.drop_duplicates(subset=["timestamp"], keep="last")
    combined["datetime_utc"] = pd.to_datetime(combined["datetime_utc"], utc=True)
    combined["datetime_local"] = pd.to_datetime(combined["datetime_local"], utc=True)
    return combined.sort_values("datetime_utc").reset_index(drop=True)


def fetch_market(code: str, ticker: str) -> dict:
    out_dir = RAW_DIR / code
    out_dir.mkdir(parents=True, exist_ok=True)

    # The short refresh windows include the previous trading day while
    # avoiding a full re-download. Existing CSVs are merged below.
    jobs = [
        ("daily", "2y", "3d", "1d"),
        ("hourly", "2y", "3d", "60m"),
        ("15min", "60d", "3d", "15m"),
        ("5min", "60d", "3d", "5m"),
        ("1min", "7d", "7d", "1m"),
    ]

    manifest = {}
    for name, initial_range, refresh_range, interval in jobs:
        out_path = out_dir / f"{name}.csv"
        range_ = refresh_range if out_path.exists() else initial_range
        print(f"  {code} ({ticker}) {name} ({range_} @ {interval})...")
        df = fetch_range(ticker, range_, interval)
        df = merge_with_existing(df, out_path)
        df.to_csv(out_path, index=False)
        manifest[name] = {
            "rows": len(df),
            "start": str(df["datetime_local"].min()),
            "end": str(df["datetime_local"].max()),
            "file": out_path.name,
        }
        print(f"    -> {len(df)} rows, {df['datetime_local'].min()} .. {df['datetime_local'].max()}")
        time.sleep(1)  # be polite to Yahoo's endpoint

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main():
    all_manifests = {}
    for code, info in MARKETS.items():
        print(f"Fetching {code} - {info['name']}...")
        all_manifests[code] = fetch_market(code, info["yahoo_ticker"])

    print("\nDone. Manifest:")
    print(json.dumps(all_manifests, indent=2))


if __name__ == "__main__":
    main()
