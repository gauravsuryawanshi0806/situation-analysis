"""
Situational Analysis backend.

Serves the pre-built multi-market session dataset (data/sessions.db, produced
by data/fetch_data.py + data/build_sessions.py) through a small JSON API, and
serves the static frontend from ../frontend.

Run with:
    uvicorn app.main:app --reload --port 8000
from the situational-analysis/ directory.
"""
from pathlib import Path
from io import StringIO
from typing import Any, Dict, List, Optional
import csv

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from app.analysis import (
    STOP_LOSS_POINTS,
    compute_session_metrics,
    compute_similarity,
    compute_srs_metrics,
    compute_stop_loss_metrics,
)
from app.db import get_conn
from app.journal import (
    CSV_FIELDS,
    JournalTradeInput,
    _safe_csv_value,
    create_trade,
    read_trades,
    update_trade,
)
from data.markets import MARKETS
from data.economic_events import ECONOMIC_EVENTS

APP_DIR = Path(__file__).parent
FRONTEND_DIR = APP_DIR.parent / "frontend"

app = FastAPI(title="Situational Analysis API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DEFAULT_MARKET = "DAX40"
RESOLUTIONS_FINEST_FIRST = ["3min", "5min", "15min", "60m"]

# date string -> list of event codes ("CPI", "FOMC") that fall on that date
EVENTS_BY_DATE: dict[str, list[str]] = {}
for _code, _info in ECONOMIC_EVENTS.items():
    for _d in _info["dates"]:
        EVENTS_BY_DATE.setdefault(_d, []).append(_code)


def validate_market(market: str) -> str:
    if market not in MARKETS:
        raise HTTPException(status_code=404, detail=f"Unknown market '{market}'. Known: {list(MARKETS)}")
    return market


def load_sessions_df(market: str) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql("SELECT * FROM sessions WHERE market = ?", conn, params=(market,))
    conn.close()
    df["date"] = pd.to_datetime(df["date"])
    df["is_complete"] = df["is_complete"].astype(bool)
    return df.sort_values("date").reset_index(drop=True)


def load_bars(market: str, date: str, resolution: Optional[str] = None) -> list[dict]:
    conn = get_conn()
    q = "SELECT * FROM bars WHERE market = ? AND date = ?"
    params = [market, date]
    if resolution:
        q += " AND resolution = ?"
        params.append(resolution)
    q += " ORDER BY ts"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    bars = [dict(r) for r in rows]
    if market == "NIKKEI_F":
        cutoff_minutes = 1 * 60 + 30
        bars = [
            bar
            for bar in bars
            if (
                lambda local_ts: local_ts.hour * 60 + local_ts.minute >= cutoff_minutes
            )(pd.to_datetime(bar["ts"]).tz_convert("Europe/Berlin"))
        ]
    return bars


def load_bars_range(
    market: str, end_date: str, resolution: str, days: int = 60
) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT * FROM bars
        WHERE market = ?
          AND resolution = ?
          AND date >= date(?, ?)
          AND date <= ?
        ORDER BY ts
        """,
        (market, resolution, end_date, f"-{days - 1} days", end_date),
    ).fetchall()
    conn.close()
    bars = [dict(row) for row in rows]
    if market == "NIKKEI_F":
        cutoff_minutes = 1 * 60 + 30
        bars = [
            bar
            for bar in bars
            if (
                lambda local_ts: local_ts.hour * 60 + local_ts.minute >= cutoff_minutes
            )(pd.to_datetime(bar["ts"]).tz_convert("Europe/Berlin"))
        ]
    return bars


def clean(v):
    """pandas read_sql returns NULLs as NaN even in object columns; JSON can't encode NaN."""
    return None if pd.isna(v) else v


def session_row_to_dict(row) -> dict:
    date_value = pd.to_datetime(row["date"])
    date_text = date_value.strftime("%Y-%m-%d")
    return {
        "market": row["market"],
        "date": date_text,
        "day_of_week": row["day_of_week"],
        "gap_pct": row["gap_pct"],
        "gap_dir": row["gap_dir"],
        "open_vs_prior": row["open_vs_prior"],
        "prior_high": row["prior_high"],
        "prior_low": row["prior_low"],
        "prior_close": row["prior_close"],
        "session_open": row["session_open"],
        "day_high": row["day_high"],
        "day_low": row["day_low"],
        "day_close": row["day_close"],
        "first15_dir": clean(row["first15_dir"]),
        "second15_dir": clean(row["second15_dir"]),
        "first5_dir": clean(row["first5_dir"]),
        "bars_resolution": clean(row["bars_resolution"]),
        "available_resolutions": row["available_resolutions"].split(",") if row["available_resolutions"] else [],
        "is_complete": bool(row["is_complete"]),
        "economic_events": EVENTS_BY_DATE.get(date_text, []),
    }


def get_reference_row(market: str, reference_date: Optional[str]):
    if not reference_date:
        return None
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM sessions WHERE market = ? AND date = ?",
        (market, reference_date),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return session_row_to_dict(row)


def build_strategy_lines(market: str, strategy_bars: list[dict]) -> list[dict]:
    if market in {"DAX40", "JAPAN225", "NIKKEI_F", "US30", "US100"}:
        if len(strategy_bars) < 2:
            return []
        reference_bar = strategy_bars[1]
        return [
            {"price": reference_bar["high"], "title": "SRS Long", "color": "#16a34a"},
            {"price": reference_bar["low"], "title": "SRS Short", "color": "#dc2626"},
        ]
    if market == "UK100":
        if not strategy_bars:
            return []
        first_bar = strategy_bars[0]
        if first_bar["close"] == first_bar["open"]:
            return []
        first_bar_direction = "positive" if first_bar["close"] > first_bar["open"] else "negative"
        if first_bar_direction == "positive":
            return [{"price": first_bar["low"], "title": "FTSE Negative", "color": "#dc2626"}]
        return [{"price": first_bar["high"], "title": "FTSE Positive", "color": "#16a34a"}]
    return []


def attach_analysis(reference: Optional[dict], item: dict, bars: Optional[List[dict]] = None) -> dict:
    metrics = compute_session_metrics(item, bars)
    item["session_metrics"] = metrics
    if reference:
        similarity = compute_similarity(reference, item)
        item["match_score"] = similarity["score"]
        item["match_breakdown"] = similarity["matched_fields"]
    else:
        item["match_score"] = None
        item["match_breakdown"] = {}
    return item


@app.get("/api/markets")
def get_markets():
    return [
        {"code": code, "name": info["name"], "yahoo_ticker": info["yahoo_ticker"]}
        for code, info in MARKETS.items()
    ]


@app.get("/api/economic-events")
def get_economic_events():
    return {
        code: {"label": info["label"], "count": len(info["dates"]), "dates": info["dates"]}
        for code, info in ECONOMIC_EVENTS.items()
    }


@app.get("/api/analysis/friday-monday")
def get_friday_monday_analysis(
    market: str = Query(DEFAULT_MARKET),
    friday_direction: str = Query("all", description="all|positive|negative|flat"),
    limit: int = Query(100, ge=1, le=100),
):
    """Compare Monday outcomes with the preceding Friday direction for one market."""
    validate_market(market)
    if friday_direction not in {"all", "positive", "negative", "flat"}:
        raise HTTPException(status_code=400, detail="friday_direction must be all, positive, negative, or flat")

    df = load_sessions_df(market)
    df["date_text"] = df["date"].dt.strftime("%Y-%m-%d")
    mondays = [
        (index, row)
        for index, row in df.iterrows()
        if row["day_of_week"] == "Monday"
    ]
    pairs = []
    strategy_stop_points = STOP_LOSS_POINTS.get(market)
    if market == "UK100":
        strategy_name = "FTSE first-5-minute reversal"
        long_rule = "A negative first 5-minute bar sets Long bias; trigger above that bar's high."
        short_rule = "A positive first 5-minute bar sets Short bias; trigger below that bar's low."
    elif market in {"DAX40", "JAPAN225", "NIKKEI_F", "US30", "US100"}:
        strategy_name = "SRS second-15-minute breakout"
        long_rule = "After the second 15-minute bar closes, trigger Long on a break above its high."
        short_rule = "After the second 15-minute bar closes, trigger Short on a break below its low."
    else:
        strategy_name = None
        long_rule = "No intraday Long strategy is configured for this market."
        short_rule = "No intraday Short strategy is configured for this market."
    risk_rule = (
        "No take-profit target is set. "
        f"Configured stop loss: {strategy_stop_points:g} points."
        if strategy_name and strategy_stop_points is not None
        else "No intraday stop or strategy is configured for this market."
    )

    for _, friday in df[df["day_of_week"] == "Friday"].iterrows():
        friday_open = float(friday["session_open"])
        friday_close = float(friday["day_close"])
        if friday_close > friday_open:
            direction = "positive"
        elif friday_close < friday_open:
            direction = "negative"
        else:
            direction = "flat"
        if friday_direction != "all" and direction != friday_direction:
            continue

        next_monday = next(
            (row for _, row in mondays if row["date"] > friday["date"]),
            None,
        )
        if next_monday is None:
            continue

        monday = session_row_to_dict(next_monday)
        monday_metrics = compute_session_metrics(monday)
        strategy_status = None
        strategy_stop_hit = None
        if market == "UK100":
            strategy_bars = load_bars(market, monday["date"], "5min")
            stop_metrics = compute_stop_loss_metrics(monday, strategy_bars)
            first5 = monday.get("first5_dir")
            if first5 == "negative":
                strategy_status = "long"
                strategy_stop_hit = stop_metrics.get("long_stop_hit")
            elif first5 == "positive":
                strategy_status = "short"
                strategy_stop_hit = stop_metrics.get("short_stop_hit")
            elif first5 == "flat":
                strategy_status = "flat"
            else:
                strategy_status = "insufficient_data"
        elif market in {"DAX40", "JAPAN225", "NIKKEI_F", "US30", "US100"}:
            strategy_bars = load_bars(market, monday["date"], "15min")
            strategy = compute_srs_metrics(monday, strategy_bars)
            strategy_status = strategy.get("status")
            strategy_stop_hit = strategy.get("stop_hit")
        monday_move = monday_metrics["day_move_pct"]
        pairs.append(
            {
                "friday_date": friday["date_text"],
                "friday_direction": direction,
                "friday_move_pct": round(
                    (friday_close - friday_open) / friday_open * 100.0, 2
                ),
                "monday_date": monday["date"],
                "monday_direction": monday_metrics["direction"],
                "monday_move_pct": monday_move,
                "monday_gap_dir": monday["gap_dir"],
                "monday_gap_pct": monday["gap_pct"],
                "strategy_name": strategy_name,
                "strategy_status": strategy_status,
                "strategy_stop_points": strategy_stop_points if strategy_name else None,
                "strategy_stop_hit": strategy_stop_hit,
            }
        )

    pairs.sort(key=lambda pair: pair["friday_date"], reverse=True)
    sample_count = len(pairs)
    direction_counts = {
        direction: sum(pair["monday_direction"] == direction for pair in pairs)
        for direction in ("positive", "negative", "flat")
    }

    directional_mondays = direction_counts["positive"] + direction_counts["negative"]
    positive_directional_pct = (
        direction_counts["positive"] / directional_mondays * 100
        if directional_mondays
        else None
    )
    negative_directional_pct = (
        direction_counts["negative"] / directional_mondays * 100
        if directional_mondays
        else None
    )
    minimum_bias_pairs = 20
    minimum_bias_edge_pct = 10.0
    historical_bias = "none"
    bias_reason = "Not enough pairs to establish a historical bias."
    if sample_count >= minimum_bias_pairs and directional_mondays:
        bias_edge = positive_directional_pct - negative_directional_pct
        if bias_edge >= minimum_bias_edge_pct:
            historical_bias = "long"
            bias_reason = "Monday was positive more often after this Friday type."
        elif bias_edge <= -minimum_bias_edge_pct:
            historical_bias = "short"
            bias_reason = "Monday was negative more often after this Friday type."
        else:
            bias_reason = "Historical Monday directions are too close for a bias."
    gap_up_count = sum(pair["monday_gap_dir"] == "up" for pair in pairs)
    strategy_trades = [pair for pair in pairs if pair["strategy_status"] in {"long", "short"}]
    strategy_long_count = sum(pair["strategy_status"] == "long" for pair in strategy_trades)
    strategy_stop_hits = sum(pair["strategy_stop_hit"] is True for pair in strategy_trades)
    moves = [pair["monday_move_pct"] for pair in pairs if pair["monday_move_pct"] is not None]

    return {
        "market": market,
        "market_name": MARKETS[market]["name"],
        "friday_direction": friday_direction,
        "strategy_name": strategy_name,
        "long_rule": long_rule,
        "short_rule": short_rule,
        "risk_rule": risk_rule,
        "strategy_stop_points": strategy_stop_points if strategy_name else None,
        "sample_count": sample_count,
        "monday_direction_counts": direction_counts,
        "monday_positive_pct": round(direction_counts["positive"] / sample_count * 100, 1) if sample_count else None,
        "monday_negative_pct": round(direction_counts["negative"] / sample_count * 100, 1) if sample_count else None,
        "monday_positive_directional_pct": round(positive_directional_pct, 1) if positive_directional_pct is not None else None,
        "monday_negative_directional_pct": round(negative_directional_pct, 1) if negative_directional_pct is not None else None,
        "historical_bias": historical_bias,
        "bias_reason": bias_reason,
        "minimum_bias_pairs": minimum_bias_pairs,
        "minimum_bias_edge_pct": minimum_bias_edge_pct,
        "monday_gap_up_pct": round(gap_up_count / sample_count * 100, 1) if sample_count else None,
        "average_monday_move_pct": round(sum(moves) / len(moves), 2) if moves else None,
        "strategy_trade_count": len(strategy_trades),
        "strategy_long_count": strategy_long_count,
        "strategy_stop_hit_count": strategy_stop_hits,
        "strategy_stop_hit_pct": round(strategy_stop_hits / len(strategy_trades) * 100, 1) if strategy_trades else None,
        "pairs": pairs[:limit],
    }


@app.get("/api/analysis/weekday-following")
def get_weekday_following_analysis(
    market: str = Query(DEFAULT_MARKET),
    source_day: str = Query("Monday"),
    source_direction: str = Query("all", description="all|positive|negative|flat"),
    limit: int = Query(100, ge=1, le=100),
):
    """Compare the next weekday session with its preceding weekday session."""
    validate_market(market)
    next_weekday = {
        "Monday": "Tuesday",
        "Tuesday": "Wednesday",
        "Wednesday": "Thursday",
        "Thursday": "Friday",
    }
    if source_day not in next_weekday:
        raise HTTPException(status_code=400, detail="source_day must be Monday, Tuesday, Wednesday, or Thursday")
    if source_direction not in {"all", "positive", "negative", "flat"}:
        raise HTTPException(status_code=400, detail="source_direction must be all, positive, negative, or flat")

    target_day = next_weekday[source_day]
    df = load_sessions_df(market)
    df["date_text"] = df["date"].dt.strftime("%Y-%m-%d")
    target_rows = [row for _, row in df[df["day_of_week"] == target_day].iterrows()]
    pairs = []
    for _, source in df[df["day_of_week"] == source_day].iterrows():
        source_open = float(source["session_open"])
        source_close = float(source["day_close"])
        if source_close > source_open:
            direction = "positive"
        elif source_close < source_open:
            direction = "negative"
        else:
            direction = "flat"
        if source_direction != "all" and direction != source_direction:
            continue

        target = next((row for row in target_rows if row["date"] > source["date"]), None)
        if target is None:
            continue
        source_dict = session_row_to_dict(source)
        target_dict = session_row_to_dict(target)
        target_metrics = compute_session_metrics(target_dict)
        pairs.append({
            "source_date": source["date_text"],
            "source_direction": direction,
            "source_move_pct": round((source_close - source_open) / source_open * 100.0, 2),
            "source_gap_dir": source_dict["gap_dir"],
            "source_gap_pct": source_dict["gap_pct"],
            "target_date": target_dict["date"],
            "target_direction": target_metrics["direction"],
            "target_move_pct": target_metrics["day_move_pct"],
            "target_gap_dir": target_dict["gap_dir"],
            "target_gap_pct": target_dict["gap_pct"],
        })
    pairs.sort(key=lambda pair: pair["source_date"], reverse=True)
    pairs = pairs[:limit]
    counts = {
        direction: sum(pair["target_direction"] == direction for pair in pairs)
        for direction in ("positive", "negative", "flat")
    }
    sample_count = len(pairs)
    moves = [pair["target_move_pct"] for pair in pairs if pair["target_move_pct"] is not None]
    return {
        "market": market,
        "market_name": MARKETS[market]["name"],
        "source_day": source_day,
        "target_day": target_day,
        "source_direction": source_direction,
        "sample_count": sample_count,
        "target_direction_counts": counts,
        "target_positive_pct": round(counts["positive"] / sample_count * 100, 1) if sample_count else None,
        "target_negative_pct": round(counts["negative"] / sample_count * 100, 1) if sample_count else None,
        "target_flat_pct": round(counts["flat"] / sample_count * 100, 1) if sample_count else None,
        "target_gap_up_pct": round(sum(pair["target_gap_dir"] == "up" for pair in pairs) / sample_count * 100, 1) if sample_count else None,
        "average_target_move_pct": round(sum(moves) / len(moves), 2) if moves else None,
        "pairs": pairs,
    }


@app.get("/api/analysis/weekday-directions")
def get_weekday_direction_table(
    market: str = Query(DEFAULT_MARKET),
    weeks: int = Query(26, ge=1, le=104),
):
    """Return session direction and percentage move in a Monday-Friday grid."""
    validate_market(market)
    df = load_sessions_df(market)
    df = df[df["day_of_week"].isin(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"])].copy()
    df["week_start"] = df["date"] - pd.to_timedelta(df["date"].dt.weekday, unit="D")
    grouped: dict[str, dict[str, Any]] = {}
    for _, row in df.iterrows():
        open_price = float(row["session_open"])
        close_price = float(row["day_close"])
        direction = "positive" if close_price > open_price else "negative" if close_price < open_price else "flat"
        week_start = row["week_start"].strftime("%Y-%m-%d")
        grouped.setdefault(week_start, {"week_start": week_start, "days": {}})
        grouped[week_start]["days"][row["day_of_week"]] = {
            "date": row["date"].strftime("%Y-%m-%d"),
            "direction": direction,
            "move_pct": round((close_price - open_price) / open_price * 100.0, 2),
        }
    result = sorted(grouped.values(), key=lambda week: week["week_start"], reverse=True)[:weeks]
    return {
        "market": market,
        "market_name": MARKETS[market]["name"],
        "week_count": len(result),
        "weeks": result,
    }


@app.get("/api/sessions")
def get_sessions(
    market: str = Query(DEFAULT_MARKET),
    gap_dir: Optional[str] = Query(None, description="comma list: up,down,flat"),
    gap_size_min: Optional[float] = Query(None, description="min abs(gap_pct), e.g. 0.25"),
    open_vs_prior: Optional[str] = Query(
        None, description="comma list: above_prior_high,below_prior_low,inside_range"
    ),
    days: Optional[str] = Query(None, description="comma list: Monday,Tuesday,..."),
    first15_dir: Optional[str] = Query(None, description="positive|negative"),
    second15_dir: Optional[str] = Query(None, description="positive|negative"),
    economic_event: Optional[str] = Query(None, description="comma list: CPI,FOMC"),
    exclude_date: Optional[str] = Query(None),
    reference_date: Optional[str] = Query(None, description="date used to score matches against the selected reference session"),
    only_complete: bool = Query(True),
    limit: int = Query(50, le=500),
    include_bars: bool = Query(False, description="embed intraday bars per session (for thumbnail charts)"),
):
    validate_market(market)
    df = load_sessions_df(market)

    if only_complete:
        df = df[df["is_complete"]]
    if gap_dir:
        wanted = set(gap_dir.split(","))
        df = df[df["gap_dir"].isin(wanted)]
    if gap_size_min is not None:
        df = df[df["gap_pct"].abs() >= gap_size_min]
    if open_vs_prior:
        wanted = set(open_vs_prior.split(","))
        df = df[df["open_vs_prior"].isin(wanted)]
    if days:
        wanted = set(days.split(","))
        df = df[df["day_of_week"].isin(wanted)]
    if first15_dir:
        direction_column = "first5_dir" if market == "UK100" else "first15_dir"
        df = df[df[direction_column] == first15_dir]
    if second15_dir:
        df = df[df["second15_dir"] == second15_dir]
    if economic_event:
        wanted = set(economic_event.split(","))
        event_dates = {d for d, codes in EVENTS_BY_DATE.items() if wanted & set(codes)}
        df = df[df["date"].dt.strftime("%Y-%m-%d").isin(event_dates)]
    if exclude_date:
        df = df[df["date"].dt.strftime("%Y-%m-%d") != exclude_date]

    reference = get_reference_row(market, reference_date)
    df = df.sort_values("date", ascending=False).head(limit)

    results = [session_row_to_dict(row) for _, row in df.iterrows()]
    if include_bars:
        for item in results:
            item["bars"] = load_bars(market, item["date"], item["bars_resolution"])
            attach_analysis(reference, item, item.get("bars"))
    else:
        for item in results:
            attach_analysis(reference, item)

    if reference is not None:
        results.sort(key=lambda item: (item.get("match_score") or 0, item.get("date") or ""), reverse=True)

    return {
        "count": len(results),
        "sessions": results,
    }


@app.get("/api/sessions/{date}")
def get_session_detail(
    date: str,
    market: str = Query(DEFAULT_MARKET),
    resolution: Optional[str] = Query(
        None, description="one of available_resolutions for this session, e.g. 3min/5min/15min/60m; defaults to 15min when available"
    ),
):
    validate_market(market)
    df = load_sessions_df(market)
    match = df[df["date"].dt.strftime("%Y-%m-%d") == date]
    if match.empty:
        raise HTTPException(status_code=404, detail=f"No session for {date} in {market}")

    row = match.iloc[0]
    detail = session_row_to_dict(row)

    chart_resolution = (
        "15min"
        if "15min" in detail["available_resolutions"]
        else row["bars_resolution"]
    )
    if resolution and resolution in detail["available_resolutions"]:
        chart_resolution = resolution

    detail["chart_resolution"] = chart_resolution
    detail["bars"] = load_bars(market, date, chart_resolution)
    detail["history_bars"] = load_bars_range(market, date, chart_resolution)
    detail["session_metrics"] = compute_session_metrics(detail, detail["bars"])
    strategy_resolution = "5min" if market == "UK100" else "15min"
    strategy_bars = load_bars(market, date, strategy_resolution)
    detail["strategy_lines"] = build_strategy_lines(market, strategy_bars)
    detail["stop_loss_metrics"] = compute_stop_loss_metrics(detail, strategy_bars)
    detail["srs_metrics"] = compute_srs_metrics(detail, strategy_bars)
    detail["match_score"] = None
    detail["match_breakdown"] = {}
    return detail


@app.get("/api/meta")
def get_meta(market: str = Query(DEFAULT_MARKET)):
    validate_market(market)
    df = load_sessions_df(market)
    sessions_with_bars = {
        res: int(df["available_resolutions"].str.contains(res).sum()) for res in RESOLUTIONS_FINEST_FIRST
    }
    return {
        "market": market,
        "total_sessions": len(df),
        "date_range": {
            "start": df["date"].min().strftime("%Y-%m-%d"),
            "end": df["date"].max().strftime("%Y-%m-%d"),
        },
        "sessions_with_bars": sessions_with_bars,
        "sessions_with_15min_bars": sessions_with_bars["15min"],
        "latest_complete_date": df[df["is_complete"]]["date"].max().strftime("%Y-%m-%d"),
    }


@app.get("/api/journal/export.csv")
def export_journal_csv():
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for trade in read_trades():
        writer.writerow({field: _safe_csv_value(field, trade.get(field)) for field in CSV_FIELDS})
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="trade_journal.csv"'},
    )


@app.get("/api/journal")
def list_journal_trades(
    market: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Search journal notes and trade details"),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
):
    if market:
        validate_market(market)
    if status and status not in {"planned", "open", "closed", "cancelled"}:
        raise HTTPException(status_code=400, detail="Unknown journal status")
    search_text = (q or "").strip().casefold()
    trades = read_trades()
    filtered = []
    for trade in trades:
        trade_date = str(trade.get("trade_date") or "")
        if market and trade.get("market") != market:
            continue
        if status and trade.get("status") != status:
            continue
        if from_date and trade_date < from_date:
            continue
        if to_date and trade_date > to_date:
            continue
        if search_text and not any(search_text in str(value or "").casefold() for value in trade.values()):
            continue
        filtered.append(trade)
    filtered.sort(key=lambda trade: (trade.get("trade_date") or "", trade.get("created_at") or ""), reverse=True)
    return {"count": len(filtered), "trades": filtered}


@app.post("/api/journal", status_code=201)
def add_journal_trade(payload: JournalTradeInput):
    try:
        validate_market(payload.market)
        return create_trade(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/journal/{trade_id}")
def get_journal_trade(trade_id: str):
    trade = next((item for item in read_trades() if item.get("trade_id") == trade_id), None)
    if trade is None:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    return trade


@app.put("/api/journal/{trade_id}")
def edit_journal_trade(trade_id: str, payload: JournalTradeInput):
    try:
        validate_market(payload.market)
        trade = update_trade(trade_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if trade is None:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    return trade


# Static frontend last, so it doesn't shadow the /api/* routes above.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
