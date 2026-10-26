const API = "/api";
const form = document.querySelector("#journalForm");
const textFields = [
  "status", "market", "instrument", "strategy", "setup_type", "trade_date", "direction",
  "open_vs_prior", "first15_direction", "second15_direction", "economic_events", "chart_reference", "account_currency",
  "analysis", "expectation", "invalidation", "emotion_before", "actual_entry_time", "actual_exit_time",
  "exit_reason", "execution_notes", "followed_plan", "emotion_after", "review_notes", "lesson_learned",
];
const numberFields = [
  "gap_pct", "second_bar_high", "second_bar_low", "planned_entry", "planned_stop", "planned_target",
  "planned_size", "point_value", "confidence_before", "actual_entry", "actual_stop", "actual_target",
  "actual_exit", "actual_size", "actual_fees", "slippage_points", "broker_pnl",
];
const fieldIds = [...textFields, ...numberFields];
let allTrades = [];
let markets = [];

function $(selector) { return document.querySelector(selector); }

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function localToday() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function numberValue(id) {
  const value = $(`#${id}`).value.trim();
  if (!value) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function calculatePlanPreview() {
  const entry = numberValue("planned_entry");
  const stop = numberValue("planned_stop");
  const target = numberValue("planned_target");
  const direction = $("#direction").value;
  let risk = null;
  let reward = null;
  if (entry != null && stop != null && target != null) {
    risk = direction === "long" ? entry - stop : stop - entry;
    reward = direction === "long" ? target - entry : entry - target;
  }
  if (risk > 0 && reward > 0) {
    $("#plannedRrPreview").textContent = `1 : ${(reward / risk).toFixed(2)}`;
    $("#plannedRrPreview").className = "valid-value";
  } else if (entry != null && stop != null && target != null) {
    $("#plannedRrPreview").textContent = direction === "long"
      ? "Check long levels: stop < entry < target"
      : "Check short levels: target < entry < stop";
    $("#plannedRrPreview").className = "invalid-value";
  } else {
    $("#plannedRrPreview").textContent = "—";
    $("#plannedRrPreview").className = "";
  }

  const size = numberValue("planned_size");
  const pointValue = numberValue("point_value");
  if (entry != null && stop != null && size > 0 && pointValue > 0) {
    const amount = Math.abs(entry - stop) * size * pointValue;
    const currency = $("#account_currency").value.trim();
    $("#riskPreview").textContent = `${amount.toFixed(2)}${currency ? ` ${currency}` : ""}`;
  } else {
    $("#riskPreview").textContent = "Enter stop, size, and point value";
  }
}

function calculateRealizedPreview() {
  const entry = numberValue("actual_entry");
  const exit = numberValue("actual_exit");
  const stop = numberValue("actual_stop") ?? numberValue("planned_stop");
  if (entry == null || exit == null || stop == null || entry === stop) {
    $("#realizedPreview").textContent = "Enter actual entry and exit to calculate points and R. R uses the actual stop when supplied, otherwise the planned stop.";
    return;
  }
  const sign = $("#direction").value === "long" ? 1 : -1;
  const points = (exit - entry) * sign;
  const r = points / Math.abs(entry - stop);
  const brokerPnl = numberValue("broker_pnl");
  const currency = $("#account_currency").value.trim();
  $("#realizedPreview").textContent = `Price result: ${points >= 0 ? "+" : ""}${points.toFixed(2)} pts (${r >= 0 ? "+" : ""}${r.toFixed(2)}R).${brokerPnl != null ? ` Broker P&L: ${brokerPnl.toFixed(2)}${currency ? ` ${currency}` : ""}.` : ""}`;
}

function showNotice(message, isError = false) {
  const notice = $("#journalNotice");
  notice.textContent = message;
  notice.className = `journal-notice${isError ? " error" : ""}`;
  notice.hidden = !message;
}

function visibleTrades() {
  const q = $("#searchTrades").value.trim().toLocaleLowerCase();
  const market = $("#filterMarket").value;
  const status = $("#filterStatus").value;
  const from = $("#filterFrom").value;
  const to = $("#filterTo").value;
  return allTrades.filter((trade) => {
    if (market && trade.market !== market) return false;
    if (status && trade.status !== status) return false;
    if (from && trade.trade_date < from) return false;
    if (to && trade.trade_date > to) return false;
    return !q || Object.values(trade).some((value) => String(value ?? "").toLocaleLowerCase().includes(q));
  });
}

function renderSummary(trades) {
  const closed = trades.filter((trade) => trade.status === "closed");
  const measured = closed.filter((trade) => trade.realized_r !== null && trade.realized_r !== "");
  const wins = measured.filter((trade) => Number(trade.realized_r) > 0).length;
  const averageR = measured.length
    ? measured.reduce((sum, trade) => sum + Number(trade.realized_r), 0) / measured.length
    : null;
  const reviewed = closed.filter((trade) => ["yes", "partly", "no"].includes(trade.followed_plan));
  const followed = reviewed.filter((trade) => trade.followed_plan === "yes").length;
  const stats = [
    ["Planned", trades.filter((trade) => trade.status === "planned").length, "Current filter"],
    ["Open", trades.filter((trade) => trade.status === "open").length, "Current filter"],
    ["Closed", closed.length, "Current filter"],
    ["Win rate", measured.length ? `${Math.round(wins / measured.length * 100)}%` : "—", `${measured.length} closed trades with R data`],
    ["Average R", averageR == null ? "—" : `${averageR >= 0 ? "+" : ""}${averageR.toFixed(2)}R`, `${measured.length} measured trades`],
    ["Followed plan", reviewed.length ? `${Math.round(followed / reviewed.length * 100)}%` : "—", `${reviewed.length} reviewed trades`],
  ];
  $("#journalSummary").innerHTML = stats.map(([label, value, detail]) => `
    <article class="journal-stat"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(detail)}</small></article>
  `).join("");
}

function marketName(code) {
  return markets.find((market) => market.code === code)?.name || code || "Market";
}

function displayNumber(value, suffix = "") {
  return value === null || value === undefined || value === "" || !Number.isFinite(Number(value))
    ? "—"
    : `${Number(value).toFixed(2)}${suffix}`;
}

function renderTrades() {
  const trades = visibleTrades();
  renderSummary(trades);
  $("#entryCount").textContent = `${trades.length} ${trades.length === 1 ? "entry" : "entries"}`;
  const list = $("#tradeList");
  if (!trades.length) {
    list.innerHTML = '<div class="journal-empty">No journal entries match these filters. Add a planned trade to get started.</div>';
    return;
  }
  list.innerHTML = trades.map((trade) => {
    const plan = `Entry ${displayNumber(trade.planned_entry)} · SL ${displayNumber(trade.planned_stop)} · TP ${displayNumber(trade.planned_target)}${trade.planned_rr ? ` · ${displayNumber(trade.planned_rr, "R")}` : ""}`;
    const realized = trade.realized_points === null || trade.realized_points === ""
      ? "Not closed"
      : `${displayNumber(trade.realized_points, " pts")} · ${displayNumber(trade.realized_r, "R")}`;
    const actualFill = `${displayNumber(trade.actual_entry)} → ${displayNumber(trade.actual_exit)}`;
    const brokerPnl = trade.broker_pnl === null || trade.broker_pnl === ""
      ? "—"
      : `${displayNumber(trade.broker_pnl)}${trade.account_currency ? ` ${escapeHtml(trade.account_currency)}` : ""}`;
    const note = trade.analysis || trade.expectation || trade.review_notes || "No notes added yet.";
    return `<article class="trade-card">
      <div class="trade-card-head">
        <div><div class="trade-card-title">${escapeHtml(trade.trade_date)} · ${escapeHtml(marketName(trade.market))} · ${escapeHtml((trade.direction || "").toUpperCase())}</div>
        <div class="trade-card-sub">${escapeHtml(trade.strategy || "Strategy not set")}${trade.instrument ? ` · ${escapeHtml(trade.instrument)}` : ""}${trade.setup_type ? ` · ${escapeHtml(trade.setup_type)}` : ""}</div></div>
        <span class="status-pill ${escapeHtml(trade.status)}">${escapeHtml(trade.status)}</span>
      </div>
      <div class="trade-card-metrics">
        <div><span>PLANNED LEVELS</span><strong>${escapeHtml(plan)}</strong></div>
        <div><span>ACTUAL ENTRY → EXIT</span><strong>${escapeHtml(actualFill)}</strong></div>
        <div><span>REALIZED</span><strong>${escapeHtml(realized)}</strong></div>
        <div><span>BROKER P&amp;L</span><strong>${escapeHtml(brokerPnl)}</strong></div>
        <div><span>PLAN FOLLOWED</span><strong>${escapeHtml(trade.followed_plan || "Not reviewed")}</strong></div>
      </div>
      <div class="trade-card-note">${escapeHtml(note)}</div>
      <div class="trade-card-actions"><button class="btn-secondary" type="button" data-edit-trade="${escapeHtml(trade.trade_id)}">Edit / review</button></div>
    </article>`;
  }).join("");
  list.querySelectorAll("[data-edit-trade]").forEach((button) => {
    button.addEventListener("click", () => editTrade(button.dataset.editTrade));
  });
}

function updateFilterMarkets() {
  $("#filterMarket").innerHTML = '<option value="">All markets</option>' + markets.map((market) =>
    `<option value="${escapeHtml(market.code)}">${escapeHtml(market.name)}</option>`).join("");
}

function resetForm() {
  form.reset();
  $("#tradeId").value = "";
  $("#trade_date").value = localToday();
  $("#market").value = markets.some((market) => market.code === "DAX40") ? "DAX40" : (markets[0]?.code || "");
  $("#strategy").value = "SRS";
  $("#direction").value = "long";
  $("#status").value = "planned";
  $("#formTitle").textContent = "New trade entry";
  $("#saveTradeBtn").textContent = "Save trade";
  $("#saveState").textContent = "";
  $("#saveState").className = "save-state";
  calculatePlanPreview();
  calculateRealizedPreview();
}

function editTrade(tradeId) {
  const trade = allTrades.find((entry) => entry.trade_id === tradeId);
  if (!trade) return;
  $("#tradeId").value = trade.trade_id;
  fieldIds.forEach((id) => {
    const element = $(`#${id}`);
    const value = trade[id];
    element.value = value == null ? "" : value;
  });
  $("#formTitle").textContent = `Edit trade · ${trade.trade_date}`;
  $("#saveTradeBtn").textContent = "Save changes";
  $("#saveState").textContent = "";
  calculatePlanPreview();
  calculateRealizedPreview();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function collectPayload() {
  const payload = {};
  textFields.forEach((id) => { payload[id] = $(`#${id}`).value.trim() || null; });
  numberFields.forEach((id) => { payload[id] = numberValue(id); });
  if (payload.actual_exit != null && payload.status !== "cancelled") payload.status = "closed";
  return payload;
}

async function handleSubmit(event) {
  event.preventDefault();
  const saveState = $("#saveState");
  saveState.textContent = "Saving…";
  saveState.className = "save-state";
  const tradeId = $("#tradeId").value;
  try {
    const response = await fetch(`${API}/journal${tradeId ? `/${encodeURIComponent(tradeId)}` : ""}`, {
      method: tradeId ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectPayload()),
    });
    const result = await response.json();
    if (!response.ok) {
      const detail = Array.isArray(result.detail) ? result.detail.map((item) => item.msg).join("; ") : result.detail;
      throw new Error(detail || `Save failed (${response.status})`);
    }
    saveState.textContent = "Saved to local CSV";
    saveState.className = "save-state success";
    showNotice(tradeId ? "Trade journal entry updated." : "Trade saved. You can edit it later to add execution and review details.");
    await loadTrades();
  } catch (error) {
    saveState.textContent = error.message || "Unable to save this entry.";
    saveState.className = "save-state error";
    showNotice(error.message || "Unable to save this entry.", true);
  }
}

async function loadMarkets() {
  try {
    const response = await fetch(`${API}/markets`);
    if (!response.ok) throw new Error("Unable to load markets");
    markets = await response.json();
  } catch {
    markets = [{ code: "DAX40", name: "DAX 40" }];
  }
  $("#market").innerHTML = markets.map((market) => `<option value="${escapeHtml(market.code)}">${escapeHtml(market.name)}</option>`).join("");
  updateFilterMarkets();
  $("#market").value = "DAX40";
}

async function loadTrades() {
  try {
    const response = await fetch(`${API}/journal`);
    if (!response.ok) throw new Error(`Journal request failed (${response.status})`);
    const data = await response.json();
    allTrades = data.trades || [];
    renderTrades();
  } catch (error) {
    $("#entryCount").textContent = "Unable to load entries";
    $("#tradeList").innerHTML = `<div class="journal-empty">${escapeHtml(error.message || "Unable to load the journal.")}</div>`;
    showNotice("The journal could not load. Check that the app server is running.", true);
  }
}

async function exportCsv() {
  try {
    const response = await fetch(`${API}/journal/export.csv`);
    if (!response.ok) throw new Error(`Export failed (${response.status})`);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "trade_journal.csv";
    anchor.click();
    URL.revokeObjectURL(url);
    showNotice("CSV export downloaded.");
  } catch (error) {
    showNotice(error.message || "Unable to export the journal.", true);
  }
}

async function init() {
  await loadMarkets();
  resetForm();
  await loadTrades();
  form.addEventListener("submit", handleSubmit);
  $("#newTradeBtn").addEventListener("click", () => { resetForm(); showNotice(""); });
  $("#resetFormBtn").addEventListener("click", resetForm);
  $("#exportJournalBtn").addEventListener("click", exportCsv);
  ["#searchTrades", "#filterMarket", "#filterStatus", "#filterFrom", "#filterTo"].forEach((selector) => {
    $(selector).addEventListener("input", renderTrades);
    $(selector).addEventListener("change", renderTrades);
  });
  ["#planned_entry", "#planned_stop", "#planned_target", "#planned_size", "#point_value", "#account_currency", "#direction"]
    .forEach((selector) => $(selector).addEventListener("input", calculatePlanPreview));
  ["#actual_entry", "#actual_exit", "#actual_stop", "#planned_stop", "#broker_pnl", "#account_currency", "#direction"]
    .forEach((selector) => $(selector).addEventListener("input", calculateRealizedPreview));
  $("#direction").addEventListener("change", () => { calculatePlanPreview(); calculateRealizedPreview(); });
}

init();
