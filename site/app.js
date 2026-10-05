/* Money Trail dashboard. Plain JS, no build step. Reads JSON from ./data/. */
(() => {
  "use strict";

  const cache = {};
  const load = (path, fallback = null) => {
    if (!cache[path]) {
      cache[path] = fetch(`data/${path}`, { cache: "no-cache" })
        .then(r => (r.ok ? r.json() : fallback))
        .catch(() => fallback);
    }
    return cache[path];
  };

  const $ = (sel, el = document) => el.querySelector(sel);
  const view = $("#view");
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = v => (v === null || v === undefined || Number.isNaN(v)) ? `<span class="muted">n/a</span>`
    : `<span class="${v > 0 ? "up" : v < 0 ? "down" : ""}">${v > 0 ? "+" : ""}${Number(v).toFixed(1)}%</span>`;
  const money = v => v == null ? "" : v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `$${Math.round(v / 1e3)}K` : `$${v}`;
  const tk = t => `<button class="tk" data-tk="${esc(t)}">${esc(t)}</button>`;
  const chip = (text, tone = "") => `<span class="chip ${tone}">${esc(text)}</span>`;
  const tkList = arr => (arr || []).filter(Boolean).map(tk).join(" ");
  const sources = list => (list && list.length)
    ? `<div class="src">Sources: ${list.map(s => `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title || s.url)}</a>`).join(" · ")}</div>` : "";

  function spark(values) {
    if (!values || values.length < 2) return "";
    const w = 300, h = 56, min = Math.min(...values), max = Math.max(...values), span = max - min || 1;
    const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - 4 - ((v - min) / span) * (h - 8)}`).join(" ");
    const up = values[values.length - 1] >= values[0];
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="Six month price trend">
      <polyline fill="none" stroke="var(${up ? "--up" : "--down"})" stroke-width="2" points="${pts}" vector-effect="non-scaling-stroke"/></svg>`;
  }

  /* Sortable table. cols: [{key, label, num, render(row)}] */
  function table(cols, rows, { sortKey = null, desc = true, empty = "Nothing here yet." } = {}) {
    const id = "t" + Math.random().toString(36).slice(2, 8);
    const state = { key: sortKey, desc };
    const draw = () => {
      const sorted = [...rows];
      if (state.key) {
        sorted.sort((a, b) => {
          const x = a[state.key], y = b[state.key];
          if (x == null) return 1; if (y == null) return -1;
          const r = typeof x === "number" ? x - y : String(x).localeCompare(String(y));
          return state.desc ? -r : r;
        });
      }
      return `<table><thead><tr>${cols.map(c => `<th data-k="${c.key}" class="${c.num ? "num" : ""}">${esc(c.label)}${state.key === c.key ? (state.desc ? " ↓" : " ↑") : ""}</th>`).join("")}</tr></thead>
        <tbody>${sorted.map(r => `<tr>${cols.map(c => `<td class="${c.num ? "num" : ""} ${c.wrap ? "wrap" : ""}">${c.render ? c.render(r) : esc(r[c.key])}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
    };
    setTimeout(() => {
      const wrap = document.getElementById(id);
      if (!wrap) return;
      wrap.addEventListener("click", e => {
        const th = e.target.closest("th");
        if (!th) return;
        const k = th.dataset.k;
        state.desc = state.key === k ? !state.desc : true;
        state.key = k;
        wrap.innerHTML = draw();
      });
    });
    if (!rows.length) return `<div class="empty">${esc(empty)}</div>`;
    return `<div class="table-wrap" id="${id}">${draw()}</div>`;
  }

  /* ---------- Today ---------- */
  async function renderToday(date) {
    const meta = await load("meta.json", { briefs: [] });
    const dates = meta.briefs || [];
    if (!dates.length) { view.innerHTML = `<div class="empty">No brief yet. The first one arrives at 6am Pacific.</div>`; return; }
    const d = date && dates.includes(date) ? date : dates[0];
    const b = await load(`briefs/${d}.json`, null);
    if (!b) { view.innerHTML = `<div class="empty">Could not load the brief for ${esc(d)}.</div>`; return; }
    const cats = [...new Set(b.signals.map(s => s.category))];
    const stanceTone = { "risk on": "up", "risk off": "down" }[b.regime?.stance] || "warn";

    view.innerHTML = `
      ${(meta.errors || []).length ? `<div class="note"><b>Data problems on the last refresh:</b> ${meta.errors.map(esc).join(" · ")}</div>` : ""}
      <div class="section-head"><div><h2>Daily brief</h2><span class="muted small">${esc(d)}</span></div>
        <div class="filters">${dates.slice(0, 7).map(x => `<button data-date="${x}" class="${x === d ? "on" : ""}">${x.slice(5)}</button>`).join("")}</div></div>
      <div class="card hero">
        <div class="chips" style="margin-bottom:10px">${chip(`Market: ${b.regime?.stance || "n/a"}`, stanceTone)}</div>
        <div class="headline">${esc(b.headline)}</div>
        <p class="muted">${esc(b.summary)}</p>
        <p class="small muted">${esc(b.regime?.why || "")}</p>
        <div class="levels">${(b.regime?.levels || []).map(l => `
          <div class="level" title="${esc(l.as_of)}${l.note ? " · " + esc(l.note) : ""}"><div class="n">${esc(l.name)}</div><div class="v">${esc(l.value)}</div>
          <div class="c ${String(l.change_1w).trim().startsWith("-") ? "down" : String(l.change_1w).trim().startsWith("+") ? "up" : "muted"}">${esc(l.change_1w)}</div></div>`).join("")}</div>
      </div>

      <div class="section-head"><h2>What it means for you</h2></div>
      <div class="grid g3">
        <div class="card"><h4>Swing trades</h4><p>${esc(b.actions?.swing)}</p></div>
        <div class="card"><h4>Puts and covered calls</h4><p>${esc(b.actions?.options)}</p></div>
        <div class="card"><h4>Long term</h4><p>${esc(b.actions?.long_term)}</p></div>
      </div>

      <div class="section-head"><h2>Signals and second order effects</h2>
        <div class="filters" id="cat-filter"><button class="on" data-cat="">All</button>${cats.map(c => `<button data-cat="${esc(c)}">${esc(c)}</button>`).join("")}</div></div>
      <div class="grid g2" id="signals">${b.signals.map(s => `
        <article class="card signal" data-cat="${esc(s.category)}">
          <div class="chips cat">${chip(s.category, "accent")} ${chip(`Confidence: ${s.confidence}`, s.confidence === "high" ? "up" : s.confidence === "low" ? "down" : "warn")} ${chip(s.timeframe)}</div>
          <h3>${esc(s.title)}</h3>
          <p class="muted small">${esc(s.what_happened)}</p>
          <div class="sowhat">${esc(s.so_what)}</div>
          <div class="who"><span class="muted">Benefits</span><span>${tkList(s.beneficiaries) || "<span class='muted'>none named</span>"}</span>
          <span class="muted">Hurt</span><span>${tkList(s.hurt) || "<span class='muted'>none named</span>"}</span></div>
          ${sources(s.sources)}
        </article>`).join("")}</div>

      <div class="grid g2" style="margin-top:28px">
        <div><div class="section-head"><h2>Smart money notes</h2></div>
          <div class="card stack">${(b.smart_money || []).map(m => `
            <div><b>${esc(m.who)}</b> <span class="muted small">${esc(m.when)}</span><p style="margin:2px 0">${esc(m.what)}</p>
            <p class="small muted">${esc(m.why_it_matters)}</p>${m.source ? sources([m.source]) : ""}</div>`).join("") || "<p class='muted'>None today.</p>"}</div></div>
        <div><div class="section-head"><h2>Calendar</h2></div>
          <div class="card cal">${(b.calendar || []).map(c => `<div class="d">${esc(c.date)}</div><div><b>${esc(c.event)}</b><div class="small muted">${esc(c.why_it_matters)}</div></div>`).join("")}</div></div>
      </div>`;

    view.querySelectorAll("[data-date]").forEach(btn => btn.onclick = () => { location.hash = `#/today/${btn.dataset.date}`; });
    $("#cat-filter").onclick = e => {
      const btn = e.target.closest("button"); if (!btn) return;
      $("#cat-filter").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === btn));
      view.querySelectorAll("#signals .signal").forEach(card => { card.style.display = !btn.dataset.cat || card.dataset.cat === btn.dataset.cat ? "" : "none"; });
    };
  }

  /* ---------- Themes ---------- */
  async function renderThemes() {
    const themes = await load("themes.json", []);
    view.innerHTML = `
      <div class="section-head"><div><h2>Themes</h2><p class="muted">Follow the money: who is spending big, where it flows, and who sits at the chokepoints. Click a theme to see its supply chain.</p></div></div>
      <div class="grid g3">${themes.map(t => `
        <article class="card theme-card" data-theme="${esc(t.id)}" tabindex="0">
          <div class="chips">${t.verified === false ? chip("Not yet verified", "down") : ""}${t.emerging ? chip("Emerging", "warn") : ""}${chip(`${t.layers} layers`)}${chip(`${t.companies} companies`)}${t.chokepoints ? chip(`${t.chokepoints} chokepoints`, "warn") : ""}</div>
          <h3>${esc(t.name)}</h3>
          <p class="small muted">${esc(t.thesis)}</p>
          <div class="stats"><span>Uptrend <b>${t.pct_uptrend ?? "n/a"}${t.pct_uptrend != null ? "%" : ""}</b></span><span>Median 3 month ${pct(t.median_3m)}</span><span>Updated <b>${esc(t.updated)}</b></span></div>
        </article>`).join("")}</div>`;
    view.querySelectorAll("[data-theme]").forEach(c => {
      const go = () => { location.hash = `#/theme/${c.dataset.theme}`; };
      c.onclick = go; c.onkeydown = e => { if (e.key === "Enter") go(); };
    });
  }

  async function renderTheme(id) {
    const [th, market, insiders, congress] = await Promise.all([
      load(`themes/${id}.json`, null), load("market.json", {}), load("insiders.json", { by_ticker: [] }), load("congress.json", { by_ticker: [] }),
    ]);
    if (!th) { view.innerHTML = `<div class="empty">Theme not found.</div>`; return; }
    const ins = new Set((insiders.by_ticker || []).map(r => r.ticker));
    const con = new Set((congress.by_ticker || []).filter(r => r.net_buyers > 0 || r.leaders?.length).map(r => r.ticker));

    const tile = c => {
      const t = (c.ticker || "").toUpperCase(), m = market[t];
      if (!t) return `<div class="co" style="cursor:default"><div class="row1"><b class="small">${esc(c.name)}</b>${chip("Private")}</div>
        <div class="role">${esc(c.role)}</div><div class="flags">${c.chokepoint ? chip("Chokepoint", "warn") : ""}</div></div>`;
      return `<button class="co ${c.chokepoint ? "choke" : ""}" data-tk="${esc(t)}">
        <div class="row1"><span class="mono"><span class="dot ${m ? m.trend : ""}"></span> <b>${esc(t)}</b></span>${m ? pct(m.chg_3m) : `<span class="small muted">${c.us_tradable === false ? "foreign" : ""}</span>`}</div>
        <div class="name">${esc(c.name)}${c.listing ? ` <span class="muted">· ${esc(c.listing)}</span>` : ""}</div><div class="role">${esc(c.role)}</div>
        <div class="flags">${c.buyout ? chip("Buyout pending", "down") : ""}${c.chokepoint ? chip("Chokepoint", "warn") : ""}${c.exposure ? chip(c.exposure) : ""}${ins.has(t) ? chip("Insider buy", "up") : ""}${con.has(t) ? chip("Congress buy", "up") : ""}${m?.breakout_setup ? chip("Setup", "accent") : ""}</div>
      </button>`;
    };

    view.innerHTML = `
      <a href="#/themes" class="back">← All themes</a>
      <div class="card hero">
        <div class="chips" style="margin-bottom:8px">${th.verified === false ? chip("Not yet verified: numbers from older data, check before acting", "down") : ""}${th.emerging ? chip("Emerging", "warn") : ""}${chip(`Updated ${th.updated}`)}</div>
        <h2>${esc(th.name)}</h2>
        <p style="margin-top:8px">${esc(th.thesis)}</p>
        ${th.money_source ? `<p class="small"><b>Where the money comes from:</b> ${esc(th.money_source)}</p>` : ""}
        ${th.anchor ? `<h4 style="margin-top:14px">Anchor: ${tk(th.anchor.ticker)}</h4><ul class="small">${(th.anchor.facts || []).map(f => `<li>${esc(f)}</li>`).join("")}</ul>` : ""}
      </div>

      ${(th.pipeline || []).length ? `<div class="section-head"><h2>What's coming</h2></div>
      <div class="card timeline">${th.pipeline.map(p => `<div class="t">${esc(p.timing)}</div><div><b>${esc(p.product)}</b><div class="small muted">${esc(p.what_changes_for_suppliers)}</div></div>`).join("")}</div>` : ""}

      <div class="section-head"><h2>The chain</h2>
        <div class="legend"><span><span class="dot uptrend"></span> uptrend</span><span><span class="dot mixed"></span> mixed</span><span><span class="dot downtrend"></span> downtrend</span><span>${chip("Chokepoint", "warn")} sole or dominant supplier</span><span>% = 3 month change</span></div></div>
      <div class="card chain">${th.layers.map(l => `
        <div class="layer">
          <div><div class="lname">${esc(l.name)}</div><div class="why">${esc(l.why)}</div>
            <div class="bneck">${chip(`Bottleneck: ${l.bottleneck}`, l.bottleneck === "high" ? "down" : l.bottleneck === "medium" ? "warn" : "")}</div>
            <div class="small muted" style="margin-top:4px">${esc(l.bottleneck_reason || "")}</div></div>
          <div class="cos">${(l.companies || []).map(tile).join("")}</div>
        </div>`).join("")}</div>

      <div class="grid g2" style="margin-top:28px">
        <div><div class="section-head"><h2>Second order ideas</h2></div><div class="card stack">${(th.second_order || []).map(s => `
          <div><b>${esc(s.idea)}</b><div style="margin:4px 0">${tkList(s.tickers)}</div><p class="small muted">${esc(s.why)}</p></div>`).join("")}</div></div>
        <div><div class="section-head"><h2>Risks</h2></div><div class="card stack">${(th.risks || []).map(r => `
          <div><b>${esc(r.risk)}</b><div style="margin:4px 0">${tkList(r.who_gets_hurt)}</div><p class="small muted">Watch for: ${esc(r.signal)}</p></div>`).join("")}</div></div>
      </div>
      <div class="section-head"><h2>Leading indicators</h2></div>
      ${table([{ key: "name", label: "Indicator" }, { key: "why", label: "Why it matters", wrap: true }, { key: "cadence", label: "How often" }], th.indicators || [])}
      ${sources(th.sources)}`;
  }

  /* ---------- Lineup ---------- */
  async function renderLineup() {
    const [rows, market, themes] = await Promise.all([load("lineup.json", []), load("market.json", {}), load("themes.json", [])]);
    const max = Math.max(1, ...rows.map(r => r.score));
    const enrich = rows.map(r => ({ ...r, chg_3m: market[r.ticker]?.chg_3m ?? null, from_high: market[r.ticker]?.from_52w_high ?? null, trend: market[r.ticker]?.trend || "" }));
    const draw = theme => {
      const list = enrich.filter(r => !theme || r.themes.includes(theme)).slice(0, 60);
      $("#lineup-table").innerHTML = table([
        { key: "score", label: "Score", num: true, render: r => `<div style="display:flex;gap:8px;align-items:center;justify-content:flex-end"><div class="bar"><span style="width:${Math.max(0, r.score) / max * 100}%"></span></div><span class="mono">${r.score}</span></div>` },
        { key: "ticker", label: "Ticker", render: r => tk(r.ticker) },
        { key: "name", label: "Company", render: r => `<span class="small">${esc(r.name)}</span>` },
        { key: "reasons", label: "Why it lines up", wrap: true, render: r => `<div class="reasons">${r.reasons.map(x => chip(x.text, x.tone)).join("")}</div>` },
        { key: "chg_3m", label: "3 mo", num: true, render: r => pct(r.chg_3m) },
        { key: "from_high", label: "From 52w high", num: true, render: r => pct(r.from_high) },
        { key: "themes", label: "Themes", wrap: true, render: r => `<span class="small muted">${esc(r.themes.join(", "))}</span>` },
      ], list, { sortKey: "score" });
    };
    view.innerHTML = `
      <div class="section-head"><div><h2>Lineup</h2>
        <p class="muted">Where the story, the smart money and the chart agree. Every stock in every theme gets points for being a chokepoint or pure play, insider buying, Congress leader buying, and a healthy trend or breakout setup. Downtrends lose points. High score means look closer, not buy.</p></div></div>
      <div class="filters" id="lineup-filter"><button class="on" data-theme="">All themes</button>${themes.map(t => `<button data-theme="${esc(t.name)}">${esc(t.name)}</button>`).join("")}</div>
      <div id="lineup-table"></div>`;
    draw("");
    $("#lineup-filter").onclick = e => {
      const btn = e.target.closest("button"); if (!btn) return;
      $("#lineup-filter").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === btn));
      draw(btn.dataset.theme);
    };
  }

  /* ---------- Smart money ---------- */
  async function renderSmart() {
    const [insiders, congress] = await Promise.all([load("insiders.json", { by_ticker: [] }), load("congress.json", { by_ticker: [], trades: [], sources: [] })]);
    const ins = insiders.by_ticker || [];
    const conBy = congress.by_ticker || [];
    const trades = (congress.trades || []).slice(0, 150);
    view.innerHTML = `
      <div class="section-head"><div><h2>Insider buying</h2>
        <p class="muted">Executives and directors buying their own stock with their own cash in the last 30 days, $50K or more. Clusters (2 or more insiders) and CEO or CFO buys carry the most weight. This has the strongest research behind it of anything on this page.</p></div>
        <span class="small muted">As of ${esc(insiders.as_of || "n/a")}</span></div>
      <div class="filters" id="ins-filter"><button class="on" data-f="all">All</button><button data-f="cluster">Clusters only</button><button data-f="theme">In my themes</button></div>
      <div id="ins-table"></div>

      <div class="section-head"><div><h2>Congress</h2>
        <p class="muted">Disclosed trades filed in the last 60 days. Members can report up to 45 days late, so check the lag column. Copying Congress as a whole has shown no reliable edge. Party leaders are the exception, so they are flagged. Use this as a clue about where policy is heading, not as a buy signal.</p></div>
        <span class="small muted">Source: ${esc((congress.sources || []).join(", ") || "none worked on the last run")}</span></div>
      ${table([
        { key: "ticker", label: "Ticker", render: r => tk(r.ticker) },
        { key: "net_buyers", label: "Net buyers", num: true },
        { key: "buyers", label: "Bought", wrap: true, render: r => `<span class="small">${esc(r.buyers.join(", "))}</span>` },
        { key: "sellers", label: "Sold", wrap: true, render: r => `<span class="small muted">${esc(r.sellers.join(", "))}</span>` },
        { key: "leaders", label: "Leader", wrap: true, render: r => r.leaders.length ? chip(r.leaders.join(", "), "warn") : "" },
        { key: "buy_amount_min", label: "Bought at least", num: true, render: r => money(r.buy_amount_min) },
        { key: "themes", label: "Themes", wrap: true, render: r => `<span class="small muted">${esc((r.themes || []).join(", "))}</span>` },
      ], conBy, { sortKey: "net_buyers", empty: "No Congress data on the last run." })}
      <div class="section-head"><h3>Recent filings</h3></div>
      ${table([
        { key: "filed", label: "Filed" }, { key: "traded", label: "Traded" },
        { key: "lag_days", label: "Lag (days)", num: true },
        { key: "person", label: "Member", render: r => `${esc(r.person)} ${r.leader ? chip(r.leader, "warn") : ""}` },
        { key: "chamber", label: "Chamber" },
        { key: "type", label: "Type", render: r => chip(r.type, r.type === "buy" ? "up" : r.type === "sell" ? "down" : "") },
        { key: "ticker", label: "Ticker", render: r => tk(r.ticker) },
        { key: "amount", label: "Amount" },
      ], trades, { sortKey: "filed", empty: "No filings on the last run." })}`;

    const drawIns = f => {
      const list = ins.filter(r => f === "all" || (f === "cluster" && r.cluster) || (f === "theme" && r.themes?.length));
      $("#ins-table").innerHTML = table([
        { key: "score", label: "Score", num: true },
        { key: "ticker", label: "Ticker", render: r => tk(r.ticker) },
        { key: "company", label: "Company", render: r => `<span class="small">${esc(r.company)}</span>` },
        { key: "insiders", label: "Insiders", num: true, render: r => `${r.insiders} ${r.cluster ? chip("Cluster", "up") : ""}` },
        { key: "top_role", label: "Most senior" },
        { key: "total_value", label: "Total bought", num: true, render: r => money(r.total_value) },
        { key: "avg_price", label: "Avg price", num: true, render: r => r.avg_price ? `$${r.avg_price}` : "" },
        { key: "last_trade", label: "Last trade" },
        { key: "themes", label: "Themes", wrap: true, render: r => `<span class="small muted">${esc((r.themes || []).join(", "))}</span>` },
      ], list, { sortKey: "score", empty: "No insider data on the last run." });
    };
    drawIns("all");
    $("#ins-filter").onclick = e => {
      const btn = e.target.closest("button"); if (!btn) return;
      $("#ins-filter").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === btn));
      drawIns(btn.dataset.f);
    };
  }

  /* ---------- Setups ---------- */
  /* Account settings live only in this browser, never in the public repo. */
  const ACCT_KEY = "moneytrail.account";
  const getAcct = () => {
    try { return { size: 50000, risk: 1, maxPos: 20, ...JSON.parse(localStorage.getItem(ACCT_KEY) || "{}"), ...(renderSetups.override || {}) }; }
    catch { return { size: 50000, risk: 1, maxPos: 20 }; }
  };
  const sizeShares = (r, a) => {
    if (!r.risk_per_share || !r.entry) return 0;
    const byRisk = Math.floor((a.size * a.risk / 100) / r.risk_per_share);
    const byCap = Math.floor((a.size * a.maxPos / 100) / r.entry);
    return Math.max(0, Math.min(byRisk, byCap));
  };

  async function renderSetups() {
    const s = await load("setups.json", { swing: [], csp: [] });
    const a = getAcct();
    const themeCol = { key: "themes", label: "Themes", wrap: true, render: r => `<span class="small muted">${esc((r.themes || []).join(", "))}</span>` };
    const swing = (s.swing || []).map(r => { const sh = sizeShares(r, a); return { ...r, my_shares: sh, my_cost: Math.round(sh * r.entry), my_loss: Math.round(sh * r.risk_per_share) }; });
    const csp = (s.csp || []).map(r => ({ ...r, pct_of_acct: r.strike ? Math.round(1000 * r.strike * 100 / a.size) / 10 : null }));
    view.innerHTML = `
      <div class="card" style="margin-bottom:20px">
        <h4>Your account (saved only in this browser, never uploaded)</h4>
        <form id="acct" class="filters" style="align-items:center;margin:0">
          <label class="small">Account size $ <input name="size" type="number" min="1000" step="1000" value="${a.size}" class="acct-in"></label>
          <label class="small">Risk per trade % <input name="risk" type="number" min="0.1" max="5" step="0.1" value="${a.risk}" class="acct-in"></label>
          <label class="small">Max position % <input name="maxPos" type="number" min="1" max="100" step="1" value="${a.maxPos}" class="acct-in"></label>
          <button type="submit" class="on">Update sizes</button>
        </form>
      </div>
      <div class="section-head"><div><h2>Swing breakouts</h2>
        <p class="muted">Above a rising 50 and 200 day, tight base near the high, volume drying up, beating SPY, earnings at least 2 weeks away. Entry is a buy stop over the pivot. Shares are sized so a stop out loses ${a.risk}% of your account.</p></div>
        <span class="small muted">Prices as of ${esc(s.as_of || "n/a")}</span></div>
      ${table([
        { key: "ticker", label: "Ticker", render: r => tk(r.ticker) }, { key: "score", label: "Score", num: true },
        { key: "price", label: "Price", num: true }, { key: "entry", label: "Entry", num: true }, { key: "stop", label: "Stop", num: true },
        { key: "risk_pct", label: "Risk %", num: true }, { key: "target_2r", label: "Target 2R", num: true }, { key: "target_3r", label: "Target 3R", num: true },
        { key: "my_shares", label: "Shares", num: true }, { key: "my_cost", label: "Cost", num: true, render: r => money(r.my_cost) },
        { key: "my_loss", label: "Loss if stopped", num: true, render: r => money(r.my_loss) },
        { key: "vs_spy_3mo_pct", label: "vs SPY 3mo", num: true, render: r => pct(r.vs_spy_3mo_pct) },
        { key: "earnings", label: "Earnings" }, themeCol,
      ], swing, { sortKey: "score", empty: "No breakouts passed every rule. Sitting in cash is a position." })}

      <div class="section-head"><div><h2>Cash secured puts</h2>
        <p class="muted">Strike at or below real support, 25 to 50 days out, no earnings before expiration. IV/HV above 1 means option premium is rich compared with how much the stock actually moves. Keep any one put under about 10% of your account.</p></div></div>
      ${table([
        { key: "ticker", label: "Ticker", render: r => tk(r.ticker) }, { key: "price", label: "Price", num: true },
        { key: "support", label: "Support", num: true }, { key: "expiration", label: "Expiry" }, { key: "strike", label: "Strike", num: true },
        { key: "premium", label: "Premium", num: true }, { key: "annualized_pct", label: "Annualized %", num: true },
        { key: "breakeven", label: "Breakeven", num: true }, { key: "cushion_pct", label: "Cushion %", num: true },
        { key: "pct_of_acct", label: "% of acct per contract", num: true, render: r => r.pct_of_acct == null ? "" : `<span class="${r.pct_of_acct > 10 ? "down" : ""}">${r.pct_of_acct}%</span>` },
        { key: "iv_to_hv", label: "IV/HV", num: true }, { key: "earnings", label: "Earnings" }, themeCol,
      ], csp, { sortKey: "annualized_pct", empty: "No puts passed every rule on the last run." })}`;
    $("#acct").onsubmit = e => {
      e.preventDefault();
      const f = new FormData(e.target);
      const next = { size: +f.get("size") || 50000, risk: +f.get("risk") || 1, maxPos: +f.get("maxPos") || 20 };
      try { localStorage.setItem(ACCT_KEY, JSON.stringify(next)); } catch { /* private window: sizes still update for this view */ }
      Object.assign(a, next);
      renderSetups.override = next;
      renderSetups();
    };
  }

  /* ---------- Ticker drawer ---------- */
  async function openTicker(t) {
    t = t.toUpperCase().trim();
    const [market, idx, insiders, congress, lineup, setups] = await Promise.all([
      load("market.json", {}), load("tickers.json", {}), load("insiders.json", { by_ticker: [] }),
      load("congress.json", { by_ticker: [], trades: [] }), load("lineup.json", []), load("setups.json", { swing: [], csp: [] }),
    ]);
    const m = market[t], places = idx[t] || [], ins = (insiders.by_ticker || []).find(r => r.ticker === t);
    const conTrades = (congress.trades || []).filter(r => r.ticker === t);
    const lu = lineup.find(r => r.ticker === t);
    const sw = (setups.swing || []).find(r => r.ticker === t), csp = (setups.csp || []).find(r => r.ticker === t);
    const name = places[0]?.name || ins?.company || "";

    $("#drawer-body").innerHTML = `
      <h2 class="mono">${esc(t)}</h2><p class="muted">${esc(name)}</p>
      ${lu ? `<div class="reasons" style="margin:8px 0">${chip(`Lineup score ${lu.score}`, "accent")}${lu.reasons.map(x => chip(x.text, x.tone)).join("")}</div>` : ""}
      ${m ? `${spark(m.spark)}
        <div class="kv">
          <div><div class="k">Price</div><div class="v">$${m.price}</div></div>
          <div><div class="k">1 day</div><div class="v">${pct(m.chg_1d)}</div></div>
          <div><div class="k">1 month</div><div class="v">${pct(m.chg_1m)}</div></div>
          <div><div class="k">3 months</div><div class="v">${pct(m.chg_3m)}</div></div>
          <div><div class="k">1 year</div><div class="v">${pct(m.chg_1y)}</div></div>
          <div><div class="k">From 52w high</div><div class="v">${pct(m.from_52w_high)}</div></div>
          <div><div class="k">vs SPY 3mo</div><div class="v">${pct(m.vs_spy_3m)}</div></div>
          <div><div class="k">Trend</div><div class="v">${esc(m.trend)}</div></div>
          <div><div class="k">20d volatility</div><div class="v">${m.hv20 ?? "n/a"}%</div></div>
        </div>` : `<p class="small muted">No price data for this ticker on the last run.</p>`}
      ${sw ? `<h4>Swing setup</h4><p class="small">Buy stop ${sw.entry}, stop ${sw.stop} (${sw.risk_pct}% risk), targets ${sw.target_2r} / ${sw.target_3r}, ${sizeShares(sw, getAcct())} shares for your account.</p>` : ""}
      ${csp ? `<h4>Put idea</h4><p class="small">Sell the ${csp.expiration} ${csp.strike} put for about $${csp.premium} (${csp.annualized_pct}% annualized, breakeven ${csp.breakeven}).</p>` : ""}
      ${places.length ? `<h4 style="margin-top:16px">Where it sits in the themes</h4>${places.map(p => `
        <div style="margin-bottom:10px"><a href="#/theme/${esc(p.theme)}">${esc(p.theme_name)}</a> <span class="muted small">· ${esc(p.layer)}</span>
        <div class="small">${esc(p.role)}</div><div class="chips" style="margin-top:4px">${p.chokepoint ? chip("Chokepoint", "warn") : ""}${p.exposure ? chip(p.exposure) : ""}</div></div>`).join("")}` : ""}
      ${ins ? `<h4 style="margin-top:16px">Insider buying, last 30 days</h4>
        ${table([{ key: "traded", label: "Date" }, { key: "insider", label: "Who" }, { key: "title", label: "Title" }, { key: "price", label: "Price", num: true }, { key: "value", label: "Value", num: true, render: r => money(r.value) }], ins.trades || [])}` : ""}
      ${conTrades.length ? `<h4 style="margin-top:16px">Congress</h4>
        ${table([{ key: "traded", label: "Traded" }, { key: "person", label: "Member", render: r => `${esc(r.person)} ${r.leader ? chip("Leader", "warn") : ""}` }, { key: "type", label: "Type" }, { key: "amount", label: "Amount" }, { key: "lag_days", label: "Lag", num: true }], conTrades)}` : ""}
      <h4 style="margin-top:16px">Look deeper</h4>
      <div class="links">
        <a href="https://finance.yahoo.com/quote/${encodeURIComponent(t)}" target="_blank" rel="noopener">Yahoo Finance</a>
        <a href="https://finviz.com/quote.ashx?t=${encodeURIComponent(t)}" target="_blank" rel="noopener">Finviz chart</a>
        <a href="http://openinsider.com/${encodeURIComponent(t)}" target="_blank" rel="noopener">All insider trades</a>
        <a href="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&ticker=${encodeURIComponent(t)}&type=&dateb=&owner=include&count=40" target="_blank" rel="noopener">SEC filings</a>
      </div>`;
    $("#drawer").classList.add("open"); $("#drawer").setAttribute("aria-hidden", "false"); $("#scrim").classList.add("open");
  }
  const closeDrawer = () => { $("#drawer").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true"); $("#scrim").classList.remove("open"); };

  /* ---------- Router ---------- */
  async function route() {
    const [, tab = "today", arg] = location.hash.split("/");
    const active = tab === "theme" ? "themes" : tab;
    document.querySelectorAll(".tabs a").forEach(a => a.classList.toggle("active", a.dataset.tab === active));
    view.innerHTML = `<div class="empty">Loading…</div>`;
    const pages = { today: () => renderToday(arg), themes: renderThemes, theme: () => renderTheme(arg), lineup: renderLineup, smart: renderSmart, setups: renderSetups };
    await (pages[tab] || pages.today)();
    const names = { today: "Daily brief", themes: "Themes", theme: "Theme", lineup: "Lineup", smart: "Smart money", setups: "Setups" };
    const title = tab === "theme" ? ($("#view h2")?.textContent || "Theme") : (names[tab] || "Daily brief");
    currentPage = { tab: tab in pages ? tab : "today", title, arg };
    $("#page-title").textContent = `${title} · ${new Date().toLocaleDateString([], { dateStyle: "medium" })}`;
    window.scrollTo(0, 0);
  }

  /* ---------- PDF of the current page ---------- */
  let currentPage = { tab: "today", title: "Daily brief" };
  async function downloadPdf() {
    const btn = $("#pdf-btn");
    const day = new Date().toISOString().slice(0, 10);
    const slug = (currentPage.tab === "theme" ? `theme-${currentPage.arg}` : currentPage.tab === "today" && currentPage.arg ? `brief-${currentPage.arg}` : currentPage.tab);
    const filename = `money-trail-${slug}-${day}.pdf`;

    // Build a print copy: page header, the page itself, and the disclaimer. Always light, never cut off.
    const wrap = document.createElement("div");
    wrap.className = "pdf-doc";
    wrap.innerHTML = `<div class="pdf-head"><b>Money Trail</b> · ${esc(currentPage.title)} · ${esc(day)}<br>
      <span>${esc(location.href)}</span></div>`;
    const copy = view.cloneNode(true);
    copy.removeAttribute("id");
    copy.querySelectorAll(".filters, .acct-in, #acct button").forEach(el => el.remove());
    copy.querySelectorAll(".table-wrap").forEach(el => { el.style.overflow = "visible"; });
    wrap.appendChild(copy);
    wrap.appendChild($(".disclaimer").cloneNode(true));

    if (!window.html2pdf) { window.print(); return; }
    // Letter paper minus margins: about 740px wide in portrait, 990px in landscape.
    const landscape = ["smart", "setups", "lineup"].includes(currentPage.tab);
    const width = landscape ? 990 : 740;
    wrap.style.width = `${width}px`;
    const root = document.documentElement, prevTheme = root.getAttribute("data-theme");
    root.setAttribute("data-theme", "light");
    const scrollPos = window.scrollY;
    window.scrollTo(0, 0);
    btn.disabled = true; btn.textContent = "Making PDF…";
    try {
      await window.html2pdf().set({
        margin: [8, 8, 10, 8],
        filename,
        image: { type: "jpeg", quality: 0.85 },
        html2canvas: { scale: 1.6, useCORS: true, windowWidth: document.documentElement.clientWidth, scrollX: 0, scrollY: 0, backgroundColor: "#ffffff" },
        jsPDF: { unit: "mm", format: "letter", orientation: landscape ? "landscape" : "portrait" },
        pagebreak: { mode: ["css", "legacy"], avoid: ["tr", ".signal", ".layer", ".theme-card", ".level"] },
      }).from(wrap).save();
    } catch (err) {
      window.print();
    } finally {
      window.scrollTo(0, scrollPos);
      prevTheme ? root.setAttribute("data-theme", prevTheme) : root.removeAttribute("data-theme");
      btn.disabled = false; btn.textContent = "Download PDF";
    }
  }
  $("#pdf-btn").onclick = downloadPdf;

  document.addEventListener("click", e => {
    const b = e.target.closest("[data-tk]");
    if (b) { e.preventDefault(); e.stopPropagation(); openTicker(b.dataset.tk); }
  });
  $("#drawer-close").onclick = closeDrawer;
  $("#scrim").onclick = closeDrawer;
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });
  $("#search").onsubmit = e => { e.preventDefault(); const v = $("#search-input").value.trim(); if (v) openTicker(v); };

  load("meta.json", {}).then(meta => {
    const when = meta?.generated ? new Date(meta.generated).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "never";
    $("#updated").textContent = `Updated ${when}`;
  });
  window.addEventListener("hashchange", route);
  route();
})();
