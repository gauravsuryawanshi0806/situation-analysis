const API = "/api";
const marketSelect = document.querySelector("#studyMarket");
const weekCountSelect = document.querySelector("#weekCount");
const weekDays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

function formatMove(value) {
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(2)}%`;
}

function stat(label, value, detail = "") {
  return `<article class="study-stat"><span class="study-stat-label">${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>${detail ? `<small>${escapeHtml(detail)}</small>` : ""}</article>`;
}

function renderTable(data) {
  document.querySelector("#studyBrandSub").textContent = `${data.market_name} weekday history`;
  document.querySelector("#studyDescription").textContent = `Daily direction and open-to-close move for each ${data.market_name} weekday session.`;
  document.querySelector("#weekCountLabel").textContent = `${data.week_count} weeks shown`;
  const counts = Object.fromEntries(weekDays.map((day) => [day, { positive: 0, negative: 0, flat: 0, count: 0 }]));
  for (const week of data.weeks) {
    for (const day of weekDays) {
      const entry = week.days[day];
      if (entry) {
        counts[day][entry.direction] += 1;
        counts[day].count += 1;
      }
    }
  }
  document.querySelector("#studySummary").innerHTML = weekDays.map((day) => {
    const tally = counts[day];
    const positiveRate = tally.count ? `${Math.round(tally.positive / tally.count * 100)}% positive` : "No sessions";
    return stat(`${day} positive`, positiveRate, `${tally.positive} positive · ${tally.negative} negative · ${tally.flat} flat`);
  }).join("");

  const rows = document.querySelector("#weekRows");
  if (!data.weeks.length) {
    rows.innerHTML = '<tr><td class="study-empty" colspan="6">No weekday sessions found.</td></tr>';
    return;
  }
  rows.innerHTML = data.weeks.map((week) => `
    <tr>
      <td>${escapeHtml(week.week_start)}</td>
      ${weekDays.map((day) => {
        const entry = week.days[day];
        if (!entry) return '<td class="weekday-direction-empty">—</td>';
        const direction = entry.direction[0].toUpperCase() + entry.direction.slice(1);
        return `<td class="weekday-direction-cell direction-${escapeHtml(entry.direction)}"><strong>${escapeHtml(direction)}</strong><span>${escapeHtml(formatMove(entry.move_pct))}</span><small>${escapeHtml(entry.date)}</small></td>`;
      }).join("")}
    </tr>`).join("");
}

async function loadDirections() {
  document.querySelector("#weekRows").innerHTML = '<tr><td class="study-empty" colspan="6">Loading…</td></tr>';
  const query = new URLSearchParams({ market: marketSelect.value, weeks: weekCountSelect.value });
  try {
    const response = await fetch(`${API}/analysis/weekday-directions?${query}`);
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    renderTable(await response.json());
  } catch (error) {
    document.querySelector("#weekCountLabel").textContent = "";
    document.querySelector("#studySummary").innerHTML = '<div class="study-loading">Unable to load weekday directions. Check that the app server is running.</div>';
    document.querySelector("#weekRows").innerHTML = "";
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
  loadDirections();
}

marketSelect.addEventListener("change", loadDirections);
weekCountSelect.addEventListener("change", loadDirections);
initializeMarkets();
