# Situational Analysis

A local clone of the "situational analysis" screen: pick a market and a
reference trading session, filter by gap direction/size, open-vs-prior-day,
day of week, and first/second 15-minute bar direction, and browse
historically similar sessions with real candlestick charts.

## Markets

Switchable from the sidebar dropdown ([data/markets.py](data/markets.py)):

| Code  | Market                           | Yahoo ticker |
| ----- | -------------------------------- | ------------ |
| DAX40 | DAX 40 (cash index)              | `^GDAXI`     |
| US30  | Dow Jones (Wall Street 30, cash) | `^DJI`       |
| US100 | Nasdaq (US Tech 100, cash)       | `^NDX`       |
| YM_F  | Dow Jones Futures (YM)           | `YM=F`       |
| NQ_F  | US Tech 100 Futures (NQ)         | `NQ=F`       |

**No DAX 40 futures**: Yahoo Finance does not host real Eurex FDAX futures
data under any ticker — verified by testing several candidates; `DAX=F` on
Yahoo is an unrelated, unconnected NYMEX instrument (price ~35-37, nothing
like the index), and Yahoo's own symbol search only turns up leveraged ETN
products, not the futures contract itself. DAX 40 is only available here as
the cash index.

**Gap means something different for futures.** YM/NQ futures trade nearly
24 hours a day (CME Globex), so "gap" (session open vs. prior session close)
only captures the brief daily maintenance-break move — typically well under
0.5% — not a real overnight/weekend gap the way it does for the cash
indices. "Open vs Prior Day" is similarly dominated by "Inside Range" (~90%
of sessions) for the same reason. The data is real and correctly pulled;
these filters are just far less discriminating for a continuously-traded
instrument than for a cash index that actually closes overnight.

## Data

All data is **real**, pulled from Yahoo Finance's public chart API, no API
key required. Each session stores whichever of these resolutions Yahoo
actually has for that date, and the chart's timeframe selector (3m/5m/15m/1H)
only enables the ones genuinely available for the session on screen:

| Resolution     | Window                                           | Notes                                                                                                                                                 |
| -------------- | ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Daily          | last 2 years                                     | gap %, prior-day high/low/close, day-of-week                                                                                                          |
| 60-minute (1H) | last 2 years                                     | available for essentially every session                                                                                                               |
| 15-minute      | last 60 days (Yahoo's own cap for this interval) | also used for 1st/2nd 15m bar direction                                                                                                               |
| 5-minute       | last 60 days (Yahoo's own cap for this interval) |                                                                                                                                                       |
| 3-minute       | last ~7 days                                     | Yahoo has no native 3-minute interval — these are real 1-minute bars (Yahoo's own 7-day cap) aggregated into 3-min OHLC, not synthetic/estimated data |

Sessions with no 15-min data won't have a 1st/2nd-15-min-bar value — the UI
labels these "n/a" rather than faking them, and the timeframe buttons on the
chart are disabled for any resolution the session doesn't have.

Everything is stored in one SQLite database (`data/sessions.db`) with a
`market` column, built from per-market raw CSVs under `data/raw/<code>/`. The
`bars` table holds every available resolution per session (not just one), and
each session row's `available_resolutions` lists which ones it has.

The main chart also marks the prior session's close (PDC) as a dashed
horizontal price line, using each session's own `prior_close`.

## Economic Events (CPI / FOMC)

The sidebar's "Economic Events" dropdown filters sessions to the real dates
of US CPI releases and FOMC rate decisions, defined in
[data/economic_events.py](data/economic_events.py):

- **FOMC** dates are parsed straight from the Fed's own calendar
  (federalreserve.gov) — each meeting's press-release link embeds the exact
  decision date.
- **CPI** dates are BLS's official release schedule, reconstructed from
  usinflationcalculator.com's schedule page plus two Wayback Machine
  snapshots (bls.gov itself blocks scripted access from this environment).
  This also captures a real disruption: the Oct-2025 CPI report was
  **canceled** outright and the Nov-2025 report was pushed from Dec 10 to
  Dec 18, 2025 (2025 government shutdown) — reflected accurately rather than
  assuming the normal monthly cadence.

Selecting an event type clears the gap/day-of-week/15m-bar filters and shows
every session on those dates across the 2-year window (~24 for CPI, ~16 for
FOMC) — combine it with other filters afterward (e.g. click "Gap Up") to
narrow further. These are calendar dates only (no actual CPI value / rate
decision is stored) — good enough to see how each market reacted on the day,
not to correlate with the surprise/beat-or-miss size of the release.

To update: re-check the two source pages above and edit `CPI_DATES` /
`FOMC_DATES` in `data/economic_events.py` — no need to re-run
`build_sessions.py`, these are matched against the database at request time.

## Adding another market

1. Add an entry to `MARKETS` in [data/markets.py](data/markets.py) with its
   Yahoo ticker and IANA timezone.
2. Re-run the two data scripts below (they loop over every configured market).

## Re-downloading data

```bash
cd data
python fetch_data.py      # incrementally merges recent bars into data/raw/<code>/
python build_sessions.py  # rebuilds data/sessions.db from those CSVs, for all markets
```

For existing markets, `fetch_data.py` requests only the recent trading window
needed to capture the latest session and merges it by timestamp, preserving
older downloaded bars. The first run for a new market still downloads the
full history. Yahoo only exposes a rolling 7-day window for 1-minute data, so
3-minute history can accumulate beyond seven days only if this script is run
regularly; 5-minute and 15-minute history can be preserved beyond Yahoo's
rolling 60-day window once downloaded.

## Running the app

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Then open http://localhost:8000

## Trade Journal

The Trade Journal page stores planned trades, execution details, and post-trade
reviews in `data/trade_journal.csv`. The CSV is local app data and is excluded
from Git. Use the page's Export CSV button to download a spreadsheet copy.

The journal calculates planned reward-to-risk, estimated cash risk when a
broker-specific point value and position size are supplied, realized points,
and realized R. Realized R assumes one entry and one exit; partial-fill details
can be recorded in execution notes but are not weighted into that calculation.
Broker-reported P&L, fees, and slippage remain user-entered so the app does not
assume a contract's value or execution costs.

## Weekday Relationships

The Weekday Relationships page compares Monday→Tuesday, Tuesday→Wednesday,
Wednesday→Thursday, and Thursday→Friday sessions. It supports the same market
selection as the other studies, filters pairs by the source day's direction,
and summarizes the following session's direction, gap, and average move.

The Weekday Directions page displays the open-to-close direction and percentage
move for Monday through Friday in a weekly table, with 13 to 104 weeks available.
