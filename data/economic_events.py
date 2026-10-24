"""
US economic-calendar event dates used for the "Economic Events" filter.

These are real historical dates, not estimates -- sourced and cross-checked
from primary/independent sources reachable from this environment (bls.gov
itself blocks scripted access; fred.stlouisfed.org is unreachable here):

FOMC_DATES
    The rate-decision day of every FOMC meeting (the day the statement/press
    release goes out -- last day of 2-day meetings). Parsed directly from the
    Federal Reserve's own calendar: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
    (each meeting's press-release link embeds the exact date, e.g.
    ".../monetary20260128a1.pdf" -> 2026-01-28).

CPI_DATES
    BLS's official CPI release-date schedule, reconstructed from
    usinflationcalculator.com's release-schedule page (which republishes the
    BLS schedule) plus two Wayback Machine snapshots (Sep 2024, Mar 2025) to
    cover dates that have since rolled off that page's "upcoming" window.
    This also correctly reflects a real disruption: the Oct-2025 CPI report
    (originally due Nov 13, 2025) was CANCELED outright and the Nov-2025
    report was pushed from Dec 10 to Dec 18, 2025 (2025 government shutdown).

Update by re-checking https://www.usinflationcalculator.com/inflation/consumer-price-index-release-schedule/
and the Fed calendar link above; re-run build_sessions.py is NOT needed since
these are matched against sessions.db at request time (see app/main.py).
"""

FOMC_DATES = [
    "2024-09-18", "2024-11-07", "2024-12-18",
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29",
]

CPI_DATES = [
    "2024-09-11", "2024-10-10", "2024-11-13", "2024-12-11",
    "2025-01-15", "2025-02-12", "2025-03-12", "2025-04-10", "2025-05-13",
    "2025-06-11", "2025-07-15", "2025-08-12", "2025-09-11", "2025-10-15",
    # Oct-2025 CPI (originally due 2025-11-13) was canceled outright (shutdown).
    "2025-12-18",  # Nov-2025 CPI, rescheduled from Dec 10 to Dec 18
    "2026-01-13", "2026-02-13", "2026-03-11", "2026-04-10", "2026-05-12",
    "2026-06-10", "2026-07-14", "2026-08-12", "2026-09-11",
]

ECONOMIC_EVENTS = {
    "CPI": {"label": "US CPI (Inflation)", "dates": CPI_DATES},
    "FOMC": {"label": "FOMC Rate Decision", "dates": FOMC_DATES},
}
