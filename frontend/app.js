const API = "/api";

const state = {
  market: "DAX40",
  referenceDate: null,
  referenceSession: null,
  selectedDate: null,
  matchSessions: [],
  savedSetups: JSON.parse(
    localStorage.getItem("situational-analysis-setups") || "[]",
  ),
  filters: {
    gap_dir: null,
    gap_size_min: null,
    open_vs_prior: null,
    days: new Set(),
    first15_dir: null,
    second15_dir: null,
    economic_event: null,
  },
};

let mainChart = null;
let mainSeries = null;
let pdcLine = null;
let strategyLines = [];
let daySeparatorTimes = [];

function $(sel) {
  return document.querySelector(sel);
}
function $all(sel) {
  return Array.from(document.querySelectorAll(sel));
}

// Every market's bars are timestamped in that market's own exchange timezone
// (e.g. US markets in America/New_York), but the chart should always read in
// the viewer's own time -- Europe/Berlin -- regardless of the browser's own
// system timezone (which the underlying charting library would otherwise use
// by default). So DAX's 09:00 open and the US markets' ~15:30 open (Berlin
// time) both land correctly on the same clock.
const DISPLAY_TZ = "Europe/Berlin";
const berlinTimeFmt = new Intl.DateTimeFormat("en-GB", {
  timeZone: DISPLAY_TZ,
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});
const berlinDateFmt = new Intl.DateTimeFormat("en-CA", {
  timeZone: DISPLAY_TZ,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});
function formatBerlinTime(unixSeconds) {
  return berlinTimeFmt.format(new Date(unixSeconds * 1000));
}
function formatBerlinDate(unixSeconds) {
  return berlinDateFmt.format(new Date(unixSeconds * 1000));
}

function fmtPct(v) {
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

function dirClass(dir) {
  if (dir === "up" || dir === "positive") return "up";
  if (dir === "down" || dir === "negative") return "down";
  return "flat";
}

function label(value) {
  return (
    {
      up: "Gap Up",
      down: "Gap Down",
      flat: "Flat",
      above_prior_high: "Above Prior High",
      below_prior_low: "Below Prior Low",
      inside_range: "Inside Range",
      positive: "Positive",
      negative: "Negative",
    }[value] || value
  );
}

const TF_LABELS = {
  "3min": "3-min",
  "5min": "5-min",
  "15min": "15-min",
  "60m": "1H",
};
function resolutionLabel(res) {
  return TF_LABELS[res] ? `${TF_LABELS[res]} bars` : res;
}

function firstBarLabel(market) {
  return market === "UK100" ? "1st 5m" : "1st 15m";
}

function strategyBias(session) {
  if (session.market !== "UK100" || !session.first5_dir) return null;
  if (session.first5_dir === "negative") return "Long";
  if (session.first5_dir === "positive") return "Short";
  return "Neutral";
}

// ---------- filter button wiring ----------
function setupButtonGroups() {
  $all(".btn-row[data-group]").forEach((row) => {
    const group = row.dataset.group;
    const multi = row.dataset.multi === "true";
    row.querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", () => {
        const value = btn.dataset.value;
        if (multi) {
          if (state.filters[group].has(value)) {
            state.filters[group].delete(value);
            btn.classList.remove("active");
          } else {
            state.filters[group].add(value);
            btn.classList.add("active");
          }
        } else {
          const alreadyActive = btn.classList.contains("active");
          row
            .querySelectorAll("button")
            .forEach((b) => b.classList.remove("active"));
          if (alreadyActive) {
            state.filters[group] = null;
          } else {
            btn.classList.add("active");
            state.filters[group] = value;
          }
        }
        runSearch();
      });
    });
  });
}

function setButtonGroupValue(group, value) {
  const row = document.querySelector(`.btn-row[data-group="${group}"]`);
  if (!row) return;
  row.querySelectorAll("button").forEach((b) => {
    b.classList.toggle("active", b.dataset.value === value);
  });
  state.filters[group] = value;
}

function clearPatternFilterButtons() {
  // clears the gap/day-of-week/15m-bar button groups (not economic_event,
  // which has its own <select>) -- used when switching to "browse an
  // economic event" mode so it isn't silently ANDed with a leftover pattern.
  $all(".btn-row[data-group]").forEach((row) => {
    row.querySelectorAll("button").forEach((b) => b.classList.remove("active"));
  });
  state.filters.gap_dir = null;
  state.filters.gap_size_min = null;
  state.filters.open_vs_prior = null;
  state.filters.days = new Set();
  state.filters.first15_dir = null;
  state.filters.second15_dir = null;
}

function clearAllFilters() {
  clearPatternFilterButtons();
  state.filters.economic_event = null;
  $("#econEvents").value = "";
  runSearch();
}

function persistSavedSetups() {
  localStorage.setItem(
    "situational-analysis-setups",
    JSON.stringify(state.savedSetups),
  );
  renderSavedSetups();
}

function getCurrentSetupSnapshot() {
  return {
    id: Date.now().toString(),
    name: `${state.market} · ${state.referenceDate || "current"}`,
    market: state.market,
    referenceDate: state.referenceDate,
    filters: {
      gap_dir: state.filters.gap_dir,
      gap_size_min: state.filters.gap_size_min,
      open_vs_prior: state.filters.open_vs_prior,
      days: Array.from(state.filters.days || []),
      first15_dir: state.filters.first15_dir,
      second15_dir: state.filters.second15_dir,
      economic_event: state.filters.economic_event,
    },
  };
}

function applySetup(setup) {
  state.market = setup.market || state.market;
  $("#marketSelect").value = state.market;
  state.referenceDate = setup.referenceDate || state.referenceDate;
  state.filters.gap_dir = setup.filters.gap_dir || null;
  state.filters.gap_size_min = setup.filters.gap_size_min || null;
  state.filters.open_vs_prior = setup.filters.open_vs_prior || null;
  state.filters.days = new Set(setup.filters.days || []);
  state.filters.first15_dir = setup.filters.first15_dir || null;
  state.filters.second15_dir = setup.filters.second15_dir || null;
  state.filters.economic_event = setup.filters.economic_event || null;
  $("#econEvents").value = state.filters.economic_event || "";
  $all(".btn-row[data-group]").forEach((row) => {
    const group = row.dataset.group;
    const value = state.filters[group];
    row.querySelectorAll("button").forEach((btn) => {
      const active =
        group === "days"
          ? state.filters.days.has(btn.dataset.value)
          : btn.dataset.value === value;
      btn.classList.toggle("active", active);
    });
  });
  loadMarket();
}

function renderSavedSetups() {
  const list = $("#savedSetups");
  if (!list) return;
  list.innerHTML = (state.savedSetups || [])
    .map(
      (setup) => `
    <div class="saved-setup-item">
      <span>${setup.name}</span>
      <div>
        <button data-setup-load="${setup.id}">Load</button>
        <button data-setup-delete="${setup.id}" class="danger">Delete</button>
      </div>
    </div>
  `,
    )
    .join("");

  list.querySelectorAll("button[data-setup-load]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const setup = state.savedSetups.find(
        (item) => item.id === btn.dataset.setupLoad,
      );
      if (setup) applySetup(setup);
    });
  });

  list.querySelectorAll("button[data-setup-delete]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.savedSetups = state.savedSetups.filter(
        (item) => item.id !== btn.dataset.setupDelete,
      );
      persistSavedSetups();
    });
  });
}

function saveCurrentSetup() {
  const snapshot = getCurrentSetupSnapshot();
  const name = window.prompt("Name this setup", snapshot.name);
  if (!name) return;
  snapshot.name = name.trim() || snapshot.name;
  state.savedSetups.push(snapshot);
  persistSavedSetups();
}

// ---------- API helpers ----------
async function fetchMarkets() {
  const res = await fetch(`${API}/markets`);
  return res.json();
}

async function fetchEconomicEvents() {
  const res = await fetch(`${API}/economic-events`);
  return res.json();
}

async function fetchMeta() {
  const res = await fetch(`${API}/meta?market=${state.market}`);
  return res.json();
}

async function fetchSessionDetail(date) {
  const res = await fetch(`${API}/sessions/${date}?market=${state.market}`);
  if (!res.ok) throw new Error(`No session data for ${date}`);
  return res.json();
}

function buildQuery(extra) {
  const p = new URLSearchParams();
  p.set("market", state.market);
  const f = state.filters;
  if (f.gap_dir) p.set("gap_dir", f.gap_dir);
  if (f.gap_size_min) p.set("gap_size_min", f.gap_size_min);
  if (f.open_vs_prior) p.set("open_vs_prior", f.open_vs_prior);
  if (f.days.size) p.set("days", Array.from(f.days).join(","));
  if (f.first15_dir) p.set("first15_dir", f.first15_dir);
  if (f.second15_dir) p.set("second15_dir", f.second15_dir);
  if (f.economic_event) p.set("economic_event", f.economic_event);
  if (state.referenceDate) p.set("reference_date", state.referenceDate);
  Object.entries(extra || {}).forEach(([k, v]) => p.set(k, v));
  return p.toString();
}

async function fetchMatches() {
  const q = buildQuery({
    exclude_date: state.referenceDate || "",
    include_bars: "true",
    limit: 60,
  });
  const res = await fetch(`${API}/sessions?${q}`);
  return res.json();
}

// ---------- rendering ----------
function renderMainChart(session) {
  const container = $("#mainChart");
  if (!mainChart) {
    mainChart = LightweightCharts.createChart(container, {
      layout: { background: { color: "#ffffff" }, textColor: "#374151" },
      grid: {
        vertLines: { color: "#f1f3f6" },
        horzLines: { color: "#f1f3f6" },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (time) => formatBerlinTime(time),
      },
      localization: {
        timeFormatter: (time) =>
          `${formatBerlinDate(time)} ${formatBerlinTime(time)} (Berlin)`,
      },
      rightPriceScale: { borderColor: "#e2e6ec" },
      handleScroll: true,
      handleScale: true,
    });
    mainSeries = mainChart.addCandlestickSeries({
      upColor: "#3b82f6",
      downColor: "#ef4444",
      borderVisible: false,
      wickUpColor: "#3b82f6",
      wickDownColor: "#ef4444",
    });
    new ResizeObserver(() => {
      mainChart.applyOptions({
        width: container.clientWidth,
        height: container.clientHeight,
      });
      requestAnimationFrame(renderDaySeparators);
    }).observe(container);
    mainChart
      .timeScale()
      .subscribeVisibleLogicalRangeChange(renderDaySeparators);
  }

  const chartBars = session.history_bars || session.bars || [];
  const bars = chartBars.map((b) => ({
    time: Math.floor(new Date(b.ts).getTime() / 1000),
    open: b.open,
    high: b.high,
    low: b.low,
    close: b.close,
  }));
  mainSeries.setData(bars);
  daySeparatorTimes = [];
  const seenDates = new Set();
  chartBars.forEach((bar) => {
    const time = Math.floor(new Date(bar.ts).getTime() / 1000);
    const date = formatBerlinDate(time);
    if (!seenDates.has(date)) {
      seenDates.add(date);
      daySeparatorTimes.push(time);
    }
  });
  const datesByBar = chartBars.map((bar) =>
    formatBerlinDate(Math.floor(new Date(bar.ts).getTime() / 1000)),
  );
  const visibleDates = [
    ...new Set(datesByBar.filter((date) => date <= session.date)),
  ];
  const firstVisibleDate = visibleDates[Math.max(0, visibleDates.length - 3)];
  let firstVisibleIndex = datesByBar.findIndex(
    (date) => date === firstVisibleDate,
  );
  let lastVisibleIndex = datesByBar.lastIndexOf(session.date);

  if (firstVisibleIndex < 0 || lastVisibleIndex < firstVisibleIndex) {
    lastVisibleIndex = bars.length - 1;
    firstVisibleIndex = Math.max(0, lastVisibleIndex - 3 * 30);
  }

  requestAnimationFrame(() => {
    if (firstVisibleIndex >= 0 && lastVisibleIndex >= firstVisibleIndex) {
      mainChart.timeScale().setVisibleLogicalRange({
        from: firstVisibleIndex,
        to: lastVisibleIndex,
      });
    } else {
      mainChart.timeScale().fitContent();
    }
    renderDaySeparators();
  });

  if (pdcLine) {
    mainSeries.removePriceLine(pdcLine);
    pdcLine = null;
  }
  pdcLine = mainSeries.createPriceLine({
    price: session.prior_close,
    color: "#9333ea",
    lineWidth: 1,
    lineStyle: LightweightCharts.LineStyle.Dashed,
    axisLabelVisible: true,
    title: "PDC",
  });

  strategyLines.forEach((line) => mainSeries.removePriceLine(line));
  strategyLines = (session.strategy_lines || []).map((line) =>
    mainSeries.createPriceLine({
      price: line.price,
      color: line.color,
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Dashed,
      axisLabelVisible: true,
      title: line.title,
    }),
  );

  $("#chartTitle").textContent = `${session.date} · ${session.day_of_week}`;
  renderTfRow(session);

  const badges = [];
  badges.push(
    `<span class="badge ${dirClass(session.gap_dir)}">Gap ${fmtPct(session.gap_pct)}</span>`,
  );
  badges.push(
    `<span class="badge muted">${label(session.open_vs_prior)}</span>`,
  );
  if (session.first15_dir) {
    badges.push(
      `<span class="badge ${dirClass(session.first15_dir)}">1st 15m ${label(session.first15_dir)}</span>`,
    );
  }
  if (session.second15_dir) {
    badges.push(
      `<span class="badge ${dirClass(session.second15_dir)}">2nd 15m ${label(session.second15_dir)}</span>`,
    );
  }
  badges.push(
    `<span class="badge muted">${resolutionLabel(session.chart_resolution || session.bars_resolution)}</span>`,
  );
  (session.economic_events || []).forEach((ev) => {
    badges.push(`<span class="badge event">${ev} day</span>`);
  });
  $("#chartBadges").innerHTML = badges.join("");
}

function renderDaySeparators() {
  const container = $("#mainChart");
  const layer = $("#daySeparators");
  if (!container || !layer || !mainChart) return;
  const timeScale = mainChart.timeScale();
  layer.innerHTML = daySeparatorTimes
    .map((time) => {
      const x = timeScale.timeToCoordinate(time);
      if (x == null || x < 0 || x > container.clientWidth) return "";
      return `<span class="day-separator" style="left:${x}px"></span>`;
    })
    .join("");
}

function renderTfRow(session) {
  const available = new Set(session.available_resolutions || []);
  const current = session.chart_resolution || session.bars_resolution;
  $all("#tfRow button").forEach((btn) => {
    const tf = btn.dataset.tf;
    btn.disabled = !available.has(tf);
    btn.classList.toggle("active", tf === current);
  });
}

function adjustChartZoom(direction) {
  if (!mainChart) return;
  const timeScale = mainChart.timeScale();
  const range = timeScale.getVisibleLogicalRange();
  if (!range) return;

  const center = (range.from + range.to) / 2;
  const span = Math.max(1, range.to - range.from);
  const nextSpan = direction === "in" ? Math.max(20, span * 0.65) : span * 1.5;
  timeScale.setVisibleLogicalRange({
    from: center - nextSpan / 2,
    to: center + nextSpan / 2,
  });
}

async function changeResolution(tf) {
  const date = state.selectedDate || state.referenceDate;
  if (!date) return;
  const q = new URLSearchParams({
    market: state.market,
    resolution: tf,
  }).toString();
  const res = await fetch(`${API}/sessions/${date}?${q}`);
  if (!res.ok) return;
  const detail = await res.json();
  renderMainChart(detail);
  renderDetail(detail);
}

function renderDetail(session) {
  const panel = $("#detailPanel");
  const metrics = session.session_metrics || {};
  panel.innerHTML = `
    <div class="detail-date">${session.date}</div>
    <div class="detail-dow">${session.day_of_week}</div>

    <div class="detail-section">
      <h4>SESSION CONTEXT</h4>
      <div class="detail-row"><span>Gap</span><span class="v ${dirClass(session.gap_dir)}">${fmtPct(session.gap_pct)}</span></div>
      <div class="detail-row"><span>Open vs Prior</span><span class="v">${label(session.open_vs_prior)}</span></div>
      <div class="detail-row"><span>${firstBarLabel(session.market)} Bar</span><span class="v ${dirClass(session.market === "UK100" ? session.first5_dir : session.first15_dir)}">${(session.market === "UK100" ? session.first5_dir : session.first15_dir) ? label(session.market === "UK100" ? session.first5_dir : session.first15_dir) : "n/a"}</span></div>
      ${strategyBias(session) ? `<div class="detail-row"><span>FTSE strategy bias</span><span class="v">${strategyBias(session)}</span></div>` : ""}
      <div class="detail-row"><span>2nd 15m Bar</span><span class="v ${dirClass(session.second15_dir)}">${session.second15_dir ? label(session.second15_dir) : "n/a"}</span></div>
    </div>

    <div class="detail-section">
      <h4>OUTCOME METRICS</h4>
      <div class="detail-row"><span>Day move</span><span class="v ${dirClass(metrics.direction || "flat")}">${metrics.day_move_pct != null ? fmtPct(metrics.day_move_pct) : "n/a"}</span></div>
      <div class="detail-row"><span>1st 15m move</span><span class="v ${dirClass(metrics.direction || "flat")}">${metrics.first15_move_pct != null ? fmtPct(metrics.first15_move_pct) : "n/a"}</span></div>
      <div class="detail-row"><span>Overall direction</span><span class="v">${metrics.direction ? label(metrics.direction) : "n/a"}</span></div>
    </div>

    ${
      session.stop_loss_metrics
        ? `
    <div class="detail-section">
      <h4>STOP-LOSS CHECK</h4>
      <div class="detail-row"><span>Stop loss</span><span class="v">${session.stop_loss_metrics.stop_loss_points != null ? `${session.stop_loss_metrics.stop_loss_points} pts` : "n/a"}</span></div>
      <div class="detail-row"><span>Long stop hit</span><span class="v">${session.stop_loss_metrics.long_stop_hit == null ? "n/a" : session.stop_loss_metrics.long_stop_hit ? "Yes" : "No"}</span></div>
      <div class="detail-row"><span>Short stop hit</span><span class="v">${session.stop_loss_metrics.short_stop_hit == null ? "n/a" : session.stop_loss_metrics.short_stop_hit ? "Yes" : "No"}</span></div>
    </div>`
        : ""
    }

    ${
      session.srs_metrics && session.srs_metrics.strategy === "SRS"
        ? `
    <div class="detail-section">
      <h4>SRS STRATEGY</h4>
      <div class="detail-row"><span>Signal</span><span class="v">${session.srs_metrics.status === "long" ? "Long" : session.srs_metrics.status === "short" ? "Short" : session.srs_metrics.status === "ambiguous" ? "Ambiguous" : session.srs_metrics.status === "no_breakout" ? "No breakout" : "Insufficient data"}</span></div>
      <div class="detail-row"><span>Stop loss</span><span class="v">${session.srs_metrics.stop_loss_points != null ? `${session.srs_metrics.stop_loss_points} pts` : "n/a"}</span></div>
      ${session.srs_metrics.entry_price != null ? `<div class="detail-row"><span>Entry</span><span class="v">${session.srs_metrics.entry_price.toFixed(2)}</span></div>` : ""}
      ${session.srs_metrics.stop_price != null ? `<div class="detail-row"><span>Stop hit</span><span class="v">${session.srs_metrics.stop_hit ? "Yes" : "No"}</span></div>` : ""}
      ${session.srs_metrics.reason ? `<div class="detail-row"><span>Note</span><span class="v">${session.srs_metrics.reason}</span></div>` : ""}
    </div>`
        : ""
    }

    <div class="detail-section">
      <h4>PRIOR DAY</h4>
      <div class="detail-row"><span>High</span><span class="v">${session.prior_high.toFixed(2)}</span></div>
      <div class="detail-row"><span>Low</span><span class="v">${session.prior_low.toFixed(2)}</span></div>
      <div class="detail-row"><span>Close</span><span class="v">${session.prior_close.toFixed(2)}</span></div>
    </div>

    <div class="detail-section">
      <h4>SESSION</h4>
      <div class="detail-row"><span>Open</span><span class="v">${session.session_open.toFixed(2)}</span></div>
      <div class="detail-row"><span>High</span><span class="v">${session.day_high.toFixed(2)}</span></div>
      <div class="detail-row"><span>Low</span><span class="v">${session.day_low.toFixed(2)}</span></div>
      <div class="detail-row"><span>Close</span><span class="v">${session.day_close.toFixed(2)}</span></div>
    </div>

    <div class="detail-section">
      <h4>DATA</h4>
      <div class="detail-row"><span>Chart resolution</span><span class="v">${resolutionLabel(session.chart_resolution || session.bars_resolution)}</span></div>
      <div class="detail-row"><span>Available TFs</span><span class="v">${(session.available_resolutions || []).map((r) => TF_LABELS[r] || r).join(", ")}</span></div>
      <div class="detail-row"><span>Economic events</span><span class="v">${(session.economic_events || []).join(", ") || "none"}</span></div>
    </div>
  `;
}

function svgCandles(bars, width = 280, height = 56) {
  if (!bars.length) return `<svg width="${width}" height="${height}"></svg>`;
  const highs = bars.map((b) => b.high);
  const lows = bars.map((b) => b.low);
  const max = Math.max(...highs);
  const min = Math.min(...lows);
  const range = max - min || 1;
  const pad = 4;
  const plotH = height - pad * 2;
  const slot = width / bars.length;
  const bodyW = Math.max(1.5, slot * 0.6);

  const y = (price) => pad + (1 - (price - min) / range) * plotH;

  let svg = `<svg width="100%" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">`;
  bars.forEach((b, i) => {
    const cx = i * slot + slot / 2;
    const up = b.close >= b.open;
    const color = up ? "#3b82f6" : "#ef4444";
    const yHigh = y(b.high);
    const yLow = y(b.low);
    const yOpen = y(b.open);
    const yClose = y(b.close);
    const bodyTop = Math.min(yOpen, yClose);
    const bodyH = Math.max(1, Math.abs(yClose - yOpen));
    svg += `<line x1="${cx}" y1="${yHigh}" x2="${cx}" y2="${yLow}" stroke="${color}" stroke-width="1"/>`;
    svg += `<rect x="${cx - bodyW / 2}" y="${bodyTop}" width="${bodyW}" height="${bodyH}" fill="${color}"/>`;
  });
  svg += `</svg>`;
  return svg;
}

function matchCardHtml(session, { isReference = false } = {}) {
  const tags = [label(session.open_vs_prior)];
  const firstBar =
    session.market === "UK100" ? session.first5_dir : session.first15_dir;
  if (firstBar)
    tags.push(`${firstBarLabel(session.market)} ${label(firstBar)}`);
  if (session.second15_dir) tags.push(`2nd ${label(session.second15_dir)}`);
  (session.economic_events || []).forEach((ev) => tags.push(`${ev} day`));
  const score =
    session.match_score != null
      ? `<span class="match-score">${session.match_score.toFixed(1)}%</span>`
      : "";

  return `
    <div class="match-card ${isReference ? "reference" : ""}" data-date="${session.date}">
      <div class="match-card-header">
        <span class="gap-pill">Gap ${fmtPct(session.gap_pct)}</span>
        <span>${isReference ? "Reference" : label(session.open_vs_prior)}</span>
        ${score}
      </div>
      <div class="match-card-chart">${svgCandles(session.bars || [])}</div>
      <div class="match-card-tags">${tags.map((t) => `<span class="tag">${t}</span>`).join("")}</div>
      <div class="match-card-footer">
        <span>${session.date}</span>
        <span>${session.day_of_week}</span>
      </div>
    </div>
  `;
}

function wireCardClicks() {
  $all(".match-card").forEach((card) => {
    card.addEventListener("click", async () => {
      const date = card.dataset.date;
      $all(".match-card").forEach((c) => c.classList.remove("selected"));
      card.classList.add("selected");
      state.selectedDate = date;
      const detail = await fetchSessionDetail(date);
      renderMainChart(detail);
      renderDetail(detail);
    });
  });
}

let searchRequestId = 0;

async function runSearch() {
  if (!state.referenceDate) return;
  const requestId = ++searchRequestId;
  const data = await fetchMatches();
  if (requestId !== searchRequestId) return; // a newer runSearch() superseded this one

  $("#matchesCount").textContent = `${data.count + 1} sessions`;

  const cards = [matchCardHtml(state.referenceSession, { isReference: true })];
  data.sessions.forEach((s) => cards.push(matchCardHtml(s)));
  state.matchSessions = data.sessions;
  $("#matchesGrid").innerHTML = cards.join("");
  wireCardClicks();

  // keep whichever card is currently "selected" highlighted, default to reference
  const selDate = state.selectedDate || state.referenceDate;
  const selCard = document.querySelector(`.match-card[data-date="${selDate}"]`);
  if (selCard) selCard.classList.add("selected");
}

let analyzeRequestId = 0;

async function analyzeDate(date, { silent = false } = {}) {
  const requestId = ++analyzeRequestId;
  let detail;
  try {
    detail = await fetchSessionDetail(date);
  } catch (e) {
    if (!silent) {
      alert(
        `No session data for ${date} (market holiday/weekend, or outside the downloaded 2-year window).`,
      );
    }
    return false;
  }
  if (requestId !== analyzeRequestId) return false; // a newer analyzeDate() superseded this one

  state.referenceDate = date;
  state.referenceSession = detail;
  state.selectedDate = date;
  $("#refDate").value = date;

  // seed the filters from the reference session's own conditions
  setButtonGroupValue("gap_dir", detail.gap_dir);
  setButtonGroupValue("open_vs_prior", detail.open_vs_prior);

  renderMainChart(detail);
  renderDetail(detail);
  await runSearch();
  return true;
}

function setDateNotice(text) {
  const el = $("#dateNotice");
  if (!text) {
    el.hidden = true;
    el.textContent = "";
  } else {
    el.hidden = false;
    el.textContent = text;
  }
}

async function loadMarket() {
  // keep whatever reference date was selected (so switching markets compares
  // the SAME date across markets), falling back only if this market has no
  // session on that date (holiday/weekend mismatch between exchanges).
  const wantedDate = state.referenceDate;
  state.referenceDate = null;
  state.referenceSession = null;
  state.selectedDate = null;
  setDateNotice(null);

  const meta = await fetchMeta();
  const firstBarHeading = document
    .querySelector('.btn-row[data-group="first15_dir"]')
    ?.parentElement.querySelector("label");
  if (firstBarHeading) {
    firstBarHeading.innerHTML = `${state.market === "UK100" ? "FIRST 5 MIN BAR" : "FIRST 15 MIN BAR"} <span class="hint">${state.market === "UK100" ? "FTSE strategy input" : "only last ~60 sessions have real 15m data"}</span>`;
  }
  const b = meta.sessions_with_bars || {};
  $("#metaLine").textContent =
    `${meta.total_sessions} sessions · ${meta.date_range.start} → ${meta.date_range.end} · TF coverage: 3m ${b["3min"] || 0} · 5m ${b["5min"] || 0} · 15m ${b["15min"] || 0} · 1H ${b["60m"] || 0}`;
  $("#refDate").max = meta.latest_complete_date;

  let ok = false;
  if (wantedDate) {
    ok = await analyzeDate(wantedDate, { silent: true });
    if (!ok) {
      setDateNotice(
        `No ${wantedDate} session for this market (holiday/weekend or outside the 2y window) — showing latest session instead.`,
      );
    }
  }
  if (!ok) {
    await analyzeDate(meta.latest_complete_date);
  }
}

async function init() {
  setupButtonGroups();
  $("#analyzeBtn").addEventListener("click", () => {
    const date = $("#refDate").value;
    if (date) {
      setDateNotice(null);
      analyzeDate(date);
    }
  });
  $("#clearFiltersBtn").addEventListener("click", clearAllFilters);
  $("#saveSetupBtn").addEventListener("click", saveCurrentSetup);
  renderSavedSetups();

  $all("#tfRow button").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      changeResolution(btn.dataset.tf);
    });
  });
  $("#zoomInBtn").addEventListener("click", () => adjustChartZoom("in"));
  $("#zoomOutBtn").addEventListener("click", () => adjustChartZoom("out"));

  const markets = await fetchMarkets();
  $("#marketSelect").innerHTML = markets
    .map((m) => `<option value="${m.code}">${m.name}</option>`)
    .join("");
  $("#marketSelect").value = state.market;
  $("#brandSub").textContent =
    `${markets.find((m) => m.code === state.market).name} · real Yahoo Finance data, last 2y`;
  $("#marketSelect").addEventListener("change", (e) => {
    state.market = e.target.value;
    $("#brandSub").textContent =
      `${markets.find((m) => m.code === state.market).name} · real Yahoo Finance data, last 2y`;
    loadMarket();
  });

  const events = await fetchEconomicEvents();
  $("#econEvents").innerHTML =
    `<option value="">Any / None</option>` +
    Object.entries(events)
      .map(
        ([code, info]) =>
          `<option value="${code}">${info.label} (${info.count} in 2y)</option>`,
      )
      .join("");
  $("#econEvents").addEventListener("change", (e) => {
    const code = e.target.value;
    clearPatternFilterButtons();
    state.filters.economic_event = code || null;
    runSearch();
  });

  await loadMarket();
}

init();
