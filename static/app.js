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
  initMobileNav();
  $("retry-btn").addEventListener("click", loadMatches);
  $("last-updated").textContent = "Updated: " + new Date().toLocaleTimeString();
});

function initMobileNav() {
  const btn = $("mobile-nav-btn");
  const sidebar = $("sidebar");
  if (btn && sidebar) {
    btn.addEventListener("click", () => {
      sidebar.classList.toggle("open");
    });
  }
}

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
    if (data.scraped_at) {
      $("data-refresh").textContent =
        `Fixtures & odds: ${data.source || "BetPawa"} · fetched ${new Date(data.scraped_at).toLocaleString()} · ` +
        `results: football-data.co.uk + ESPN`;
    }
    fillLeagueFilter(allMatches);

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
      <div class="match-meta">${m.kickoff ? "🕒 " + esc(m.kickoff) + " · " : ""}⚽ ${esc(leagueName(m.league))}${m.odds ? " · " + m.odds.join(" / ") : ""}</div>
    `;
    item.dataset.league = m.league || "";
    item.addEventListener("click", () => selectMatch(m, item));
    list.appendChild(item);
  });
}

function leagueName(league) {
  return (league || "BetPawa TZ").replace(/^Football \/ /, "");
}

function fillLeagueFilter(matches) {
  const sel = $("league-filter");
  const leagues = [...new Set(matches.map(m => m.league).filter(Boolean))].sort();
  sel.innerHTML = `<option value="">All leagues (${matches.length})</option>` + leagues.map(l =>
    `<option value="${esc(l)}">${esc(leagueName(l))} (${matches.filter(m => m.league === l).length})</option>`
  ).join("");
}

/* ─── Search + league filter ─────────────────────────────── */
function applyFilters() {
  const q = $("match-search").value.toLowerCase();
  const lg = $("league-filter").value;
  document.querySelectorAll(".match-item").forEach(el => {
    const text = el.querySelector(".match-teams").textContent.toLowerCase();
    el.style.display = text.includes(q) && (!lg || el.dataset.league === lg) ? "" : "none";
  });
}

function initSearch() {
  $("match-search").addEventListener("input", applyFilters);
  $("league-filter").addEventListener("change", applyFilters);
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
  $("summary-panel").classList.add("hidden");
  $("prediction-error").classList.add("hidden");

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
      body: JSON.stringify({ home: match.home, away: match.away, league: match.league, odds: match.odds, kickoff: match.kickoff }),
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
  $("result-container").classList.add("hidden");
  const box = $("prediction-error");
  box.innerHTML = `<div style="font-size:40px;margin-bottom:12px;">⚠️</div><p>${esc(msg)}</p>`;
  box.classList.remove("hidden");
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
  $("p-confidence-badge").textContent = conf;
  $("p-confidence-badge").className   = "conf-badge " + conf;

  // Data source badge
  const src = ts.data_source || meta.data_source || "";
  if (src) {
    const srcEl = $("data-source-badge");
    const srcLabels = {
      "model+market": "📊 Results + Odds",
      market:         "💹 Odds Only",
      model:          "📊 Results Only",
      none:           "⚠️ No Data",
      known_db:       "📊 Real Stats",
      web_extracted:  "🌐 Web Stats",
      league_average: "📐 League Avg",
      nlp_fallback:   "🔍 NLP Only"
    };
    srcEl.textContent = srcLabels[src] || src;
    srcEl.className = "data-source-badge src-" + src.replace(/[^a-z]/g, "-");
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
  } else {
    $("stats-wrap").classList.add("hidden");      // no team ratings (odds-only or no data)
  }

  // Why / what could make it wrong
  const factors = data.factors || [];
  $("factors-list").innerHTML = factors.map(f => `<li>${esc(f)}</li>`).join("");
  $("reasoning-text").textContent = factors.length ? "" : reas;
  $("risks-list").innerHTML = (data.risks || []).map(r => `<li>${esc(r)}</li>`).join("");
  if (factors.length || reas) $("reasoning-card").classList.remove("hidden");

  renderSummary(data);
  renderValue(data);
  renderForm(data);
  renderSources(data);

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

/* ─── Summary: probabilities + separate confidence measures ─── */
function renderSummary(data) {
  const p = data.probabilities;
  if (!p) return;
  $("sum-home").textContent = p.home.toFixed(1) + "%";
  $("sum-draw").textContent = p.draw.toFixed(1) + "%";
  $("sum-away").textContent = p.away.toFixed(1) + "%";
  const dr = data.draw_risk ? ` · draw risk ${data.draw_risk.level}` : "";
  const hc = p.high_confidence
    ? `<span class="tag good">high-confidence pick</span>`
    : `<span class="tag">most likely, not a high-confidence pick</span>`;
  $("sum-most-likely").innerHTML =
    `Most likely: <b>${esc(p.most_likely)}</b> (historically wins ${p.most_likely_hit_rate}%) ${hc}${esc(dr)}`;
  const xg = data.expected_goals || {}, g = data.goals || {};
  $("sum-goals").textContent =
    `Expected goals ${xg.home} – ${xg.away} · BTTS ${g.btts_yes}% · Over 1.5 ${g.over_1_5}% · ` +
    `Over 2.5 ${g.over_2_5}% · Over 3.5 ${g.over_3_5}%`;

  const a = data.assessment || {}, crit = a.criteria || {};
  const badge = (label, obj, key) => obj ? `<div class="assess" title="${esc(crit[key] || "")}">
      <span class="assess-label">${label}</span>
      <span class="assess-val lvl-${esc(obj.level)}">${esc(obj.level)}</span>
      ${obj.reasons ? `<span class="assess-why">${esc(obj.reasons.join(" "))}</span>` : ""}
    </div>` : "";
  $("assess-badges").innerHTML =
    badge("Prediction strength", a.prediction_strength, "prediction_strength") +
    badge("Model confidence", a.model_confidence, "model_confidence") +
    badge("Data quality", a.data_quality, "data_quality");
  $("summary-panel").classList.remove("hidden");
}

/* ─── Model vs bookmaker, expected value ─────────────────── */
function renderValue(data) {
  const v = data.value, meta = data.analysis_meta || {};
  if (!v) {
    $("value-table").innerHTML = `<p class="muted">No valid odds for this match, so no comparison or value check.</p>`;
    $("value-note").textContent = "";
    return;
  }
  const mo = meta.model_1x2 || {};
  const keys = ["1", "X", "2"];
  const pctEv = x => x === null || x === undefined ? "–" : `${x > 0 ? "+" : ""}${x}%`;
  $("value-table").innerHTML = `<table class="data-table">
    <tr><th>Outcome</th><th>Odds</th><th>Implied</th><th>Fair (no margin) = published</th><th>Ratings model</th>
      <th>EV at published</th><th>EV at model</th></tr>
    ${v.outcomes.map(o => `<tr class="${o.flag ? "flag" : ""}">
      <td>${esc(o.outcome)}</td><td>${o.odds.toFixed(2)}</td><td>${o.implied}%</td><td>${o.probability}%</td>
      <td>${o.model_probability !== null && o.model_probability !== undefined ? o.model_probability + "%" : "–"}</td>
      <td class="neg">${pctEv(o.ev)}</td>
      <td class="${o.ev_model > 0 ? "pos" : "neg"}">${pctEv(o.ev_model)}${o.flag ? " ⚑" : ""}</td></tr>`).join("")}
  </table>`;
  $("value-note").textContent =
    `Bookmaker margin ${v.overround}%. ` +
    (v.threshold === null ? "Value flags are OFF. " : `⚑ = model EV ≥ ${v.threshold}%. `) +
    `${v.assumptions} ${v.history}`;
}

/* ─── Form, venue form, head-to-head ─────────────────────── */
function seq(s) {
  return (s || "").split("").map(c => `<span class="res res-${c}">${c}</span>`).join("");
}

function formRow(team, f) {
  if (!f) return `<tr><td>${esc(team)}</td><td colspan="6" class="muted">no matches</td></tr>`;
  const xg = f.xg_for !== undefined ? `${f.xg_for} / ${f.xg_against}` : "–";
  const opp = f.opponent_strength !== undefined ? (f.opponent_strength > 0 ? "+" : "") + f.opponent_strength : "–";
  return `<tr><td>${esc(team)}</td><td>${seq(f.sequence)}</td><td>${f.w}-${f.d}-${f.l}</td>
    <td>${f.gf}:${f.ga}</td><td>${f.ppg}</td><td>${xg}</td><td>${opp}</td></tr>`;
}

function renderForm(data) {
  const c = data.context;
  if (!c) {
    $("form-table").innerHTML = `<p class="muted">No results data for these teams (odds-only prediction).</p>`;
    $("venue-form").innerHTML = `<p class="muted">No results data.</p>`;
    $("h2h-list").innerHTML = `<p class="muted">No results data.</p>`;
    $("form-scope").textContent = "";
    return;
  }
  $("form-scope").textContent = "league matches only";
  const head = `<tr><th>Team</th><th>Results (newest first)</th><th>W-D-L</th><th>Goals</th><th>Pts/game</th>
    <th>xG for / against</th><th>Opponents vs league avg</th></tr>`;
  $("form-table").innerHTML = ["last5", "last10", "last15"].map(k => `
    <div class="sub-head">Last ${k.replace("last", "")} matches</div>
    <table class="data-table">${head}${formRow(data.home, c.home_form[k])}${formRow(data.away, c.away_form[k])}</table>`
  ).join("") + `<p class="fine-print">Rest: ${esc(data.home)} ${c.rest_days.home ?? "?"} days, ${esc(data.away)} ` +
    `${c.rest_days.away ?? "?"} days since their last league match. Data through ${esc(c.data_through)}.</p>`;

  const v = (label, f) => f ? `<div class="venue-line"><b>${esc(label)}</b>: ${seq(f.sequence)}
      ${f.w}W ${f.d}D ${f.l}L · goals ${f.gf}:${f.ga} · clean sheets ${f.clean_sheets} · failed to score ${f.failed_to_score}</div>`
    : `<div class="venue-line muted">${esc(label)}: no matches</div>`;
  $("venue-form").innerHTML = v(`${data.home} at home (last ${c.home_at_home ? c.home_at_home.matches : 0})`, c.home_at_home) +
    v(`${data.away} away (last ${c.away_away ? c.away_away.matches : 0})`, c.away_away);

  const h = c.h2h;
  $("h2h-list").innerHTML = h.meetings.length
    ? `<div class="venue-line">${esc(data.home)} ${h.home_wins} · draws ${h.draws} · ${esc(data.away)} ${h.away_wins}</div>` +
      h.meetings.map(m => `<div class="h2h-row">${esc(m.date)} &nbsp; ${esc(m.home)} <b>${esc(m.score)}</b> ${esc(m.away)}</div>`).join("") +
      `<p class="fine-print">Shown for context. Not used in the probabilities: recent form and ratings predict better.</p>`
    : `<p class="muted">No meetings in the last two seasons of data.</p>`;
}

/* ─── Sources ─────────────────────────────────────────────── */
function renderSources(data) {
  const src = (data.sources || []).map(s =>
    `${esc(s.name)}${s.data_through ? " (results through " + esc(s.data_through) + ")" : ""}`).join(" · ");
  $("sources-list").innerHTML =
    `${src || "No data sources for this match."}<br>` +
    `Prediction made ${esc(data.created_at || "?")} by model ${esc(data.model_version || "?")}. ` +
    `Injuries, suspensions and line-ups: not available in this system — check official team news.`;
}
