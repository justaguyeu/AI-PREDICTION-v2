/* ══════════════════════════════════════════════════════════
   BetPawa AI Predictor – Deep Analysis Frontend
   ══════════════════════════════════════════════════════════ */

let allMatches = [];
let activeMatch = null;

const $ = id => document.getElementById(id);
const $q = sel => document.querySelector(sel);

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  loadMatches();
  loadBestBets();
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

/* ─── Best Bets Panel ───────────────────────────────────── */
async function loadBestBets() {
  try {
    const res = await fetch("/api/best-bets");
    const data = await res.json();
    const list = $("best-bets-list");
    const bets = data.best_bets || [];

    if (!bets.length) {
      list.innerHTML = `<p class="bb-empty">No analysed matches yet. Click a fixture to generate predictions.</p>`;
      return;
    }

    list.innerHTML = bets.map(b => `
      <div class="bb-item">
        <div class="bb-match">
          ${esc(b.home)} vs ${esc(b.away)}
          <small>${esc(b.market)}</small>
        </div>
        <div class="bb-pick">${esc(b.pick)}</div>
        <div class="bb-conf">${esc(b.confidence)}</div>
      </div>
    `).join("");
  } catch (err) {
    const list = $("best-bets-list");
    if (list) list.innerHTML = `<p class="bb-empty">Analyse a match to see best bets.</p>`;
  }
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

    if (!allMatches.length) {
      $("sidebar-error").classList.remove("hidden");
      $("sidebar-error").querySelector("p").textContent = "No fixtures found for today.";
      return;
    }
    renderMatchList(allMatches);
    $("matches-list").classList.remove("hidden");

  } catch (err) {
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
      <div class="match-meta">⚽ BetPawa TZ · Click to predict</div>
    `;
    item.addEventListener("click", () => selectMatch(m, item));
    list.appendChild(item);
  });
}

/* ─── Search ─────────────────────────────────────────────── */
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
  $("reasoning-card").classList.add("hidden");

  $("p-home").textContent = match.home;
  $("p-away").textContent = match.away;
  $("p-home-avatar").textContent = match.home[0];
  $("p-away-avatar").textContent = match.away[0];
  $("p-confidence-badge").textContent = "Analysing…";
  $("p-confidence-badge").className = "conf-badge PENDING";
  $("best-bet-banner").classList.add("hidden");
  $("data-source-badge").classList.add("hidden");

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

    if (!res.ok || data.error) { showError(data.error || "Prediction failed"); return; }
    renderPrediction(data);
    $("result-container").classList.remove("hidden");
    // Refresh best bets panel
    loadBestBets();

  } catch (err) {
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

/* ─── Main Render ────────────────────────────────────────── */
function renderPrediction(data) {
  const m    = data.markets    || {};
  const conf = data.overall_confidence || "LOW";
  const meta = data.analysis_meta      || {};
  const ts   = data.team_stats         || {};
  const bb   = data.best_bet           || {};
  const reas = data.reasoning          || "";

  // Confidence badge
  $("p-confidence-badge").textContent = conf + " Confidence";
  $("p-confidence-badge").className   = "conf-badge " + conf;

  // Data source badge
  const src = ts.data_source || meta.data_source || "";
  if (src) {
    const srcEl = $("data-source-badge");
    const srcLabels = {
      known_db:       "📊 Real Stats",
      web_extracted:  "🌐 Web Stats",
      league_average: "📐 League Avg",
      nlp_fallback:   "🔍 NLP Only"
    };
    srcEl.textContent = srcLabels[src] || src;
    srcEl.className = "data-source-badge " + src;
    srcEl.classList.remove("hidden");
  }

  // Best Bet banner on hero
  if (bb.pick && bb.confidence) {
    const banner = $("best-bet-banner");
    banner.textContent = `⭐ BEST BET: ${bb.pick} @ ${bb.confidence}`;
    banner.classList.remove("hidden");
  }

  // xG Bar
  const xgH = meta.home_xg || 1.48;
  const xgA = meta.away_xg || 1.17;
  const xgTotal = xgH + xgA;
  $("xg-home-label").textContent = `xG ${xgH.toFixed(2)}`;
  $("xg-away-label").textContent = `xG ${xgA.toFixed(2)}`;
  $("xg-bar-home").style.width = (xgH / xgTotal * 100).toFixed(1) + "%";
  $("xg-bar-away").style.width = (xgA / xgTotal * 100).toFixed(1) + "%";

  // Team Stats bars
  if (ts.home_attack) {
    const maxVal = 3.5; // max goals/game scale
    $("stat-home-label").textContent = data.home || "Home";
    $("stat-away-label").textContent = data.away || "Away";
    $("stat-h-atk").style.width = Math.min((ts.home_attack / maxVal) * 100, 100) + "%";
    $("stat-h-def").style.width = Math.min((ts.home_defense / maxVal) * 100, 100) + "%";
    $("stat-a-atk").style.width = Math.min((ts.away_attack / maxVal) * 100, 100) + "%";
    $("stat-a-def").style.width = Math.min((ts.away_defense / maxVal) * 100, 100) + "%";
    $("stats-wrap").classList.remove("hidden");
  }

  // AI Reasoning
  if (reas) {
    $("reasoning-text").textContent = reas;
    $("reasoning-card").classList.remove("hidden");
  }

  // ── All 14 Markets ────────────────────────────────────────────────────────
  renderCard1x2(m["1x2_ft"], "pick-1x2-ft", "conf-1x2-ft", "seg-1x2-1", "seg-1x2-x", "seg-1x2-2");

  if (m["boosted"]) {
    $("pick-boosted").textContent = m["boosted"].prediction || "--";
    $("conf-boosted").textContent = m["boosted"].confidence || "--";
  }

  if (m["double_chance"]) {
    const dc = m["double_chance"];
    $("pick-dc").textContent = dc.prediction || "--";
    $("conf-dc").textContent = dc.confidence || "--";
    renderOptions("opts-dc", dc.options, dc.prediction);
  }

  if (m["btts"]) {
    const btts = m["btts"];
    const pickEl = $("pick-btts");
    pickEl.className = "pick-badge " + (btts.prediction || "");
    pickEl.textContent = btts.prediction || "--";
    $("conf-btts").textContent = btts.confidence || "--";
    const yesPct = (btts.options && btts.options["YES"]) || 50;
    $("bar-btts").innerHTML = `
      <div class="mini-seg-yes" style="width:${yesPct}%"></div>
      <div class="mini-seg-no"  style="width:${100 - yesPct}%"></div>`;
  }

  renderOU($("pick-ou-ft"), $("conf-ou-ft"), $("lines-ou-ft"), m["ou_ft"]);

  if (m["ou_home"]) {
    $("label-ou-home").textContent = m["ou_home"].label || "Home O/U | FT";
    renderOU($("pick-ou-home"), $("conf-ou-home"), $("lines-ou-home"), m["ou_home"]);
  }
  if (m["ou_away"]) {
    $("label-ou-away").textContent = m["ou_away"].label || "Away O/U | FT";
    renderOU($("pick-ou-away"), $("conf-ou-away"), $("lines-ou-away"), m["ou_away"]);
  }

  renderCard1x2(m["1x2_h1"], "pick-1x2-h1", "conf-1x2-h1", "seg-h1-1", "seg-h1-x", "seg-h1-2");
  renderCard1x2(m["1x2_h2"], "pick-1x2-h2", "conf-1x2-h2", "seg-h2-1", "seg-h2-x", "seg-h2-2");
  renderOU($("pick-ou-h1"), $("conf-ou-h1"), $("lines-ou-h1"), m["ou_h1"]);
  renderOU($("pick-ou-h2"), $("conf-ou-h2"), $("lines-ou-h2"), m["ou_h2"]);

  if (m["next_goal"]) {
    const ng = m["next_goal"];
    $("pick-ng").textContent = ng.prediction || "--";
    $("conf-ng").textContent = ng.confidence || "--";
    renderOptions("opts-ng", ng.options, ng.prediction);
  }
  if (m["ht_ft"]) {
    const htft = m["ht_ft"];
    $("pick-htft").textContent = htft.prediction || "--";
    $("conf-htft").textContent = htft.confidence || "--";
    renderHTFT("opts-htft", htft.options, htft.prediction);
  }
  if (m["handicap"]) {
    const hcp = m["handicap"];
    $("pick-hcp").textContent = hcp.prediction || "--";
    $("conf-hcp").textContent = hcp.confidence || "--";
    renderOptions("opts-hcp", hcp.options, hcp.prediction);
  }

  renderScores(data.correct_scores || []);
}

/* ─── Helper Renderers ──────────────────────────────────── */
function renderCard1x2(market, pickId, confId, seg1Id, segXId, seg2Id) {
  if (!market) return;
  $(pickId).textContent = market.prediction || "--";
  $(confId).textContent = market.confidence || "--";
  const opts = market.options || {};
  const p1 = opts["1"] || 33, pX = opts["X"] || 34, p2 = opts["2"] || 33;
  const s1 = $(seg1Id), sX = $(segXId), s2 = $(seg2Id);
  if (s1) { s1.style.width = p1 + "%"; s1.querySelector("small").textContent = p1 + "%"; }
  if (sX) { sX.style.width = pX + "%"; sX.querySelector("small").textContent = pX + "%"; }
  if (s2) { s2.style.width = p2 + "%"; s2.querySelector("small").textContent = p2 + "%"; }
}

function renderOU(pickEl, confEl, linesEl, market) {
  if (!market || !pickEl) return;
  pickEl.textContent = market.prediction || "--";
  if (confEl) confEl.textContent = market.confidence || "--";
  if (!linesEl) return;
  linesEl.innerHTML = (market.all_thresholds || []).map(l =>
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
  const ranks = ["🥇", "🥈", "🥉", "4th", "5th", "6th"];
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
