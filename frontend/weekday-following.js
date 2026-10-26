const API = "/api";
const marketSelect = document.querySelector("#studyMarket");
const sourceDaySelect = document.querySelector("#sourceDay");
const sourceDirectionSelect = document.querySelector("#sourceDirection");

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

function formatPercent(value) {
  if (value == null || Number.isNaN(Number(value))) return "n/a";
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(2)}%`;
}

function rate(value) {
  return value == null ? "n/a" : `${value}%`;
}

function directionLabel(value) {
  return ({ positive: "Positive", negative: "Negative", flat: "Flat", up: "Up", down: "Down" })[value] || value || "n/a";
}

function stat(label, value, detail = "") {
  return `<article class="study-stat"><span class="study-stat-label">${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>${detail ? `<small>${escapeHtml(detail)}</small>` : ""}</article>`;
}

function renderStudy(data) {
  const counts = data.target_direction_counts;
  const pairName = `${data.source_day} → ${data.target_day}`;
  document.querySelector("#studyBrandSub").textContent = `${data.market_name} historical study`;
  document.querySelector("#studyTitle").textContent = pairName;
  document.querySelector("#studyDescription").textContent = `Compare ${data.target_day} outcomes after positive, negative, or flat ${data.market_name} ${data.source_day}s.`;
  document.querySelector("#sourceDirectionLabel").textContent = `${data.source_day} result`;
  document.querySelector("#sourceDateHeading").textContent = data.source_day;
  document.querySelector("#sourceDirectionHeading").textContent = `${data.source_day} direction`;
  document.querySelector("#sourceMoveHeading").textContent = `${data.source_day} move`;
  document.querySelector("#sourceGapHeading").textContent = `${data.source_day} gap`;
  document.querySelector("#targetDateHeading").textContent = data.target_day;
  document.querySelector("#targetDirectionHeading").textContent = `${data.target_day} direction`;
  document.querySelector("#targetMoveHeading").textContent = `${data.target_day} move`;
  document.querySelector("#targetGapHeading").textContent = `${data.target_day} gap`;
  document.querySelector("#resultsTitle").textContent = `Recent ${data.source_day}–${data.target_day} pairs`;
  document.querySelector("#studyPairCount").textContent = `${data.sample_count} observed pairs`;
  document.querySelector("#studySummary").innerHTML = [
    stat(`${data.source_day}–${data.target_day} pairs`, data.sample_count, `${data.source_day} filter: ${directionLabel(data.source_direction)}`),
    stat(`${data.target_day} positive`, rate(data.target_positive_pct), `${counts.positive} of ${data.sample_count} pairs`),
    stat(`${data.target_day} negative`, rate(data.target_negative_pct), `${counts.negative} of ${data.sample_count} pairs`),
    stat(`${data.target_day} flat`, rate(data.target_flat_pct), `${counts.flat} of ${data.sample_count} pairs`),
    stat(`${data.target_day} gap up`, rate(data.target_gap_up_pct)),
    stat(`Average ${data.target_day} move`, formatPercent(data.average_target_move_pct)),
  ].join("");

  const rows = document.querySelector("#studyRows");
  if (!data.pairs.length) {
    rows.innerHTML = '<tr><td class="study-empty" colspan="8">No weekday pairs found for this filter.</td></tr>';
    return;
  }
  rows.innerHTML = data.pairs.map((pair) => `
    <tr>
      <td>${escapeHtml(pair.source_date)}</td>
      <td class="direction-${escapeHtml(pair.source_direction)}">${escapeHtml(directionLabel(pair.source_direction))}</td>
      <td class="direction-${escapeHtml(pair.source_direction)}">${escapeHtml(formatPercent(pair.source_move_pct))}</td>
      <td>${escapeHtml(directionLabel(pair.source_gap_dir))} ${escapeHtml(formatPercent(pair.source_gap_pct))}</td>
      <td>${escapeHtml(pair.target_date)}</td>
      <td class="direction-${escapeHtml(pair.target_direction)}">${escapeHtml(directionLabel(pair.target_direction))}</td>
      <td class="direction-${escapeHtml(pair.target_direction)}">${escapeHtml(formatPercent(pair.target_move_pct))}</td>
      <td>${escapeHtml(directionLabel(pair.target_gap_dir))} ${escapeHtml(formatPercent(pair.target_gap_pct))}</td>
    </tr>`).join("");
}

async function loadStudy() {
  document.querySelector("#studyRows").innerHTML = '<tr><td class="study-empty" colspan="8">Loading…</td></tr>';
  const query = new URLSearchParams({
    market: marketSelect.value,
    source_day: sourceDaySelect.value,
    source_direction: sourceDirectionSelect.value,
    limit: "100",
  });
  try {
    const response = await fetch(`${API}/analysis/weekday-following?${query}`);
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    renderStudy(await response.json());
  } catch (error) {
    document.querySelector("#studyPairCount").textContent = "";
    document.querySelector("#studySummary").innerHTML = '<div class="study-loading">Unable to load weekday relationships. Check that the app server is running.</div>';
    document.querySelector("#studyRows").innerHTML = "";
  }
}

async function initializeMarkets() {
  try {
    const response = await fetch(`${API}/markets`);
    if (!response.ok) throw new Error("Unable to load markets");
    const markets = await response.json();
    marketSelect.innerHTML = markets.map((market) => `<option value="${escapeHtml(market.code)}">${escapeHtml(market.name)}</option>`).join("");
    marketSelect.value = "DAX40";
  } catch (error) {
    marketSelect.innerHTML = '<option value="DAX40">DAX 40</option>';
  }
  loadStudy();
}

sourceDaySelect.addEventListener("change", () => {
  document.querySelector("#sourceDirectionLabel").textContent = `${sourceDaySelect.value} result`;
});
marketSelect.addEventListener("change", loadStudy);
sourceDaySelect.addEventListener("change", loadStudy);
sourceDirectionSelect.addEventListener("change", loadStudy);
initializeMarkets();
