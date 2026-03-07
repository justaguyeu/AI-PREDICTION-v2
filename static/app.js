/* ══════════════════════════════════════════════════════════
   BetPawa AI Predictor – Frontend Logic
   All 14 BetPawa market predictions rendered dynamically.
   ══════════════════════════════════════════════════════════ */

/* ─── State ─────────────────────────────────────────────── */
let allMatches = [];
let activeMatch = null;

/* ─── DOM Refs ──────────────────────────────────────────── */
const $ = id => document.getElementById(id);
const $q = sel => document.querySelector(sel);

/* ─── Boot ──────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  loadMatches();
  initSearch();
  $("retry-btn").addEventListener("click", loadMatches);
  $("last-updated").textContent = "Updated: " + new Date().toLocaleTimeString();
});

/* ─── Tab System ────────────────────────────────────────── */
function initTabs() {
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      $("tab-" + btn.dataset.tab).classList.add("active");
    });
  });
}

/* ─── Match Loading ─────────────────────────────────────── */
async function loadMatches() {
  $("sidebar-loading").classList.remove("hidden");
  $("matches-list").classList.add("hidden");
  $("sidebar-error").classList.add("hidden");

  try {
    const res = await fetch("/api/matches");
    const data = await res.json();

    if (!res.ok || data.error) throw new Error(data.error || "Server error");

    allMatches = data.matches || [];
    $("sidebar-loading").classList.add("hidden");

    if (allMatches.length === 0) {
      $("sidebar-error").classList.remove("hidden");
      $("sidebar-error").querySelector("p").textContent = "No fixtures found for today.";
      return;
    }

    renderMatchList(allMatches);
    $("matches-list").classList.remove("hidden");

  } catch (err) {
    console.error("Match load failed:", err);
    $("sidebar-loading").classList.add("hidden");
    $("sidebar-error").classList.remove("hidden");
  }
}

function renderMatchList(matches) {
  const list = $("matches-list");
  list.innerHTML = "";
  matches.forEach((m, i) => {
    const item = document.createElement("div");
    item.className = "match-item";
    item.id = "match-item-" + i;
    item.innerHTML = `
      <div class="match-teams">${esc(m.home)} vs ${esc(m.away)}</div>
      <div class="match-meta">Football · Click to predict</div>
    `;
    item.addEventListener("click", () => selectMatch(m, item));
    list.appendChild(item);
  });
}

/* ─── Search ────────────────────────────────────────────── */
function initSearch() {
  $("match-search").addEventListener("input", e => {
    const q = e.target.value.toLowerCase();
    document.querySelectorAll(".match-item").forEach(el => {
      const text = el.querySelector(".match-teams").textContent.toLowerCase();
      el.style.display = text.includes(q) ? "" : "none";
    });
  });
}

/* ─── Match Selection ───────────────────────────────────── */
function selectMatch(match, itemEl) {
  document.querySelectorAll(".match-item").forEach(el => el.classList.remove("active"));
  itemEl.classList.add("active");
  activeMatch = match;

  $("empty-state").classList.add("hidden");
  $("prediction-view").classList.remove("hidden");
  $("analyzing-state").classList.remove("hidden");
  $("result-container").classList.add("hidden");

  // Update hero header immediately
  $("p-home").textContent = match.home;
  $("p-away").textContent = match.away;
  $("p-home-avatar").textContent = match.home[0];
  $("p-away-avatar").textContent = match.away[0];
  $("p-confidence-badge").textContent = "Analysing…";
  $("p-confidence-badge").className = "conf-badge PENDING";

  performPrediction(match);
}

/* ─── Prediction Fetch & Render ─────────────────────────── */
async function performPrediction(match) {
  try {
    const res = await fetch("/api/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ home: match.home, away: match.away }),
    });
    const data = await res.json();

    $("analyzing-state").classList.add("hidden");

    if (!res.ok || data.error) {
      showError(data.error || "Prediction failed");
      return;
    }
    if (data.status === "insufficient_data") {
      showError("Not enough web data found for this match.");
      return;
    }

    renderPrediction(data);
    $("result-container").classList.remove("hidden");

  } catch (err) {
    console.error("Prediction failed:", err);
    showError("Network error – check the server is running.");
  }
}

function showError(msg) {
  $("analyzing-state").classList.add("hidden");
  $("result-container").classList.remove("hidden");
  $("result-container").innerHTML = `
    <div style="text-align:center;padding:40px;color:#ef4444;">
      <div style="font-size:40px;margin-bottom:12px;">⚠️</div>
      <p style="color:#94a3b8;">${esc(msg)}</p>
    </div>`;
}

/* ─── Rendering: all 14 markets ─────────────────────────── */
function renderPrediction(data) {
  const m = data.markets || {};
  const conf = data.overall_confidence || "LOW";
  const meta = data.analysis_meta || {};

  // Overall confidence badge
  $("p-confidence-badge").textContent = conf + " Confidence";
  $("p-confidence-badge").className = "conf-badge " + conf;

  // ── xG Bar ────────────────────────────────────────────────
  const xgH = meta.home_xg || 1.35;
  const xgA = meta.away_xg || 1.05;
  const xgTotal = xgH + xgA;
  const xgHPct = (xgH / xgTotal * 100).toFixed(1);
  const xgAPct = (xgA / xgTotal * 100).toFixed(1);
  $("xg-home-label").textContent = "xG " + xgH.toFixed(2);
  $("xg-away-label").textContent = "xG " + xgA.toFixed(2);
  $("xg-bar-home").style.width = xgHPct + "%";
  $("xg-bar-away").style.width = xgAPct + "%";

  // ── 1X2 FT ────────────────────────────────────────────────
  renderCard1x2(
    m["1x2_ft"],
    "pick-1x2-ft", "conf-1x2-ft",
    "seg-1x2-1", "seg-1x2-x", "seg-1x2-2"
  );

  // ── Boosted ───────────────────────────────────────────────
  if (m["boosted"]) {
    $("pick-boosted").textContent = m["boosted"].prediction || "--";
    $("conf-boosted").textContent = m["boosted"].confidence || "--";
  }

  // ── Double Chance ─────────────────────────────────────────
  if (m["double_chance"]) {
    const dc = m["double_chance"];
    $("pick-dc").textContent = dc.prediction || "--";
    $("conf-dc").textContent = dc.confidence || "--";
    renderOptions("opts-dc", dc.options, dc.prediction);
  }

  // ── BTTS ──────────────────────────────────────────────────
  if (m["btts"]) {
    const btts = m["btts"];
    const pickEl = $("pick-btts");
    pickEl.className = "pick-badge " + (btts.prediction || "");
    pickEl.textContent = btts.prediction || "--";
    $("conf-btts").textContent = btts.confidence || "--";
    // Mini bar
    const barEl = $("bar-btts");
    const yesPct = (btts.options && btts.options["YES"]) || 50;
    barEl.innerHTML = `
      <div class="mini-seg-yes" style="width:${yesPct}%"></div>
      <div class="mini-seg-no" style="width:${100 - yesPct}%"></div>`;
  }

  // ── O/U FT ────────────────────────────────────────────────
  renderOU($("pick-ou-ft"), $("conf-ou-ft"), $("lines-ou-ft"), m["ou_ft"]);

  // ── O/U Home ──────────────────────────────────────────────
  if (m["ou_home"]) {
    $("label-ou-home").textContent = m["ou_home"].label || "Home O/U | FT";
    renderOU($("pick-ou-home"), $("conf-ou-home"), $("lines-ou-home"), m["ou_home"]);
  }

  // ── O/U Away ──────────────────────────────────────────────
  if (m["ou_away"]) {
    $("label-ou-away").textContent = m["ou_away"].label || "Away O/U | FT";
    renderOU($("pick-ou-away"), $("conf-ou-away"), $("lines-ou-away"), m["ou_away"]);
  }

  // ── 1X2 H1 ────────────────────────────────────────────────
  renderCard1x2(m["1x2_h1"], "pick-1x2-h1", "conf-1x2-h1", "seg-h1-1", "seg-h1-x", "seg-h1-2");

  // ── 1X2 H2 ────────────────────────────────────────────────
  renderCard1x2(m["1x2_h2"], "pick-1x2-h2", "conf-1x2-h2", "seg-h2-1", "seg-h2-x", "seg-h2-2");

  // ── O/U H1 ────────────────────────────────────────────────
  renderOU($("pick-ou-h1"), $("conf-ou-h1"), $("lines-ou-h1"), m["ou_h1"]);

  // ── O/U H2 ────────────────────────────────────────────────
  renderOU($("pick-ou-h2"), $("conf-ou-h2"), $("lines-ou-h2"), m["ou_h2"]);

  // ── Next Goal ─────────────────────────────────────────────
  if (m["next_goal"]) {
    const ng = m["next_goal"];
    $("pick-ng").textContent = ng.prediction || "--";
    $("conf-ng").textContent = ng.confidence || "--";
    renderOptions("opts-ng", ng.options, ng.prediction);
  }

  // ── HT/FT ─────────────────────────────────────────────────
  if (m["ht_ft"]) {
    const htft = m["ht_ft"];
    $("pick-htft").textContent = htft.prediction || "--";
    $("conf-htft").textContent = htft.confidence || "--";
    renderHTFT("opts-htft", htft.options, htft.prediction);
  }

  // ── Handicap ──────────────────────────────────────────────
  if (m["handicap"]) {
    const hcp = m["handicap"];
    $("pick-hcp").textContent = hcp.prediction || "--";
    $("conf-hcp").textContent = hcp.confidence || "--";
    renderOptions("opts-hcp", hcp.options, hcp.prediction);
  }

  // ── Correct Scores ────────────────────────────────────────
  renderScores(data.correct_scores || []);
}

/* ─── Helper Renderers ──────────────────────────────────── */
function renderCard1x2(market, pickId, confId, seg1Id, segXId, seg2Id) {
  if (!market) return;
  $(pickId).textContent = market.prediction || "--";
  $(confId).textContent = market.confidence || "--";
  const opts = market.options || {};
  const p1 = opts["1"] || 33, pX = opts["X"] || 33, p2 = opts["2"] || 34;

  const seg1 = $(seg1Id);
  const segX = $(segXId);
  const seg2 = $(seg2Id);

  if (seg1) { seg1.style.width = p1 + "%"; seg1.querySelector("small").textContent = p1 + "%"; }
  if (segX) { segX.style.width = pX + "%"; segX.querySelector("small").textContent = pX + "%"; }
  if (seg2) { seg2.style.width = p2 + "%"; seg2.querySelector("small").textContent = p2 + "%"; }
}

function renderOU(pickEl, confEl, linesEl, market) {
  if (!market || !pickEl) return;
  pickEl.textContent = market.prediction || "--";
  confEl.textContent = market.confidence || "--";
  if (!linesEl) return;
  const lines = market.all_thresholds || [];
  linesEl.innerHTML = lines.map(l =>
    `<span class="ou-chip ${l.pick.toLowerCase()}">${l.label} <b>${l.confidence}%</b></span>`
  ).join("");
}

function renderOptions(containerId, options, bestPick) {
  if (!options) return;
  const el = $(containerId);
  if (!el) return;
  el.innerHTML = Object.entries(options).map(([k, v]) =>
    `<span class="opt-chip ${k === bestPick ? 'best' : ''}">${esc(k)}: ${v}%</span>`
  ).join("");
}

function renderHTFT(containerId, options, bestPick) {
  if (!options) return;
  const el = $(containerId);
  if (!el) return;
  el.innerHTML = Object.entries(options).map(([k, v]) =>
    `<span class="htft-chip ${k === bestPick ? 'best' : ''}">${esc(k)}<br/>${v}%</span>`
  ).join("");
}

function renderScores(scores) {
  const podium = $("scores-podium");
  if (!podium) return;
  const ranks = ["🥇", "🥈", "🥉", "4th", "5th"];
  podium.innerHTML = scores.map((s, i) => `
    <div class="score-block">
      <div class="score-rank">${ranks[i] || (i+1)+"th"}</div>
      <div class="score-val">${esc(s.score)}</div>
      <div class="score-pct">${s.prob}%</div>
    </div>
  `).join("");
}

/* ─── Escape ─────────────────────────────────────────────── */
function esc(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
