"""Helpers for ranking historical sessions by similarity and summarizing session move metrics."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


SIMILARITY_WEIGHTS = {
    "gap_dir": 30,
    "gap_pct": 20,
    "open_vs_prior": 20,
    "first15_dir": 15,
    "second15_dir": 10,
    "day_of_week": 5,
}

STOP_LOSS_POINTS = {
    "DAX40": 100.0,
    "JAPAN225": 150.0,
    "NIKKEI_F": 150.0,
    "UK100": 20.0,
    "US30": 100.0,
    "US100": 60.0,
}


def _gap_pct_similarity(reference_gap_pct: Optional[float], candidate_gap_pct: Optional[float]) -> float:
    if reference_gap_pct is None or candidate_gap_pct is None:
        return 0.0
    diff = abs(reference_gap_pct - candidate_gap_pct)
    if diff <= 0.05:
        return 20.0
    if diff <= 0.25:
        return 15.0
    if diff <= 0.75:
        return 8.0
    return 2.0


def compute_similarity(reference: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    first_bar_field = "first5_dir" if reference.get("market") == "UK100" else "first15_dir"
    matched_fields: dict[str, bool] = {
        "gap_dir": reference.get("gap_dir") == candidate.get("gap_dir"),
        "gap_pct": False,
        "open_vs_prior": reference.get("open_vs_prior") == candidate.get("open_vs_prior"),
        first_bar_field: reference.get(first_bar_field) == candidate.get(first_bar_field),
        "second15_dir": reference.get("second15_dir") == candidate.get("second15_dir"),
        "day_of_week": reference.get("day_of_week") == candidate.get("day_of_week"),
    }

    score = 0.0
    if matched_fields["gap_dir"]:
        score += SIMILARITY_WEIGHTS["gap_dir"]
    else:
        score += max(0.0, SIMILARITY_WEIGHTS["gap_dir"] - 20.0)

    gap_similarity = _gap_pct_similarity(reference.get("gap_pct"), candidate.get("gap_pct"))
    matched_fields["gap_pct"] = gap_similarity >= 15.0
    score += gap_similarity

    if matched_fields["open_vs_prior"]:
        score += SIMILARITY_WEIGHTS["open_vs_prior"]
    else:
        score += max(0.0, SIMILARITY_WEIGHTS["open_vs_prior"] - 10.0)

    if matched_fields[first_bar_field]:
        score += SIMILARITY_WEIGHTS["first15_dir"]
    else:
        score += max(0.0, SIMILARITY_WEIGHTS["first15_dir"] - 8.0)

    if matched_fields["second15_dir"]:
        score += SIMILARITY_WEIGHTS["second15_dir"]
    else:
        score += max(0.0, SIMILARITY_WEIGHTS["second15_dir"] - 6.0)

    if matched_fields["day_of_week"]:
        score += SIMILARITY_WEIGHTS["day_of_week"]

    score = min(100.0, max(0.0, round(score, 1)))
    return {
        "score": score,
        "matched_fields": matched_fields,
    }


def compute_session_metrics(session: Dict[str, Any], bars: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    session_open = session.get("session_open")
    day_close = session.get("day_close")
    day_move_pct = None
    direction = "flat"

    if session_open not in (None, "") and day_close not in (None, ""):
        try:
            session_open_f = float(session_open)
            day_close_f = float(day_close)
            day_move_pct = ((day_close_f - session_open_f) / session_open_f) * 100.0
            if day_move_pct > 0.05:
                direction = "positive"
            elif day_move_pct < -0.05:
                direction = "negative"
        except (TypeError, ValueError):
            day_move_pct = None

    first15_move_pct = None
    first15_close = session.get("first15_close")
    if first15_close is not None:
        try:
            first_open = float(session.get("session_open") or 0)
            first_close = float(first15_close)
            if first_open:
                first15_move_pct = ((first_close - first_open) / first_open) * 100.0
        except (TypeError, ValueError):
            first15_move_pct = None
    elif bars:
        try:
            first_bar = min(bars, key=lambda b: b.get("ts", ""))
            first_open = float(first_bar.get("open"))
            first_close = float(first_bar.get("close"))
            if first_open:
                first15_move_pct = ((first_close - first_open) / first_open) * 100.0
        except (TypeError, ValueError):
            first15_move_pct = None

    return {
        "day_move_pct": round(day_move_pct, 2) if day_move_pct is not None else None,
        "first15_move_pct": round(first15_move_pct, 2) if first15_move_pct is not None else None,
        "direction": direction,
    }


def compute_stop_loss_metrics(
    session: Dict[str, Any], bars: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Evaluate fixed stop-only scenarios after the strategy's opening bar."""
    market = session.get("market")
    stop_loss_points = STOP_LOSS_POINTS.get(market)
    if stop_loss_points is None or not bars:
        return {
            "stop_loss_points": stop_loss_points,
            "long_stop_hit": None,
            "short_stop_hit": None,
        }

    strategy_resolution = "5min" if market == "UK100" else "15min"
    strategy_bars = [bar for bar in bars if bar.get("resolution") == strategy_resolution]
    if len(strategy_bars) < 2:
        return {
            "stop_loss_points": stop_loss_points,
            "long_stop_hit": None,
            "short_stop_hit": None,
        }

    strategy_bars.sort(key=lambda bar: bar.get("ts", ""))
    entry_bar = strategy_bars[0]
    entry_price = float(entry_bar["close"])
    long_stop = entry_price - stop_loss_points
    short_stop = entry_price + stop_loss_points
    following_bars = strategy_bars[1:]

    return {
        "stop_loss_points": stop_loss_points,
        "entry_price": round(entry_price, 2),
        "long_stop_price": round(long_stop, 2),
        "short_stop_price": round(short_stop, 2),
        "long_stop_hit": any(float(bar["low"]) <= long_stop for bar in following_bars),
        "short_stop_hit": any(float(bar["high"]) >= short_stop for bar in following_bars),
    }


def compute_srs_metrics(
    session: Dict[str, Any], bars: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Evaluate the SRS second-15-minute-bar breakout and market stop."""
    market = session.get("market")
    if market not in {"DAX40", "JAPAN225", "NIKKEI_F", "US30", "US100"} or not bars:
        return {"strategy": None}

    strategy_bars = [bar for bar in bars if bar.get("resolution") == "15min"]
    strategy_bars.sort(key=lambda bar: bar.get("ts", ""))
    if len(strategy_bars) < 3:
        return {"strategy": "SRS", "status": "insufficient_data"}

    second_bar = strategy_bars[1]
    breakout_high = float(second_bar["high"])
    breakout_low = float(second_bar["low"])
    stop_loss_points = STOP_LOSS_POINTS[market]

    for bar in strategy_bars[2:]:
        broke_high = float(bar["high"]) >= breakout_high
        broke_low = float(bar["low"]) <= breakout_low
        if broke_high and broke_low:
            return {
                "strategy": "SRS",
                "status": "ambiguous",
                "reason": "Both second-bar levels broke within the same bar",
                "breakout_high": round(breakout_high, 2),
                "breakout_low": round(breakout_low, 2),
                "stop_loss_points": stop_loss_points,
            }
        if broke_high:
            stop_price = breakout_high - stop_loss_points
            stop_hit = any(
                float(candidate["low"]) <= stop_price
                for candidate in strategy_bars[strategy_bars.index(bar) :]
            )
            return {
                "strategy": "SRS",
                "status": "long",
                "entry_price": round(breakout_high, 2),
                "stop_price": round(stop_price, 2),
                "stop_loss_points": stop_loss_points,
                "stop_hit": stop_hit,
            }
        if broke_low:
            stop_price = breakout_low + stop_loss_points
            stop_hit = any(
                float(candidate["high"]) >= stop_price
                for candidate in strategy_bars[strategy_bars.index(bar) :]
            )
            return {
                "strategy": "SRS",
                "status": "short",
                "entry_price": round(breakout_low, 2),
                "stop_price": round(stop_price, 2),
                "stop_loss_points": stop_loss_points,
                "stop_hit": stop_hit,
            }

    return {
        "strategy": "SRS",
        "status": "no_breakout",
        "breakout_high": round(breakout_high, 2),
        "breakout_low": round(breakout_low, 2),
        "stop_loss_points": stop_loss_points,
    }
