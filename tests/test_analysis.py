from app.analysis import (
    compute_similarity,
    compute_session_metrics,
    compute_srs_metrics,
    compute_stop_loss_metrics,
)


def test_similarity_rewards_close_pattern_match():
    reference = {
        "gap_dir": "up",
        "gap_pct": 0.8,
        "open_vs_prior": "above_prior_high",
        "first15_dir": "positive",
        "second15_dir": "positive",
        "day_of_week": "Monday",
    }
    candidate = {
        "gap_dir": "up",
        "gap_pct": 0.78,
        "open_vs_prior": "above_prior_high",
        "first15_dir": "positive",
        "second15_dir": "positive",
        "day_of_week": "Monday",
    }

    result = compute_similarity(reference, candidate)

    assert result["score"] > 85
    assert result["matched_fields"]["gap_dir"] is True
    assert result["matched_fields"]["first15_dir"] is True


def test_session_metrics_derive_basic_move_values():
    session = {
        "session_open": 100.0,
        "day_close": 106.0,
        "first15_dir": "positive",
        "first15_close": 103.0,
    }

    result = compute_session_metrics(session)

    assert abs(result["day_move_pct"] - 6.0) < 1e-9
    assert abs(result["first15_move_pct"] - 3.0) < 1e-9
    assert result["direction"] == "positive"


def test_uk100_similarity_uses_first_five_minute_direction():
    reference = {
        "market": "UK100",
        "gap_dir": "up",
        "gap_pct": 0.8,
        "open_vs_prior": "above_prior_high",
        "first5_dir": "negative",
        "first15_dir": "positive",
        "second15_dir": "positive",
        "day_of_week": "Monday",
    }
    candidate = {
        **reference,
        "first5_dir": "negative",
        "first15_dir": "negative",
    }

    result = compute_similarity(reference, candidate)

    assert result["matched_fields"]["first5_dir"] is True
    assert "first15_dir" not in result["matched_fields"]


def test_stop_loss_metrics_only_evaluate_configured_stops():
    session = {"market": "DAX40"}
    bars = [
        {"resolution": "15min", "ts": "09:00", "open": 100, "high": 110, "low": 95, "close": 105},
        {"resolution": "15min", "ts": "09:15", "open": 105, "high": 106, "low": -1, "close": 70},
    ]

    result = compute_stop_loss_metrics(session, bars)

    assert result["stop_loss_points"] == 100
    assert result["long_stop_hit"] is True
    assert result["short_stop_hit"] is False
    assert "target" not in result


def test_dax_srs_enters_long_on_second_bar_high_break():
    session = {"market": "DAX40"}
    bars = [
        {"resolution": "15min", "ts": "09:00", "open": 100, "high": 110, "low": 95, "close": 105},
        {"resolution": "15min", "ts": "09:15", "open": 105, "high": 120, "low": 100, "close": 115},
        {"resolution": "15min", "ts": "09:30", "open": 115, "high": 121, "low": 115, "close": 120},
        {"resolution": "15min", "ts": "09:45", "open": 120, "high": 122, "low": 19, "close": 90},
    ]

    result = compute_srs_metrics(session, bars)

    assert result["strategy"] == "SRS"
    assert result["status"] == "long"
    assert result["entry_price"] == 120
    assert result["stop_loss_points"] == 100
    assert result["stop_hit"] is True


def test_srs_uses_market_specific_stops_for_us_indices():
    bars = [
        {"resolution": "15min", "ts": "09:00", "open": 100, "high": 110, "low": 95, "close": 105},
        {"resolution": "15min", "ts": "09:15", "open": 105, "high": 120, "low": 100, "close": 115},
        {"resolution": "15min", "ts": "09:30", "open": 115, "high": 121, "low": 115, "close": 120},
    ]

    us30_result = compute_srs_metrics({"market": "US30"}, bars)
    us100_result = compute_srs_metrics({"market": "US100"}, bars)

    assert us30_result["stop_loss_points"] == 100
    assert us100_result["stop_loss_points"] == 60


def test_srs_uses_japan225_stop_and_strategy():
    bars = [
        {"resolution": "15min", "ts": "09:00", "open": 100, "high": 110, "low": 95, "close": 105},
        {"resolution": "15min", "ts": "09:15", "open": 105, "high": 120, "low": 100, "close": 115},
        {"resolution": "15min", "ts": "09:30", "open": 115, "high": 121, "low": 115, "close": 120},
    ]

    result = compute_srs_metrics({"market": "JAPAN225"}, bars)

    assert result["strategy"] == "SRS"
    assert result["stop_loss_points"] == 150


def test_srs_uses_nikkei_futures_stop_and_strategy():
    result = compute_srs_metrics({"market": "NIKKEI_F"}, [
        {"resolution": "15min", "ts": "09:00", "open": 100, "high": 110, "low": 95, "close": 105},
        {"resolution": "15min", "ts": "09:15", "open": 105, "high": 120, "low": 100, "close": 115},
        {"resolution": "15min", "ts": "09:30", "open": 115, "high": 121, "low": 115, "close": 120},
    ])

    assert result["strategy"] == "SRS"
    assert result["stop_loss_points"] == 150
