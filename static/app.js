const money = (n) =>
  (n ?? 0).toLocaleString("en-US", { style: "currency", currency: "USD" });

/** Whole dollars for overview metrics / charts */
const moneyRound = (n) =>
  Math.round(n ?? 0).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });

const pct = (n) => `${(n ?? 0).toFixed(1)}%`;

/** Short date like "Jun 5" from ISO YYYY-MM-DD */
function shortDate(iso) {
  if (!iso) return "";
  const d = new Date(`${iso}T12:00:00`);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** e.g. "Amex · Jun 2026 · Jun 5–Jul 7 · closed Jul 7" */
function periodDisplay(s, { showIssuer = false } = {}) {
  const issuer =
    showIssuer && (s.issuer_label || s.issuer)
      ? s.issuer_label || String(s.issuer).toUpperCase()
      : "";
  const label = s.period_label || "";
  const range =
    s.period_start && s.period_end
      ? `${shortDate(s.period_start)}–${shortDate(s.period_end)}`
      : "";
  const closed = s.closing_date ? `closed ${s.closing_date}` : "";
  return [issuer, label, range, closed].filter(Boolean).join(" · ");
}

let charts = {};
let state = {
  statementId: "ytd",
  cardholder: "all",
  tag: "all",
  issuer: "all",
};

function destroyCharts() {
  Object.values(charts).forEach((c) => c.destroy());
  charts = {};
}

function deltaEl(deltaObj, invertGood = true, vsLabel = "vs prior") {
  if (!deltaObj) return `<div class="delta flat">No prior statement to compare</div>`;
  const d = deltaObj.delta;
  const cls = d === 0 ? "flat" : d > 0 ? (invertGood ? "up" : "down") : invertGood ? "down" : "up";
  const arrow = d === 0 ? "→" : d > 0 ? "▲" : "▼";
  const label =
    d === 0
      ? `same ${vsLabel}`
      : `${arrow} ${moneyRound(Math.abs(d))} (${pct(Math.abs(deltaObj.pct))}) ${vsLabel}`;
  return `<div class="delta ${cls}">${label}</div>`;
}

function momChip(metric, invertGood = true) {
  if (!metric) return `<span class="mom-chip flat">—</span>`;
  const d = metric.delta;
  const cls = d === 0 ? "flat" : d > 0 ? (invertGood ? "up" : "down") : invertGood ? "down" : "up";
  const arrow = d === 0 ? "→" : d > 0 ? "▲" : "▼";
  if (d === 0) return `<span class="mom-chip flat">→ flat</span>`;
  return `<span class="mom-chip ${cls}">${arrow} ${money(Math.abs(d))} (${pct(Math.abs(metric.pct))})</span>`;
}

function setStatus(msg, isError = false) {
  const el = document.getElementById("uploadStatus");
  el.textContent = msg || "";
  el.classList.toggle("error", isError);
}

async function loadDashboard(statementId = null, cardholder = null, tag = null, issuer = null) {
  if (statementId !== null && statementId !== undefined) state.statementId = statementId;
  if (cardholder !== null) state.cardholder = cardholder;
  if (tag !== null) state.tag = tag;
  if (issuer !== null) state.issuer = issuer;

  const params = new URLSearchParams();
  if (state.statementId && state.statementId !== "ytd") {
    params.set("statement_id", state.statementId);
  }
  if (state.cardholder && state.cardholder !== "all") params.set("cardholder", state.cardholder);
  if (state.tag && state.tag !== "all") params.set("tag", state.tag);
  if (state.issuer && state.issuer !== "all") params.set("issuer", state.issuer);

  const qs = params.toString();
  const res = await fetch(qs ? `/api/dashboard?${qs}` : "/api/dashboard");
  const data = await res.json();
  render(data);
}

function populateIssuerSelect(issuers, selected) {
  const select = document.getElementById("issuerSelect");
  if (!select) return;
  const current = selected || state.issuer || "all";
  const list = issuers || [];
  const opts = [`<option value="all">All cards (clubbed)</option>`].concat(
    list.map((row) => {
      const id = row.id || row;
      const label = row.label || id;
      const n = row.statement_count;
      const suffix =
        typeof n === "number" ? ` (${n})` : row.can_parse === false ? " · soon" : "";
      return `<option value="${escapeHtml(id)}" ${id === current ? "selected" : ""}>${escapeHtml(
        label + suffix
      )}</option>`;
    })
  );
  select.innerHTML = opts.join("");
  select.value = current === "all" || list.some((r) => (r.id || r) === current) ? current : "all";
  if (select.value !== current) state.issuer = select.value;
}

function populateUploadIssuerSelect(issuers) {
  const select = document.getElementById("uploadIssuerSelect");
  if (!select) return;
  const rows = issuers || [];
  const current = select.value || "amex";
  select.innerHTML = rows
    .map((row) => {
      const pdf = row.can_parse_pdf ? "PDF" : "";
      const act = row.can_parse_activity !== false ? "CSV/Excel" : "";
      const modes = [pdf, act].filter(Boolean).join(" · ") || "CSV/Excel";
      return `<option value="${escapeHtml(row.id)}" ${row.id === current ? "selected" : ""}>${escapeHtml(
        row.label || row.id
      )} (${modes})</option>`;
    })
    .join("");
}

function populateMemberSelect(cardholders, selected) {
  const select = document.getElementById("memberSelect");
  if (!select) return;
  const current = selected || state.cardholder || "all";
  const opts = [`<option value="all">All members</option>`].concat(
    (cardholders || []).map(
      (name) =>
        `<option value="${escapeHtml(name)}" ${name === current ? "selected" : ""}>${escapeHtml(name)}</option>`
    )
  );
  select.innerHTML = opts.join("");
  if (current !== "all" && !(cardholders || []).includes(current)) {
    state.cardholder = "all";
    select.value = "all";
  } else {
    select.value = current;
  }
}

function populateTagSelect(tags, selected) {
  const select = document.getElementById("tagSelect");
  if (!select) return;
  const current = selected || state.tag || "all";
  const list = tags || [];
  const opts = [`<option value="all">All tags</option>`].concat(
    list.map(
      (name) =>
        `<option value="${escapeHtml(name)}" ${name === current ? "selected" : ""}>${escapeHtml(name)}</option>`
    )
  );
  select.innerHTML = opts.join("");
  if (current !== "all" && !list.includes(current)) {
    state.tag = "all";
    select.value = "all";
  } else {
    select.value = current;
  }
}

function formatTags(t) {
  const tags = Array.isArray(t.tags) && t.tags.length ? t.tags : [t.category || "Misc"];
  return tags
    .map((tag) => {
      const cls =
        tag === "Starbucks"
          ? " starbucks"
          : tag === "Tesla"
            ? " tesla"
            : tag === "Company" || t.company_expense
              ? " company"
              : tag === "Avoidable" || (t.avoidable && tag === t.category)
                ? " warn"
                : tag === "Coffee" || t.coffee
                  ? ""
                  : " mint";
      return `<span class="tag${cls}">${escapeHtml(tag)}</span>`;
    })
    .join(" ");
}

function render(data) {
  const empty = document.getElementById("emptyState");
  const dash = document.getElementById("dashboard");
  const select = document.getElementById("statementSelect");

  populateIssuerSelect(data.issuers || [], data.issuer_filter || state.issuer || "all");
  populateUploadIssuerSelect(data.issuers || []);

  if (!data.has_data) {
    empty.classList.remove("hidden");
    dash.classList.add("hidden");
    return;
  }

  empty.classList.add("hidden");
  dash.classList.remove("hidden");

  if (data.empty_issuer) {
    const insight = document.getElementById("insightText");
    if (insight) insight.textContent = data.message || "No statements for this issuer yet.";
    // Keep filters visible; skip metric/table render until data exists
    select.innerHTML = `<option value="ytd" selected>YTD · ${escapeHtml(
      data.issuer_filter_label || "issuer"
    )}</option>`;
    return;
  }

  const isYtd = state.statementId === "ytd";
  const ytd = data.ytd;
  const year = ytd?.year || new Date().getFullYear();
  const clubbed = !data.issuer_filter;
  const currentId = isYtd ? "ytd" : data.current?.statement_id;
  if (!isYtd && currentId) state.statementId = currentId;

  const ytdLabel = clubbed
    ? `YTD ${year} · all cards`
    : `YTD ${year} · ${data.issuer_filter_label || state.issuer}`;

  const stmtOpts = (data.statements || [])
    .map(
      (s) =>
        `<option value="${s.id}" ${!isYtd && s.id === currentId ? "selected" : ""}>${periodDisplay(
          s,
          { showIssuer: clubbed }
        )}</option>`
    )
    .join("");
  select.innerHTML =
    `<option value="ytd" ${isYtd ? "selected" : ""}>${escapeHtml(ytdLabel)}</option>` + stmtOpts;

  populateMemberSelect(
    isYtd
      ? (ytd?.by_cardholder || []).map((h) => h.cardholder)
      : data.current?.cardholders || [],
    data.cardholder_filter || state.cardholder
  );
  populateTagSelect(
    isYtd ? ytd?.tags || [] : data.current?.tags || ytd?.tags || [],
    data.tag_filter || state.tag
  );

  if (!data.current && !isYtd) {
    state.statementId = "ytd";
  }

  if (isYtd && ytd?.totals) {
    renderYtdMetrics(ytd);
    document.getElementById("insightText").textContent = buildYtdInsight(ytd, data);
    setOverviewTitles(true, ytd);
    renderChartsFromYtd(ytd);
    renderStatementTable(ytd.by_month || []);
    renderCardholderTable(ytd.by_cardholder || []);
    renderLeadersTable(data.member_leaders || []);
    const momLabel = document.getElementById("memberMomLabel");
    if (momLabel) {
      momLabel.textContent = data.previous
        ? `Latest vs ${data.previous.period_label}`
        : "Need another statement for MoM";
    }
    renderMemberMomTable(data.member_mom || [], data.previous?.period_label);
    renderWashedTable(ytd.washed_transactions || []);
    renderRefundTable(ytd.refund_transactions || []);
    renderCoffeeTable(ytd.coffee_transactions || []);
    renderAvoidableTable((ytd.avoidable_transactions || []).slice(0, 80));
    renderAllSpendTable((ytd.all_spend || []).slice(0, 200));
    renderMerchantTable(ytd.top_merchants || []);
    renderTransferTable(ytd.transfer_transactions || ytd.amex_send_transactions || [], ytd.totals || {});
    renderChargeTable(
      "transportBody",
      "transportSummary",
      ytd.transport_transactions || [],
      ytd.totals?.transport,
      ytd.totals?.transport_count,
      "Uber · Lyft · Ventra · parking"
    );
    renderTeslaPanel(ytd);
    renderDiningPanel(ytd);
    return;
  }

  setOverviewTitles(false);

  const t = data.current.totals;
  const d = data.deltas;
  const vsLabel = data.previous
    ? `vs ${data.previous.period_label}`
    : "vs prior";
  const memberNote =
    data.cardholder_filter || state.cardholder !== "all"
      ? ` · ${data.cardholder_filter || state.cardholder}`
      : "";

  // Primary spend = charges minus refunds/credits (whole dollars on overview)
  document.getElementById("metricSpend").textContent = moneyRound(t.net_spend);
  document.getElementById("metricRefunds").textContent = moneyRound(t.refunds);
  document.getElementById("metricNet").textContent = moneyRound(t.spend);
  document.getElementById("metricCoffee").textContent = moneyRound(t.coffee);
  document.getElementById("metricAvoidable").textContent = moneyRound(t.avoidable);
  document.getElementById("metricNecessary").textContent = moneyRound(t.necessary_estimate);
  document.getElementById("metricCompany").textContent = moneyRound(t.company_expense || 0);

  document.getElementById("subSpend").textContent = `${t.transaction_count} charges · bal ${moneyRound(data.current.new_balance)}${memberNote}`;
  document.getElementById("subRefunds").textContent = `${t.refund_count} credits · ${pct(t.refund_share_pct)} of gross`;
  document.getElementById("subNet").textContent = `${t.transaction_count} personal · after washes`;
  document.getElementById("subCoffee").textContent = `${t.coffee_count} visits · ${pct(t.coffee_share_pct)} · ~${moneyRound(t.coffee_annualized)}/yr`;
  document.getElementById("subAvoidable").textContent = `${t.avoidable_count} · ${pct(t.avoidable_share_pct)} of gross`;
  document.getElementById("subNecessary").textContent = "Rent, groceries, transit…";
  document.getElementById("subCompany").textContent = `${t.company_expense_count || 0} · Metropolis · excluded`;

  document.getElementById("deltaSpend").innerHTML = deltaEl(d?.net_spend, true, vsLabel);
  document.getElementById("deltaRefunds").innerHTML = deltaEl(d?.refunds, false, vsLabel);
  document.getElementById("deltaNet").innerHTML = deltaEl(d?.spend, true, vsLabel);
  document.getElementById("deltaCoffee").innerHTML = deltaEl(d?.coffee, true, vsLabel);
  document.getElementById("deltaAvoidable").innerHTML = deltaEl(d?.avoidable, true, vsLabel);
  document.getElementById("deltaCompany").innerHTML = deltaEl(d?.company_expense, true, vsLabel);

  const momLabel = document.getElementById("memberMomLabel");
  if (momLabel) {
    momLabel.textContent = data.previous
      ? `vs ${data.previous.period_label}`
      : "Upload another month for MoM";
  }

  document.getElementById("insightText").textContent = buildInsight(data);

  renderCharts(data.current);
  renderStatementTable(data.ytd?.by_month || []);
  renderCardholderTable(data.current.by_cardholder || []);
  renderLeadersTable(data.member_leaders || []);
  renderMemberMomTable(data.member_mom || [], data.previous?.period_label);
  renderWashedTable(data.current.washed_transactions || []);
  renderRefundTable(data.current.refund_transactions || []);
  renderCoffeeTable(data.current.coffee_transactions);
  renderAvoidableTable(data.current.avoidable_transactions.slice(0, 25));
  renderAllSpendTable((data.current.all_spend || []).slice(0, 80));
  renderMerchantTable(data.current.top_merchants);
  renderTransferTable(data.current.transfer_transactions || data.current.amex_send_transactions || [], data.current.totals);
  renderChargeTable(
    "transportBody",
    "transportSummary",
    data.current.transport_transactions || [],
    data.current.totals?.transport,
    data.current.totals?.transport_count,
    "Uber · Lyft · Ventra · parking"
  );
  renderTeslaPanel(data.ytd || data.current, data.current);
  renderDiningPanel(data.current);
}

function renderYtdMetrics(ytd) {
  const t = ytd.totals || {};
  const year = ytd.year || "YTD";
  document.getElementById("metricSpend").textContent = moneyRound(t.net_spend);
  document.getElementById("metricRefunds").textContent = moneyRound(t.refunds);
  document.getElementById("metricNet").textContent = moneyRound(t.spend);
  document.getElementById("metricCoffee").textContent = moneyRound(t.coffee);
  document.getElementById("metricAvoidable").textContent = moneyRound(t.avoidable);
  document.getElementById("metricNecessary").textContent = moneyRound(t.necessary_estimate);
  document.getElementById("metricCompany").textContent = moneyRound(t.company_expense || 0);

  document.getElementById("subSpend").textContent =
    `${ytd.statement_count || 0} statements · ${t.transaction_count || 0} charges · ${year}`;
  document.getElementById("subRefunds").textContent = `${t.refund_count || 0} credits YTD`;
  document.getElementById("subNet").textContent = "Personal gross YTD";
  document.getElementById("subCoffee").textContent =
    `${t.coffee_count || 0} visits · ${pct(t.coffee_share_pct)} of gross`;
  document.getElementById("subAvoidable").textContent =
    `${t.avoidable_count || 0} · ${pct(t.avoidable_share_pct)} of gross`;
  document.getElementById("subNecessary").textContent = "Gross − avoidable";
  document.getElementById("subCompany").textContent =
    `${t.company_expense_count || 0} · Metropolis · excluded`;

  const flat = `<div class="delta flat">Year-to-date · no MoM</div>`;
  ["deltaSpend", "deltaRefunds", "deltaNet", "deltaCoffee", "deltaAvoidable", "deltaCompany"].forEach(
    (id) => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = flat;
    }
  );
}

function buildYtdInsight(ytd, data) {
  const t = ytd.totals || {};
  const year = ytd.year || "YTD";
  return (
    `${year} YTD net ${moneyRound(t.net_spend)} across ${ytd.statement_count || 0} statements` +
    ` · coffee ${moneyRound(t.coffee)} (${t.coffee_count || 0} visits)` +
    ` · avoidable ${moneyRound(t.avoidable)}.`
  );
}

function setOverviewTitles(isYtd, ytd = null) {
  const set = (id, text) => {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  };
  if (isYtd) {
    const range =
      ytd?.from_date && ytd?.to_date ? `${ytd.from_date} → ${ytd.to_date}` : "Year to date";
    set("ovCategoryTitle", "Spend by category");
    set("ovCategorySub", range);
    set("ovDailyTitle", "Net by statement");
    set("ovDailySub", "Spend months");
    set("ovAvoidTitle", "Avoidable by statement");
    set("ovAvoidSub", "Year to date");
    set("ovCoffeeTitle", "Coffee by statement");
    set("ovCoffeeSub", "Year to date");
  } else {
    set("ovCategoryTitle", "Spend by category");
    set("ovCategorySub", "Personal");
    set("ovDailyTitle", "Daily spend");
    set("ovDailySub", "Charges");
    set("ovAvoidTitle", "Avoidable leak");
    set("ovAvoidSub", "By category");
    set("ovCoffeeTitle", "Coffee by shop");
    set("ovCoffeeSub", "Habit meter");
  }
}

function renderStatementTable(rows) {
  const monthBody = document.getElementById("ytdMonthBody");
  if (!monthBody) return;
  monthBody.innerHTML = rows.length
    ? rows
        .map(
          (m) => `<tr>
              <td>${escapeHtml(m.period_label)}<div class="muted">${
                m.period_start && m.period_end
                  ? `${escapeHtml(shortDate(m.period_start))}–${escapeHtml(shortDate(m.period_end))} · `
                  : ""
              }closed ${escapeHtml(m.closing_date)}</div></td>
              <td class="num">${money(m.net_spend)}</td>
              <td class="num">${money(m.coffee)}<div class="muted">${m.coffee_count}</div></td>
              <td class="num">${money(m.avoidable)}</td>
              <td class="num">${money(m.company_expense || 0)}</td>
              <td class="num">${money(m.spend)}</td>
            </tr>`
        )
        .join("")
    : `<tr><td colspan="6" class="muted">No statements this year.</td></tr>`;
}

function activateTab(key) {
  const tabs = document.querySelectorAll(".tabs > .tab");
  const panels = {
    overview: document.getElementById("panel-overview"),
    members: document.getElementById("panel-members"),
    activity: document.getElementById("panel-activity"),
    dining: document.getElementById("panel-dining"),
    transport: document.getElementById("panel-transport"),
    tesla: document.getElementById("panel-tesla"),
    "transfers": document.getElementById("panel-transfers"),
  };
  tabs.forEach((t) => {
    const on = t.dataset.tab === key;
    t.classList.toggle("active", on);
    t.setAttribute("aria-selected", on ? "true" : "false");
  });
  Object.entries(panels).forEach(([name, panel]) => {
    if (!panel) return;
    const on = name === key;
    panel.classList.toggle("active", on);
    panel.hidden = !on;
  });
  resizeChartsSoon();
}

function renderChartsFromYtd(ytd) {
  destroyCharts();
  const cats = (ytd.by_category || []).slice(0, 10);
  const months = ytd.by_month || [];

  const catCanvas = document.getElementById("categoryChart");
  if (catCanvas && cats.length) {
    charts.category = new Chart(catCanvas, {
      type: "doughnut",
      data: {
        labels: cats.map((c) => c.category),
        datasets: [
          {
            data: cats.map((c) => Math.round(c.total)),
            backgroundColor: palette(cats.length),
            borderWidth: 0,
          },
        ],
      },
      options: {
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "right", labels: { color: "#9aa8bc", boxWidth: 10, font: { size: 11 } } },
        },
        cutout: "62%",
      },
    });
  }

  const dailyCanvas = document.getElementById("dailyChart");
  if (dailyCanvas && months.length) {
    charts.daily = new Chart(dailyCanvas, {
      type: "bar",
      data: {
        labels: months.map((m) => m.period_label),
        datasets: [
          {
            label: "Net by statement",
            data: months.map((m) => Math.round(m.net_spend)),
            backgroundColor: "rgba(158, 176, 200, 0.82)",
            borderRadius: 6,
          },
        ],
      },
      options: {
        maintainAspectRatio: false,
        scales: {
          x: { ticks: { color: "#9aa8bc", maxRotation: 0 }, grid: { display: false } },
          y: {
            ticks: { color: "#9aa8bc", callback: (v) => `$${Math.round(v)}` },
            grid: { color: "rgba(214,222,234,0.08)" },
          },
        },
        plugins: { legend: { display: false } },
      },
    });
  }

  const avoidCanvas = document.getElementById("avoidableChart");
  if (avoidCanvas && months.length) {
    charts.avoidable = new Chart(avoidCanvas, {
      type: "bar",
      data: {
        labels: months.map((m) => m.period_label),
        datasets: [
          {
            label: "Avoidable",
            data: months.map((m) => Math.round(m.avoidable)),
            backgroundColor: "rgba(224, 138, 122, 0.82)",
            borderRadius: 8,
          },
        ],
      },
      options: {
        maintainAspectRatio: false,
        indexAxis: "y",
        scales: {
          x: {
            ticks: { color: "#9aa8bc", callback: (v) => `$${Math.round(v)}` },
            grid: { color: "rgba(214,222,234,0.08)" },
          },
          y: { ticks: { color: "#e8edf4" }, grid: { display: false } },
        },
        plugins: { legend: { display: false } },
      },
    });
  }

  const coffeeCanvas = document.getElementById("coffeeChart");
  if (coffeeCanvas && months.length) {
    charts.coffee = new Chart(coffeeCanvas, {
      type: "bar",
      data: {
        labels: months.map((m) => m.period_label),
        datasets: [
          {
            label: "Coffee",
            data: months.map((m) => Math.round(m.coffee)),
            backgroundColor: "rgba(212, 184, 150, 0.88)",
            borderRadius: 8,
          },
        ],
      },
      options: {
        maintainAspectRatio: false,
        scales: {
          x: { ticks: { color: "#9aa8bc" }, grid: { display: false } },
          y: {
            ticks: { color: "#9aa8bc", callback: (v) => `$${Math.round(v)}` },
            grid: { color: "rgba(214,222,234,0.08)" },
          },
        },
        plugins: { legend: { display: false } },
      },
    });
  }
  const holders = ytd.by_cardholder || [];
  const cardholderCanvas = document.getElementById("cardholderChart");
  if (cardholderCanvas && holders.length) {
    charts.cardholder = new Chart(cardholderCanvas, {
      type: "doughnut",
      data: {
        labels: holders.map((h) => h.cardholder),
        datasets: [
          {
            data: holders.map((h) => Math.round(h.total)),
            backgroundColor: ["#d7e0ec", "#9eb0c8", "#6f86a8", "#c9b7a0"],
            borderWidth: 0,
          },
        ],
      },
      options: {
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "right", labels: { color: "#9aa8bc", boxWidth: 10, font: { size: 11 } } },
        },
        cutout: "58%",
      },
    });
  }
}

function buildInsight(data) {
  const t = data.current.totals;
  const parts = [];
  const filter = data.cardholder_filter;
  if (filter) {
    parts.push(
      `${filter}: ${money(t.spend)} charged, ${money(t.coffee)} coffee (${t.coffee_count}), ${money(t.avoidable)} avoidable.`
    );
  } else {
    parts.push(
      `In ${data.current.period_label} net spend is ${money(t.net_spend)} after ${money(t.refunds)} refunds/credits on ${money(t.spend)} gross charges.`
    );
    parts.push(
      `Coffee was ${money(t.coffee)} across ${t.coffee_count} visits; avoidable spend hit ${money(t.avoidable)}.`
    );
  }

  const leaders = data.member_leaders || [];
  const coffeeLead = leaders.find((l) => l.metric_key === "__coffee__");
  const avoidLead = leaders.find((l) => l.metric_key === "__avoidable__");
  if (!filter && coffeeLead && coffeeLead.ranking?.length > 1) {
    parts.push(
      `${coffeeLead.winner} leads coffee at ${money(coffeeLead.amount)} (margin ${money(coffeeLead.margin)}).`
    );
  }
  if (!filter && avoidLead && avoidLead.ranking?.length > 1) {
    parts.push(`${avoidLead.winner} leads avoidable at ${money(avoidLead.amount)}.`);
  }

  if (data.previous && data.deltas?.coffee) {
    const prev = data.previous.period_label;
    const c = data.deltas.coffee;
    if (c.delta < 0) parts.push(`Coffee is down ${money(Math.abs(c.delta))} vs ${prev}.`);
    else if (c.delta > 0) parts.push(`Coffee jumped ${money(c.delta)} (${pct(c.pct)}) vs ${prev}.`);
    else parts.push(`Coffee is flat vs ${prev}.`);
  } else if (!data.previous) {
    parts.push(`At this pace, coffee alone is ~${money(t.coffee_annualized)}/year.`);
  }
  return parts.join(" ");
}

function renderLeadersTable(rows) {
  const body = document.getElementById("leadersBody");
  if (!body) return;
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="5" class="muted">Need card member activity to rank leaders.</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map(
      (r) => `<tr>
        <td>${escapeHtml(r.metric)}</td>
        <td><span class="tag">${escapeHtml(r.winner)}</span></td>
        <td class="num">${money(r.amount)}</td>
        <td>${r.runner_up ? escapeHtml(r.runner_up) + `<div class="muted">${money(r.runner_up_amount)}</div>` : `<span class="muted">—</span>`}</td>
        <td class="num">${r.runner_up ? money(r.margin) : "—"}</td>
      </tr>`
    )
    .join("");
}

function renderMemberMomTable(rows, prevLabel) {
  const body = document.getElementById("memberMomBody");
  if (!body) return;
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="5" class="muted">No member data.</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map((r) => {
      const m = r.metrics;
      const changeBits = [
        `Spend ${momChip(m.spend)}`,
        `Coffee ${momChip(m.coffee)}`,
        `Avoid ${momChip(m.avoidable)}`,
      ].join(" ");
      return `<tr>
        <td>${escapeHtml(r.cardholder)}${r.card_ending ? `<div class="muted">···${escapeHtml(String(r.card_ending).slice(-5))}</div>` : ""}</td>
        <td class="num">${money(m.spend.current)}<div class="muted">was ${money(m.spend.previous)}</div></td>
        <td class="num">${money(m.coffee.current)}<div class="muted">${m.coffee_count.current} visits · was ${money(m.coffee.previous)}</div></td>
        <td class="num">${money(m.avoidable.current)}<div class="muted">was ${money(m.avoidable.previous)}</div></td>
        <td>${prevLabel ? changeBits : `<span class="muted">Baseline month</span>`}</td>
      </tr>`;
    })
    .join("");
}

function renderWashedTable(rows) {
  const body = document.getElementById("washedBody");
  if (!body) return;
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="4" class="muted">No exact charge↔refund pairs washed this period.</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map(
      (w) => `<tr>
        <td>${w.date || "—"}</td>
        <td>${escapeHtml(w.cardholder || "—")}</td>
        <td>${escapeHtml(w.description || "")}<div class="muted">Matched refund removed from charges</div></td>
        <td class="num">${money(w.amount)}</td>
      </tr>`
    )
    .join("");
}

function renderRefundTable(rows) {
  const body = document.getElementById("refundBody");
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="5" class="muted">No refunds or statement credits this period.</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map(
      (t) => `<tr>
        <td>${t.date}</td>
        <td>${escapeHtml(t.cardholder || "—")}</td>
        <td>${escapeHtml(t.description)}</td>
        <td><span class="tag mint">${escapeHtml(t.refund_type || "Credit")}</span></td>
        <td class="num">−${money(t.credit_amount ?? Math.abs(t.amount))}</td>
      </tr>`
    )
    .join("");
}

function renderCharts(summary) {
  destroyCharts();

  const catLabels = summary.by_category.map((c) => c.category);
  const catValues = summary.by_category.map((c) => c.total);

  charts.category = new Chart(document.getElementById("categoryChart"), {
    type: "doughnut",
    data: {
      labels: catLabels,
      datasets: [
        {
          data: catValues,
          backgroundColor: palette(catLabels.length),
          borderWidth: 0,
        },
      ],
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "right", labels: { color: "#9aa8bc", boxWidth: 10, font: { size: 11 } } },
      },
      cutout: "62%",
    },
  });

  charts.daily = new Chart(document.getElementById("dailyChart"), {
    type: "bar",
    data: {
      labels: summary.daily.map((d) => d.date.slice(5)),
      datasets: [
        {
          label: "Daily spend",
          data: summary.daily.map((d) => d.total),
          backgroundColor: "rgba(158, 176, 200, 0.82)",
          borderRadius: 6,
        },
      ],
    },
    options: {
      maintainAspectRatio: false,
      scales: {
        x: { ticks: { color: "#9aa8bc", maxRotation: 0, autoSkip: true, maxTicksLimit: 10 }, grid: { display: false } },
        y: { ticks: { color: "#9aa8bc", callback: (v) => `$${v}` }, grid: { color: "rgba(214,222,234,0.08)" } },
      },
      plugins: { legend: { display: false } },
    },
  });

  charts.avoidable = new Chart(document.getElementById("avoidableChart"), {
    type: "bar",
    data: {
      labels: summary.avoidable_by_category.map((c) => c.category),
      datasets: [
        {
          label: "Avoidable",
          data: summary.avoidable_by_category.map((c) => c.total),
          backgroundColor: "rgba(224, 138, 122, 0.82)",
          borderRadius: 8,
        },
      ],
    },
    options: {
      maintainAspectRatio: false,
      indexAxis: "y",
      scales: {
        x: { ticks: { color: "#9aa8bc", callback: (v) => `$${v}` }, grid: { color: "rgba(214,222,234,0.08)" } },
        y: { ticks: { color: "#e8edf4" }, grid: { display: false } },
      },
      plugins: { legend: { display: false } },
    },
  });

  charts.coffee = new Chart(document.getElementById("coffeeChart"), {
    type: "bar",
    data: {
      labels: summary.coffee_merchants.map((m) => m.merchant),
      datasets: [
        {
          label: "Coffee",
          data: summary.coffee_merchants.map((m) => m.total),
          backgroundColor: "rgba(212, 184, 150, 0.88)",
          borderRadius: 8,
        },
      ],
    },
    options: {
      maintainAspectRatio: false,
      scales: {
        x: { ticks: { color: "#9aa8bc" }, grid: { display: false } },
        y: { ticks: { color: "#9aa8bc", callback: (v) => `$${v}` }, grid: { color: "rgba(214,222,234,0.08)" } },
      },
      plugins: { legend: { display: false } },
    },
  });

  const holders = summary.by_cardholder || [];
  const cardholderCanvas = document.getElementById("cardholderChart");
  if (cardholderCanvas && holders.length) {
    charts.cardholder = new Chart(cardholderCanvas, {
      type: "doughnut",
      data: {
        labels: holders.map((h) => h.cardholder),
        datasets: [
          {
            data: holders.map((h) => h.total),
            backgroundColor: ["#d7e0ec", "#9eb0c8", "#6f86a8", "#c9b7a0"],
            borderWidth: 0,
          },
        ],
      },
      options: {
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "right", labels: { color: "#9aa8bc", boxWidth: 10, font: { size: 11 } } },
        },
        cutout: "58%",
      },
    });
  }
}

function renderCardholderTable(rows) {
  const body = document.getElementById("cardholderBody");
  if (!body) return;
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="5" class="muted">No card member split on this statement.</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map(
      (h) => `<tr>
        <td><button type="button" class="btn btn-ghost member-link" data-member="${escapeHtml(h.cardholder)}" style="padding:6px 10px">${escapeHtml(h.cardholder)}</button>${h.card_ending ? `<div class="muted">···${escapeHtml(String(h.card_ending).slice(-5))}</div>` : ""}${h.reattributed_count ? `<div class="muted">+${h.reattributed_count} UIC Starbucks (${money(h.reattributed_amount)})</div>` : ""}</td>
        <td class="num">${h.count}</td>
        <td class="num">${money(h.coffee)}<div class="muted">${h.coffee_count} visits</div></td>
        <td class="num">${money(h.avoidable)}</td>
        <td class="num">${money(h.total)}<div class="muted">${pct(h.share_pct)}</div></td>
      </tr>`
    )
    .join("");

  body.querySelectorAll(".member-link").forEach((btn) => {
    btn.addEventListener("click", () => {
      loadDashboard(state.statementId, btn.dataset.member, state.tag, state.issuer);
    });
  });
}

function palette(n) {
  const base = [
    "#d7e0ec",
    "#9eb0c8",
    "#6f86a8",
    "#c9b7a0",
    "#8fb9a8",
    "#b8a0c4",
    "#e08a7a",
    "#7a8fa8",
    "#d4c4a8",
    "#5c7394",
  ];
  return Array.from({ length: n }, (_, i) => base[i % base.length]);
}

function renderDiningPanel(src) {
  const cuisines = src?.dining_by_cuisine || [];
  const restaurants = src?.dining_restaurants || [];
  const txs = src?.dining_transactions || [];
  const total = src?.dining_total || 0;
  const count = src?.dining_count || 0;
  const placeN = src?.dining_restaurant_count || restaurants.length;
  const cuisineN = src?.dining_cuisine_count || cuisines.length;

  const cuisineSummary = document.getElementById("diningCuisineSummary");
  if (cuisineSummary) {
    cuisineSummary.textContent =
      count === 0
        ? "No Dining Out this period"
        : `${moneyRound(total)} · ${count} visits · ${placeN} places · ${cuisineN} cuisines`;
  }
  const restSummary = document.getElementById("diningRestaurantSummary");
  if (restSummary) {
    restSummary.textContent =
      placeN === 0 ? "No restaurants yet" : `${placeN} distinct · sorted by visits`;
  }
  const allSummary = document.getElementById("diningAllSummary");
  if (allSummary) {
    allSummary.textContent =
      count === 0 ? "Dining Out only" : `${count} charges · ${moneyRound(total)}`;
  }

  const cuisineBody = document.getElementById("diningCuisineBody");
  if (cuisineBody) {
    if (!cuisines.length) {
      cuisineBody.innerHTML = `<tr><td colspan="4" class="muted">No dining spend this period.</td></tr>`;
    } else {
      cuisineBody.innerHTML = cuisines
        .map(
          (c) => `<tr>
            <td>${escapeHtml(c.cuisine)}</td>
            <td class="num">${c.restaurant_count}</td>
            <td class="num">${c.count}</td>
            <td class="num">${money(c.total)}</td>
          </tr>`
        )
        .join("");
    }
  }

  const restBody = document.getElementById("diningRestaurantBody");
  if (restBody) {
    if (!restaurants.length) {
      restBody.innerHTML = `<tr><td colspan="5" class="muted">No restaurants this period.</td></tr>`;
    } else {
      restBody.innerHTML = restaurants
        .map(
          (r) => `<tr>
            <td>${escapeHtml(r.restaurant)}</td>
            <td><span class="tag mint">${escapeHtml(r.cuisine)}</span></td>
            <td class="num">${r.count}</td>
            <td class="num">${money(r.total)}</td>
            <td>${escapeHtml(r.last_date || "")}</td>
          </tr>`
        )
        .join("");
    }
  }

  const allBody = document.getElementById("diningAllBody");
  if (allBody) {
    if (!txs.length) {
      allBody.innerHTML = `<tr><td colspan="5" class="muted">No dining charges this period.</td></tr>`;
    } else {
      allBody.innerHTML = txs
        .slice()
        .reverse()
        .map(
          (t) => `<tr>
            <td>${t.date}</td>
            <td>${escapeHtml(t.cardholder || "—")}</td>
            <td>${escapeHtml(t.restaurant || t.description || "")}</td>
            <td><span class="tag mint">${escapeHtml(t.cuisine || "")}</span></td>
            <td class="num">${money(t.amount)}</td>
          </tr>`
        )
        .join("");
    }
  }

  const canvas = document.getElementById("diningCuisineChart");
  if (canvas && typeof Chart !== "undefined") {
    if (charts.diningCuisine) {
      charts.diningCuisine.destroy();
      charts.diningCuisine = null;
    }
    if (cuisines.length) {
      charts.diningCuisine = new Chart(canvas, {
        type: "bar",
        data: {
          labels: cuisines.map((c) => c.cuisine),
          datasets: [
            {
              label: "Spend",
              data: cuisines.map((c) => c.total),
              backgroundColor: palette(cuisines.length),
              borderWidth: 0,
              borderRadius: 6,
            },
          ],
        },
        options: {
          indexAxis: "y",
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: (ctx) => money(ctx.raw),
              },
            },
          },
          scales: {
            x: {
              ticks: {
                color: "#9eb0c8",
                callback: (v) => `$${Math.round(v)}`,
              },
              grid: { color: "rgba(158,176,200,0.12)" },
            },
            y: {
              ticks: { color: "#d7e0ec", font: { size: 11 } },
              grid: { display: false },
            },
          },
        },
      });
    }
  }
}

function renderCoffeeTable(rows) {
  const body = document.getElementById("coffeeBody");
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="5" class="muted">No coffee purchases this period.</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map(
      (t) => `<tr class="row-coffee">
        <td>${t.date}</td>
        <td>${escapeHtml(t.cardholder || "—")}</td>
        <td>${escapeHtml(t.description)}</td>
        <td>${formatTags(t)}</td>
        <td class="num">${money(t.amount)}</td>
      </tr>`
    )
    .join("");
}

function transferType(t) {
  const d = (t.description || "").toUpperCase();
  if (d.includes("PLAN FEE")) return "Plan fee";
  if (d.includes("TRANSFER TO CARD")) return "To card";
  if (d.includes("ADD MONEY")) return "Add money";
  return t.kind || "Transfer";
}

function renderTransferTable(rows, totals) {
  const body = document.getElementById("transferBody");
  const summary = document.getElementById("transferSummary");
  if (summary && totals) {
    const n = totals.transfer_count ?? totals.amex_send_count ?? rows.length;
    summary.textContent =
      n === 0
        ? "Excluded from spend analytics · none this period"
        : `Excluded from spend · ${n} · in ${moneyRound(totals.transfer_in ?? totals.amex_send_in ?? 0)} · out ${moneyRound(totals.transfer_out ?? totals.amex_send_out ?? 0)}`;
  }
  if (!body) return;
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="5" class="muted">No transfer activity this period.</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map((t) => {
      const amt = t.amount;
      const signed = amt < 0 ? `−${money(Math.abs(amt))}` : money(amt);
      return `<tr>
        <td>${t.date}</td>
        <td>${escapeHtml(t.cardholder || "—")}</td>
        <td>${escapeHtml(t.description)}</td>
        <td><span class="tag">${escapeHtml(transferType(t))}</span></td>
        <td class="num">${signed}</td>
      </tr>`;
    })
    .join("");
}

function renderChargeTable(bodyId, summaryId, rows, total, count, emptyHint) {
  const body = document.getElementById(bodyId);
  const summary = document.getElementById(summaryId);
  const n = count ?? rows.length;
  if (summary) {
    summary.textContent =
      n === 0
        ? `None this period · ${emptyHint}`
        : `${n} charges · ${moneyRound(total || 0)}`;
  }
  if (!body) return;
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="5" class="muted">No charges this period.</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map(
      (t) => `<tr>
        <td>${t.date}</td>
        <td>${escapeHtml(t.cardholder || "—")}</td>
        <td>${escapeHtml(t.description)}</td>
        <td>${formatTags(t)}</td>
        <td class="num">${money(t.amount)}</td>
      </tr>`
    )
    .join("");
}

function teslaTypeLabel(t) {
  const c = t.category || "";
  if (c === "EV Charging") return "EV charging";
  if (c === "Tesla Insurance") return "Insurance";
  if (c === "Tesla FSD") return "FSD";
  if (c === "Tesla") return "Other";
  return c || "Tesla";
}

function renderTeslaAllTable(rows, totals) {
  const body = document.getElementById("teslaBody");
  const summary = document.getElementById("teslaSummary");
  const n = totals?.tesla_count ?? rows.length;
  if (summary) {
    summary.textContent =
      n === 0
        ? "None this period"
        : `${n} · ${moneyRound(totals?.tesla || 0)} · EV ${moneyRound(totals?.ev_charging || 0)} · Ins ${moneyRound(totals?.tesla_insurance || 0)} · FSD ${moneyRound(totals?.tesla_self_driving || 0)}`;
  }
  if (!body) return;
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="5" class="muted">No Tesla / EV charges this period.</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map(
      (t) => `<tr>
        <td>${t.date}</td>
        <td>${escapeHtml(t.cardholder || "—")}</td>
        <td>${escapeHtml(t.description)}</td>
        <td>${formatTags(t)}</td>
        <td class="num">${money(t.amount)}</td>
      </tr>`
    )
    .join("");
}

function renderTeslaMomTable(rows) {
  const body = document.getElementById("teslaMomBody");
  if (!body) return;
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="7" class="muted">No Tesla months yet.</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map((m, i) => {
      const prev = i > 0 ? rows[i - 1] : null;
      const delta = prev ? (m.tesla || 0) - (prev.tesla || 0) : null;
      let mom = `<span class="mom-chip flat">—</span>`;
      if (delta != null) {
        const cls = delta === 0 ? "flat" : delta > 0 ? "up" : "down";
        const arrow = delta === 0 ? "→" : delta > 0 ? "▲" : "▼";
        mom = `<span class="mom-chip ${cls}">${arrow} ${moneyRound(Math.abs(delta))}</span>`;
      }
      return `<tr>
        <td>${escapeHtml(m.period_label)}<div class="muted">${
          m.period_start && m.period_end
            ? `${escapeHtml(shortDate(m.period_start))}–${escapeHtml(shortDate(m.period_end))}`
            : `closed ${escapeHtml(m.closing_date || "")}`
        }</div></td>
        <td class="num">${money(m.ev_charging)}<div class="muted">${m.ev_charging_count || 0}</div></td>
        <td class="num">${money(m.tesla_insurance)}<div class="muted">${m.tesla_insurance_count || 0}</div></td>
        <td class="num">${money(m.tesla_self_driving)}<div class="muted">${m.tesla_self_driving_count || 0}</div></td>
        <td class="num">${money(m.tesla_other)}<div class="muted">${m.tesla_other_count || 0}</div></td>
        <td class="num">${money(m.tesla)}</td>
        <td>${mom}</td>
      </tr>`;
    })
    .join("");
}

/** source: ytd object (has tesla_mom + lists) or statement summary; optional current for period lists */
function renderTeslaPanel(ytdOrSummary, current = null) {
  const src = current || ytdOrSummary;
  const totals = src.totals || ytdOrSummary.totals || {};
  const lists = current || ytdOrSummary;
  renderTeslaAllTable(lists.tesla_transactions || [], totals);
  renderChargeTable(
    "evChargingBody",
    "evChargingSummary",
    lists.ev_charging_transactions || [],
    totals.ev_charging,
    totals.ev_charging_count,
    "Supercharger · ChargePoint · Jolt"
  );
  renderChargeTable(
    "teslaInsBody",
    "teslaInsSummary",
    lists.tesla_insurance_transactions || [],
    totals.tesla_insurance,
    totals.tesla_insurance_count,
    "Tesla Insurance"
  );
  renderChargeTable(
    "teslaFsdBody",
    "teslaFsdSummary",
    lists.tesla_self_driving_transactions || [],
    totals.tesla_self_driving,
    totals.tesla_self_driving_count,
    "Subscription / FSD"
  );
  renderTeslaMomTable(ytdOrSummary.tesla_mom || []);
}

function renderAvoidableTable(rows) {
  const body = document.getElementById("avoidableBody");
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="5" class="muted">No avoidable spend tagged.</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map(
      (t) => `<tr>
        <td>${t.date}</td>
        <td>${escapeHtml(t.cardholder || "—")}</td>
        <td>${escapeHtml(t.description)}</td>
        <td>${formatTags(t)}</td>
        <td class="num">${money(t.amount)}</td>
      </tr>`
    )
    .join("");
}

function renderAllSpendTable(rows) {
  const body = document.getElementById("allSpendBody");
  if (!body) return;
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="5" class="muted">No charges.</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map(
      (t) => `<tr>
        <td>${t.date}</td>
        <td>${escapeHtml(t.cardholder || "—")}</td>
        <td>${escapeHtml(t.description)}</td>
        <td>${formatTags(t)}</td>
        <td class="num">${money(t.amount)}</td>
      </tr>`
    )
    .join("");
}

function renderMerchantTable(rows) {
  const body = document.getElementById("merchantBody");
  body.innerHTML = rows
    .map(
      (m) => `<tr>
        <td>${escapeHtml(m.cardholder || "—")}</td>
        <td>${escapeHtml(m.merchant)}</td>
        <td>${escapeHtml(m.category)}${m.coffee ? ' <span class="tag">coffee</span>' : ""}${m.avoidable && !m.coffee ? ' <span class="tag warn">avoidable</span>' : ""}${m.company_expense ? ' <span class="tag company">company</span>' : ""}</td>
        <td class="num">${m.count}</td>
        <td class="num">${money(m.total)}</td>
      </tr>`
    )
    .join("");
}

function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function uploadFile(file) {
  if (!file) return;
  setStatus(`Uploading ${file.name}…`);
  const fd = new FormData();
  fd.append("file", file);
  const issuerEl = document.getElementById("uploadIssuerSelect");
  if (issuerEl && issuerEl.value) fd.append("issuer", issuerEl.value);
  try {
    const res = await fetch("/api/upload", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Upload failed");
    setStatus(data.message);
    setUploadOpen(false);
    const focusIssuer = data.statement?.issuer || state.issuer || "all";
    // Activity imports span many months — land on that issuer's YTD
    const focusPeriod = data.months_imported && data.months_imported > 1 ? "ytd" : data.statement.id;
    await loadDashboard(focusPeriod, state.cardholder, state.tag, focusIssuer);
  } catch (err) {
    setStatus(err.message || String(err), true);
  }
}

function setUploadOpen(open) {
  const drawer = document.getElementById("uploadDrawer");
  if (!drawer) return;
  drawer.classList.toggle("open", open);
}

function resizeChartsSoon() {
  requestAnimationFrame(() => {
    Object.values(charts).forEach((c) => {
      try {
        c.resize();
      } catch (_) {
        /* ignore */
      }
    });
  });
}

function activateSubtab(panel, subKey) {
  if (!panel || !subKey) return;
  panel.querySelectorAll(".subtab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.subtab === subKey);
  });
  panel.querySelectorAll(".subtab-panel").forEach((pane) => {
    const on = pane.id === `sub-${subKey}`;
    pane.classList.toggle("active", on);
    pane.hidden = !on;
  });
  resizeChartsSoon();
}

function wireTabs() {
  const tabs = document.querySelectorAll(".tabs > .tab");
  const panels = {
    overview: document.getElementById("panel-overview"),
    members: document.getElementById("panel-members"),
    activity: document.getElementById("panel-activity"),
    dining: document.getElementById("panel-dining"),
    transport: document.getElementById("panel-transport"),
    tesla: document.getElementById("panel-tesla"),
    "transfers": document.getElementById("panel-transfers"),
  };

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const key = tab.dataset.tab;
      tabs.forEach((t) => {
        const on = t === tab;
        t.classList.toggle("active", on);
        t.setAttribute("aria-selected", on ? "true" : "false");
      });
      Object.entries(panels).forEach(([name, panel]) => {
        if (!panel) return;
        const on = name === key;
        panel.classList.toggle("active", on);
        panel.hidden = !on;
      });
      resizeChartsSoon();
    });
  });

  document.querySelectorAll(".subtabs").forEach((nav) => {
    nav.querySelectorAll(".subtab").forEach((btn) => {
      btn.addEventListener("click", () => {
        const panel = nav.closest(".tab-panel");
        activateSubtab(panel, btn.dataset.subtab);
      });
    });
  });
}

function wireUpload() {
  const input = document.getElementById("fileInput");
  const drop = document.getElementById("dropzone");
  const browse = document.getElementById("browseBtn");
  const heroUpload = document.getElementById("heroUploadBtn");
  const closeUpload = document.getElementById("closeUploadBtn");
  const emptyUpload = document.getElementById("emptyUploadBtn");

  const openUpload = () => setUploadOpen(true);
  browse?.addEventListener("click", () => input.click());
  heroUpload?.addEventListener("click", openUpload);
  emptyUpload?.addEventListener("click", openUpload);
  closeUpload?.addEventListener("click", () => setUploadOpen(false));
  input.addEventListener("change", () => uploadFile(input.files?.[0]));

  ["dragenter", "dragover"].forEach((evt) =>
    drop.addEventListener(evt, (e) => {
      e.preventDefault();
      drop.classList.add("dragover");
    })
  );
  ["dragleave", "drop"].forEach((evt) =>
    drop.addEventListener(evt, (e) => {
      e.preventDefault();
      drop.classList.remove("dragover");
    })
  );
  drop.addEventListener("drop", (e) => {
    const file = e.dataTransfer?.files?.[0];
    uploadFile(file);
  });
  drop.addEventListener("click", () => input.click());

  document.getElementById("statementSelect").addEventListener("change", (e) => {
    loadDashboard(e.target.value, state.cardholder, state.tag, state.issuer);
  });

  const memberSelect = document.getElementById("memberSelect");
  if (memberSelect) {
    memberSelect.addEventListener("change", (e) => {
      loadDashboard(state.statementId, e.target.value, state.tag, state.issuer);
    });
  }
  const tagSelect = document.getElementById("tagSelect");
  if (tagSelect) {
    tagSelect.addEventListener("change", (e) => {
      loadDashboard(state.statementId, state.cardholder, e.target.value, state.issuer);
    });
  }
  const issuerSelect = document.getElementById("issuerSelect");
  if (issuerSelect) {
    issuerSelect.addEventListener("change", (e) => {
      // Switching issuer resets to clubbed/filtered YTD
      loadDashboard("ytd", state.cardholder, state.tag, e.target.value);
    });
  }
}

wireTabs();
wireUpload();
loadDashboard();
