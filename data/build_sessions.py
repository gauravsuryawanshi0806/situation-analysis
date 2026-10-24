"""
Turns each market's raw Yahoo Finance CSVs (daily / hourly / 15min / 5min /
1min, under data/raw/<code>/) into a per-session feature table plus a
multi-resolution intraday-bars table, stored together in one SQLite database
(data/sessions.db) with a `market` column distinguishing rows.

Session features (one row per trading day per market), computed from real
data:
  - gap_pct, gap_dir       : session open vs prior session close
  - open_vs_prior          : session open vs prior day's high/low range
  - day_of_week
  - prior_high/low/close, session_open, day_high/low/close
    - first5_dir               : direction of the first 5-min bar
    - first15_dir/second15_dir : direction of the first two 15-min bars
                                (only available for the last ~60 days, since
                                that's the deepest 15m history Yahoo exposes)
  - bars_resolution        : finest resolution available for this session's
                              chart (see available_resolutions)
  - available_resolutions  : comma-separated, finest-first list of the
                              resolutions actually stored in `bars` for this
                              session -- e.g. "3min,5min,15min,60m" for a
                              session in the last week, just "60m" for one
                              older than ~60 days. 3min bars are REAL data:
                              Yahoo has no native 3-minute interval, so they
                              are aggregated (first/max/min/last) from Yahoo's
                              own 1-minute bars, which only go back 7 days.
  - is_complete            : false for still-forming/half days (hourly bar
                              count well below that market's typical
                              full-session count)
"""
import sqlite3
from pathlib import Path

import pandas as pd

from markets import MARKETS

RAW_DIR = Path(__file__).parent / "raw"
DB_PATH = Path(__file__).parent / "sessions.db"

FLAT_GAP_THRESHOLD_PCT = 0.05  # |gap| below this is classified "flat"
COMPLETE_BAR_RATIO = 0.85  # a day needs at least this fraction of the market's typical full bar count
MIN_BARS_FOR_RESOLUTION = 2  # need at least this many bars to consider a resolution "available" for a day

# finest-first; must match the keys used in build_market()'s `lookups` dict
RESOLUTIONS_FINEST_FIRST = ["3min", "5min", "15min", "60m"]


def _load_one(market_dir: Path, name: str, tz: str) -> pd.DataFrame:
    df = pd.read_csv(market_dir / f"{name}.csv")
    # datetime_local strings carry mixed UTC offsets (daylight saving), so
    # parse as UTC first and then convert back to the exchange's local zone.
    df["datetime_local"] = pd.to_datetime(df["datetime_local"], utc=True).dt.tz_convert(tz)
    df["date"] = df["datetime_local"].dt.date
    return df


def _resample_to_3min(m1: pd.DataFrame) -> pd.DataFrame:
    """Aggregate real 1-min bars into real 3-min bars (first/max/min/last).
    Yahoo has no native 3m interval, but this is standard OHLC aggregation of
    genuine 1-min prints, not synthetic/estimated data."""
    if m1.empty:
        return m1.copy()
    agg = (
        m1.set_index("datetime_local")
        .resample("3min")
        .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
        .dropna()
        .reset_index()
    )
    agg["date"] = agg["datetime_local"].dt.date
    return agg


def load_raw(code: str):
    market_dir = RAW_DIR / code
    tz = MARKETS[code]["tz"]
    daily = _load_one(market_dir, "daily", tz)
    hourly = _load_one(market_dir, "hourly", tz)
    m15 = _load_one(market_dir, "15min", tz)
    m5 = _load_one(market_dir, "5min", tz)
    m1 = _load_one(market_dir, "1min", tz)
    m3 = _resample_to_3min(m1)
    return daily, hourly, m15, m5, m3


def add_missing_daily_sessions(daily: pd.DataFrame, hourly: pd.DataFrame) -> pd.DataFrame:
    """Fill daily-feed gaps with OHLC aggregated from the hourly feed.

    Yahoo can publish recent intraday bars before the corresponding daily bar,
    especially for cash indices. The session builder needs a daily row for
    its feature calculations, so use hourly data as a fallback for missing
    dates. Completeness is still decided separately from the hourly bar count.
    """
    missing_dates = sorted(set(hourly["date"]) - set(daily["date"]))
    if not missing_dates:
        return daily

    fallback_rows = []
    for date in missing_dates:
        group = hourly[hourly["date"] == date].sort_values("datetime_local")
        if group.empty:
            continue
        first = group.iloc[0]
        fallback_rows.append(
            {
                "timestamp": first["timestamp"],
                "open": first["open"],
                "high": group["high"].max(),
                "low": group["low"].min(),
                "close": group.iloc[-1]["close"],
                "volume": group["volume"].sum(),
                "datetime_utc": first["datetime_utc"],
                "datetime_local": first["datetime_local"],
                "date": date,
            }
        )

    if not fallback_rows:
        return daily
    return pd.concat([daily, pd.DataFrame(fallback_rows)], ignore_index=True)


def classify_gap(gap_pct: float) -> str:
    if gap_pct > FLAT_GAP_THRESHOLD_PCT:
        return "up"
    if gap_pct < -FLAT_GAP_THRESHOLD_PCT:
        return "down"
    return "flat"


def classify_open_vs_prior(open_: float, prior_high: float, prior_low: float) -> str:
    if open_ > prior_high:
        return "above_prior_high"
    if open_ < prior_low:
        return "below_prior_low"
    return "inside_range"


def bar_direction(open_: float, close: float) -> str:
    if close > open_:
        return "positive"
    if close < open_:
        return "negative"
    return "flat"


def build_intraday_lookup(df: pd.DataFrame) -> dict:
    lookup = {}
    for date, group in df.groupby("date"):
        group = group.sort_values("datetime_local")
        lookup[date] = group
    return lookup


def typical_bar_count(lookup: dict) -> int:
    """The most common per-day bar count, i.e. what a normal full session looks
    like for this market/resolution. Used to spot still-forming or half days
    without hardcoding a market-specific local closing hour (Yahoo labels
    intraday bars by bucket *start* time, and bucket boundaries differ enough
    between markets -- e.g. DAX's last hourly bar starts at 16:00-17:00, while
    a US index's last bar starts at 15:30 -- that a fixed hour threshold silently
    breaks for some markets)."""
    if not lookup:
        return 0
    counts = pd.Series([len(v) for v in lookup.values()])
    return int(counts.mode().iloc[0])


def build_market(code: str):
    daily, hourly, m15, m5, m3 = load_raw(code)
    daily = add_missing_daily_sessions(daily, hourly)
    daily = daily.sort_values("datetime_local").reset_index(drop=True)

    lookups = {
        "3min": build_intraday_lookup(m3),
        "5min": build_intraday_lookup(m5),
        "15min": build_intraday_lookup(m15),
        "60m": build_intraday_lookup(hourly),
    }
    hourly_typical = typical_bar_count(lookups["60m"])

    sessions = []
    bars_rows = []

    for i in range(1, len(daily)):
        today = daily.iloc[i]
        prior = daily.iloc[i - 1]

        date = today["date"]
        prior_close = float(prior["close"])
        prior_high = float(prior["high"])
        prior_low = float(prior["low"])
        session_open = float(today["open"])

        gap_pct = (session_open - prior_close) / prior_close * 100.0
        gap_dir = classify_gap(gap_pct)
        open_vs_prior = classify_open_vs_prior(session_open, prior_high, prior_low)

        available = []
        for res in RESOLUTIONS_FINEST_FIRST:
            group = lookups[res].get(date)
            if group is not None and len(group) >= MIN_BARS_FOR_RESOLUTION:
                available.append(res)
                for _, bar in group.iterrows():
                    bars_rows.append(
                        {
                            "market": code,
                            "date": str(date),
                            "resolution": res,
                            "ts": bar["datetime_local"].isoformat(),
                            "open": float(bar["open"]),
                            "high": float(bar["high"]),
                            "low": float(bar["low"]),
                            "close": float(bar["close"]),
                        }
                    )

        bars_resolution = available[0] if available else None

        first5_dir = None
        m5_group = lookups["5min"].get(date)
        if m5_group is not None and len(m5_group) >= 1:
            first5 = m5_group.iloc[0]
            first5_dir = bar_direction(float(first5["open"]), float(first5["close"]))

        first15_dir = second15_dir = None
        m15_group = lookups["15min"].get(date)
        if m15_group is not None and len(m15_group) >= 2:
            b1, b2 = m15_group.iloc[0], m15_group.iloc[1]
            first15_dir = bar_direction(float(b1["open"]), float(b1["close"]))
            second15_dir = bar_direction(float(b2["open"]), float(b2["close"]))

        hourly_group = lookups["60m"].get(date)
        is_complete = bool(
            hourly_group is not None
            and len(hourly_group) > 0
            and hourly_typical > 0
            and len(hourly_group) >= COMPLETE_BAR_RATIO * hourly_typical
        )

        sessions.append(
            {
                "market": code,
                "date": str(date),
                "day_of_week": today["datetime_local"].strftime("%A"),
                "gap_pct": round(gap_pct, 4),
                "gap_dir": gap_dir,
                "open_vs_prior": open_vs_prior,
                "prior_high": prior_high,
                "prior_low": prior_low,
                "prior_close": prior_close,
                "session_open": session_open,
                "day_high": float(today["high"]),
                "day_low": float(today["low"]),
                "day_close": float(today["close"]),
                "first15_dir": first15_dir,
                "second15_dir": second15_dir,
                "first5_dir": first5_dir,
                "bars_resolution": bars_resolution,
                "available_resolutions": ",".join(available),
                "is_complete": is_complete,
            }
        )

    return pd.DataFrame(sessions), pd.DataFrame(bars_rows)


def main():
    all_sessions = []
    all_bars = []

    for code in MARKETS:
        print(f"Building sessions for {code}...")
        sessions_df, bars_df = build_market(code)
        all_sessions.append(sessions_df)
        all_bars.append(bars_df)
        counts = {
            res: int(sessions_df["available_resolutions"].str.contains(res).sum())
            for res in RESOLUTIONS_FINEST_FIRST
        }
        print(f"  {len(sessions_df)} sessions | " + " | ".join(f"{r}: {c}" for r, c in counts.items()))

    sessions_df = pd.concat(all_sessions, ignore_index=True)
    bars_df = pd.concat(all_bars, ignore_index=True)

    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    sessions_df.to_sql("sessions", conn, index=False)
    bars_df.to_sql("bars", conn, index=False)
    conn.execute("CREATE INDEX idx_sessions_market_date ON sessions(market, date)")
    conn.execute("CREATE INDEX idx_bars_market_date_res ON bars(market, date, resolution)")
    conn.commit()
    conn.close()

    print(f"\nBuilt {len(sessions_df)} total sessions across {len(MARKETS)} markets -> {DB_PATH}")
    print(f"Total intraday bars stored: {len(bars_df)}")


if __name__ == "__main__":
    main()
