const API = "/api";
const directionSelect = document.querySelector("#studyDirection");
const marketSelect = document.querySelector("#studyMarket");

function formatPercent(value) {
  if (value == null || Number.isNaN(Number(value))) return "n/a";
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(2)}%`;
}

function directionLabel(value) {
  return (
    {
      positive: "Positive",
      negative: "Negative",
      flat: "Flat",
      up: "Up",
      down: "Down",
    }[value] ||
    value ||
    "n/a"
  );
}

function rate(value) {
  return value == null ? "n/a" : `${value}%`;
}

function stat(label, value, detail = "") {
  return `<article class="study-stat"><span class="study-stat-label">${label}</span><strong>${value}</strong>${detail ? `<small>${detail}</small>` : ""}</article>`;
}

function renderStudy(data) {
  const counts = data.monday_direction_counts;
  document.querySelector("#studyBrandSub").textContent =
    `${data.market_name} historical study`;
  document.querySelector("#studyDescription").textContent =
    `Compare Monday outcomes after positive, negative, or flat ${data.market_name} Fridays.`;
  document.querySelector("#playbookTitle").textContent =
    `Monday rules · ${data.market_name}`;
  document.querySelector("#longRule").textContent = data.long_rule;
  document.querySelector("#shortRule").textContent = data.short_rule;
  document.querySelector("#riskRule").textContent = data.risk_rule;
  document.querySelector("#strategySignalHeading").textContent =
    data.strategy_name || "Configured signal";
  document.querySelector("#strategyStopHeading").textContent =
    data.strategy_stop_points == null
      ? "Stop hit"
      : `${data.strategy_stop_points}-point stop hit`;
  document.querySelector("#playbookCaveat").textContent =
    `The historical bias is descriptive, not a prediction. It requires at least ${data.minimum_bias_pairs} Friday–Monday pairs and a ${data.minimum_bias_edge_pct}-point percentage edge between positive and negative Mondays; flat Mondays are excluded. Follow the listed market-specific trigger and stop rules, and treat no clear bias or insufficient data as no trade.`;
  const biasLabel =
    data.historical_bias === "long"
      ? "Historical Long bias"
      : data.historical_bias === "short"
        ? "Historical Short bias"
        : "No clear bias";
  document.querySelector("#playbookBias").textContent = biasLabel;
  document.querySelector("#playbookBias").className =
    `playbook-bias bias-${data.historical_bias}`;
  document.querySelector("#playbookReason").textContent =
    `${data.bias_reason} Directional Monday results: ${rate(data.monday_positive_directional_pct)} positive, ${rate(data.monday_negative_directional_pct)} negative.`;
  document.querySelector("#studyPairCount").textContent =
    `${data.sample_count} observed pairs`;
  document.querySelector("#studySummary").innerHTML = [
    stat(
      "Friday–Monday pairs",
      data.sample_count,
      `Friday filter: ${directionLabel(data.friday_direction)}`,
    ),
    stat(
      "Monday positive",
      rate(data.monday_positive_pct),
      `${counts.positive} of ${data.sample_count} pairs`,
    ),
    stat(
      "Monday negative",
      rate(data.monday_negative_pct),
      `${counts.negative} of ${data.sample_count} pairs`,
    ),
    stat("Monday gap up", rate(data.monday_gap_up_pct)),
    stat("Average Monday move", formatPercent(data.average_monday_move_pct)),
    stat(
      data.strategy_name ? "Strategy trades" : "Intraday strategy",
      data.strategy_name ? data.strategy_trade_count : "Not configured",
      data.strategy_name
        ? `${data.strategy_long_count} Long`
        : "Outcome stats only",
    ),
    stat(
      "Stop-loss hit",
      data.strategy_stop_points == null
        ? "n/a"
        : `${data.strategy_stop_hit_count} / ${data.strategy_trade_count}`,
      data.strategy_stop_hit_pct == null
        ? "No configured strategy"
        : `${rate(data.strategy_stop_hit_pct)} · ${data.strategy_stop_points} pts`,
    ),
  ].join("");

  const rows = document.querySelector("#studyRows");
  if (!data.pairs.length) {
    rows.innerHTML =
      '<tr><td class="study-empty" colspan="9">No Friday–Monday pairs found for this filter.</td></tr>';
    return;
  }

  rows.innerHTML = data.pairs
    .map(
      (pair) => `
    <tr>
      <td>${pair.friday_date}</td>
      <td class="direction-${pair.friday_direction}">${directionLabel(pair.friday_direction)}</td>
      <td class="direction-${pair.friday_direction}">${formatPercent(pair.friday_move_pct)}</td>
      <td>${pair.monday_date}</td>
      <td class="direction-${pair.monday_direction}">${directionLabel(pair.monday_direction)}</td>
      <td class="direction-${pair.monday_direction}">${formatPercent(pair.monday_move_pct)}</td>
      <td>${directionLabel(pair.monday_gap_dir)} ${formatPercent(pair.monday_gap_pct)}</td>
      <td>${pair.strategy_name ? directionLabel(pair.strategy_status) : "Not configured"}</td>
      <td>${pair.strategy_stop_hit == null ? "n/a" : pair.strategy_stop_hit ? "Yes" : "No"}</td>
    </tr>`,
    )
    .join("");
}

async function loadStudy() {
  document.querySelector("#studyRows").innerHTML =
    '<tr><td class="study-empty" colspan="9">Loading…</td></tr>';
  const query = new URLSearchParams({
    market: marketSelect.value,
    friday_direction: directionSelect.value,
    limit: "100",
  });
  try {
    const response = await fetch(`${API}/analysis/friday-monday?${query}`);
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    renderStudy(await response.json());
  } catch (error) {
    document.querySelector("#studyPairCount").textContent = "";
    document.querySelector("#studySummary").innerHTML =
      `<div class="study-loading">Unable to load the study. Check that the app server is running.</div>`;
    document.querySelector("#studyRows").innerHTML = "";
  }
}

async function initializeMarkets() {
  try {
    const response = await fetch(`${API}/markets`);
    if (!response.ok) throw new Error("Unable to load markets");
    const markets = await response.json();
    marketSelect.innerHTML = markets
      .map((market) => `<option value="${market.code}">${market.name}</option>`)
      .join("");
    marketSelect.value = "DAX40";
  } catch (error) {
    marketSelect.innerHTML = '<option value="DAX40">DAX 40</option>';
  }
  loadStudy();
}

marketSelect.addEventListener("change", loadStudy);
directionSelect.addEventListener("change", loadStudy);
initializeMarkets();
