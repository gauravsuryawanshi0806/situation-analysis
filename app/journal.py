"""CSV-backed local trade journal storage and calculations."""

from __future__ import annotations

import csv
import os
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


JOURNAL_PATH = Path(__file__).parent.parent / "data" / "trade_journal.csv"
JOURNAL_LOCK = threading.RLock()

RAW_FIELDS = [
    "trade_id",
    "created_at",
    "updated_at",
    "status",
    "market",
    "instrument",
    "strategy",
    "setup_type",
    "trade_date",
    "direction",
    "gap_pct",
    "open_vs_prior",
    "first15_direction",
    "second15_direction",
    "second_bar_high",
    "second_bar_low",
    "economic_events",
    "chart_reference",
    "planned_entry",
    "planned_stop",
    "planned_target",
    "planned_size",
    "point_value",
    "account_currency",
    "analysis",
    "expectation",
    "invalidation",
    "emotion_before",
    "confidence_before",
    "actual_entry",
    "actual_entry_time",
    "actual_stop",
    "actual_target",
    "actual_exit",
    "actual_exit_time",
    "actual_size",
    "actual_fees",
    "slippage_points",
    "broker_pnl",
    "exit_reason",
    "execution_notes",
    "followed_plan",
    "emotion_after",
    "review_notes",
    "lesson_learned",
]
DERIVED_FIELDS = ["planned_rr", "estimated_risk_amount", "realized_points", "realized_r"]
CSV_FIELDS = RAW_FIELDS + DERIVED_FIELDS


class JournalTradeInput(BaseModel):
    status: Literal["planned", "open", "closed", "cancelled"] = "planned"
    market: str = "DAX40"
    instrument: Optional[str] = None
    strategy: str = "SRS"
    setup_type: Optional[str] = None
    trade_date: str
    direction: Literal["long", "short"]
    gap_pct: Optional[float] = None
    open_vs_prior: Optional[str] = None
    first15_direction: Optional[str] = None
    second15_direction: Optional[str] = None
    second_bar_high: Optional[float] = None
    second_bar_low: Optional[float] = None
    economic_events: Optional[str] = None
    chart_reference: Optional[str] = None
    planned_entry: Optional[float] = None
    planned_stop: Optional[float] = None
    planned_target: Optional[float] = None
    planned_size: Optional[float] = Field(default=None, gt=0)
    point_value: Optional[float] = Field(default=None, gt=0)
    account_currency: Optional[str] = None
    analysis: Optional[str] = None
    expectation: Optional[str] = None
    invalidation: Optional[str] = None
    emotion_before: Optional[str] = None
    confidence_before: Optional[int] = Field(default=None, ge=1, le=10)
    actual_entry: Optional[float] = None
    actual_entry_time: Optional[str] = None
    actual_stop: Optional[float] = None
    actual_target: Optional[float] = None
    actual_exit: Optional[float] = None
    actual_exit_time: Optional[str] = None
    actual_size: Optional[float] = Field(default=None, gt=0)
    actual_fees: Optional[float] = Field(default=None, ge=0)
    slippage_points: Optional[float] = None
    broker_pnl: Optional[float] = None
    exit_reason: Optional[str] = None
    execution_notes: Optional[str] = None
    followed_plan: Literal["yes", "partly", "no"] | None = None
    emotion_after: Optional[str] = None
    review_notes: Optional[str] = None
    lesson_learned: Optional[str] = None


def _number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _expected_plan_geometry(trade: dict[str, Any]) -> bool:
    entry = _number(trade.get("planned_entry"))
    stop = _number(trade.get("planned_stop"))
    target = _number(trade.get("planned_target"))
    if entry is None or stop is None or target is None:
        return False
    if trade.get("direction") == "long":
        return stop < entry < target
    return target < entry < stop


def enrich_trade(trade: dict[str, Any]) -> dict[str, Any]:
    result = {field: trade.get(field) for field in RAW_FIELDS}
    entry = _number(result.get("planned_entry"))
    stop = _number(result.get("planned_stop"))
    target = _number(result.get("planned_target"))
    if _expected_plan_geometry(result):
        risk_points = abs(entry - stop)
        reward_points = abs(target - entry)
        result["planned_rr"] = round(reward_points / risk_points, 2) if risk_points else None
    else:
        result["planned_rr"] = None

    size = _number(result.get("planned_size"))
    point_value = _number(result.get("point_value"))
    result["estimated_risk_amount"] = (
        round(abs(entry - stop) * size * point_value, 2)
        if entry is not None and stop is not None and size is not None and point_value is not None
        else None
    )

    actual_entry = _number(result.get("actual_entry"))
    actual_exit = _number(result.get("actual_exit"))
    actual_stop = _number(result.get("actual_stop"))
    if actual_stop is None:
        actual_stop = stop
    direction_sign = 1 if result.get("direction") == "long" else -1
    realized_points = (
        (actual_exit - actual_entry) * direction_sign
        if actual_entry is not None and actual_exit is not None
        else None
    )
    risk_from_actual_entry = (
        abs(actual_entry - actual_stop)
        if actual_entry is not None and actual_stop is not None
        else None
    )
    result["realized_points"] = round(realized_points, 2) if realized_points is not None else None
    result["realized_r"] = (
        round(realized_points / risk_from_actual_entry, 2)
        if realized_points is not None and risk_from_actual_entry
        else None
    )
    return result


def validate_trade(trade: dict[str, Any]) -> None:
    try:
        date.fromisoformat(str(trade.get("trade_date", "")))
    except ValueError as exc:
        raise ValueError("Trade date must be a valid YYYY-MM-DD date.") from exc

    if all(trade.get(field) is not None for field in ("planned_entry", "planned_stop", "planned_target")):
        if not _expected_plan_geometry(trade):
            raise ValueError("For a Long plan, stop < entry < target; for Short, target < entry < stop.")

    if trade.get("actual_entry") is not None and trade.get("actual_stop") is not None:
        actual_entry = float(trade["actual_entry"])
        actual_stop = float(trade["actual_stop"])
        if trade.get("direction") == "long" and actual_stop >= actual_entry:
            raise ValueError("A Long stop must be below the actual entry.")
        if trade.get("direction") == "short" and actual_stop <= actual_entry:
            raise ValueError("A Short stop must be above the actual entry.")


def _safe_csv_value(field: str, value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return format(value, ".10g")
    text = str(value)
    # Journal text can be opened in spreadsheet software. Neutralize formula
    # prefixes in free-text fields while keeping numeric columns unchanged.
    if field not in DERIVED_FIELDS and field not in {
        "gap_pct", "second_bar_high", "second_bar_low", "planned_entry", "planned_stop",
        "planned_target", "planned_size", "point_value", "confidence_before", "actual_entry",
        "actual_stop", "actual_target", "actual_exit", "actual_size", "actual_fees",
        "slippage_points", "broker_pnl",
    } and text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def read_trades() -> list[dict[str, Any]]:
    with JOURNAL_LOCK:
        if not JOURNAL_PATH.exists():
            return []
        with JOURNAL_PATH.open("r", newline="", encoding="utf-8") as handle:
            records = [dict(row) for row in csv.DictReader(handle)]
    for record in records:
        for field, value in record.items():
            if field not in DERIVED_FIELDS and value and value.startswith("'") and value[1:].lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
                record[field] = value[1:]
    return [enrich_trade(record) for record in records]


def write_trades(trades: list[dict[str, Any]]) -> None:
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = JOURNAL_PATH.with_suffix(".csv.tmp")
    with JOURNAL_LOCK:
        with temporary_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
            writer.writeheader()
            for trade in trades:
                enriched = enrich_trade(trade)
                writer.writerow({field: _safe_csv_value(field, enriched.get(field)) for field in CSV_FIELDS})
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(JOURNAL_PATH)


def create_trade(payload: JournalTradeInput) -> dict[str, Any]:
    trade = payload.dict()
    validate_trade(trade)
    now = _timestamp()
    trade.update({"trade_id": str(uuid4()), "created_at": now, "updated_at": now})
    with JOURNAL_LOCK:
        trades = read_trades()
        trades.append(trade)
        write_trades(trades)
    return enrich_trade(trade)


def update_trade(trade_id: str, payload: JournalTradeInput) -> Optional[dict[str, Any]]:
    updates = payload.dict()
    validate_trade(updates)
    with JOURNAL_LOCK:
        trades = read_trades()
        for index, existing in enumerate(trades):
            if existing.get("trade_id") == trade_id:
                updated = {**existing, **updates, "trade_id": trade_id, "created_at": existing.get("created_at")}
                updated["updated_at"] = _timestamp()
                validate_trade(updated)
                trades[index] = updated
                write_trades(trades)
                return enrich_trade(updated)
    return None

