const DEFAULT_DATA_ORIGIN = "https://matchdayterminal.com";
const DEFAULT_REGION = "eu";

// --- tabs ---
document.querySelectorAll("#tabs button").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#tabs button").forEach(b => b.classList.toggle("active", b === btn));
    document.getElementById("dashboard").hidden = btn.dataset.tab !== "dashboard";
    document.getElementById("settings").hidden = btn.dataset.tab !== "settings";
  });
});

// --- dashboard ---
function sparkline(history) {
  if (!history || history.length < 2) return "";
  const values = history.map(h => h.v);
  const min = Math.min(...values), max = Math.max(...values);
  const range = max - min || 1;
  const w = 60, h = 16;
  const points = history.map((pt, i) => {
    const x = (i / (history.length - 1)) * w;
    const y = h - ((pt.v - min) / range) * h;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <polyline points="${points}" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>`;
}

function pctCell(value, baseline) {
  const text = value != null ? value.toFixed(1) : "—";
  let cls = "";
  if (value != null && baseline != null) {
    const diff = value - baseline;
    cls = diff > 0.05 ? "pos" : diff < -0.05 ? "neg" : "";
  }
  return `<td class="${cls}">${text}</td>`;
}

async function renderDashboard() {
  const { watchedMarkets, alertThreshold } = await chrome.storage.local.get(["watchedMarkets", "alertThreshold"]);
  const threshold = Number(alertThreshold) || 0;
  const rows = Object.values(watchedMarkets || {}).sort((a, b) => (b.spread ?? -1) - (a.spread ?? -1));
  const tbody = document.getElementById("marketRows");
  const empty = document.getElementById("empty");
  if (!rows.length) {
    tbody.innerHTML = "";
    empty.hidden = false;
    return;
  }
  empty.hidden = true;
  tbody.innerHTML = rows.map(r => {
    const spreadCls = threshold && r.spread != null && r.spread >= threshold ? "spread-hi" : "";
    return `<tr>
      <td class="match">${r.home || "?"} vs ${r.away || "?"}<br><span style="color:#6b7280">${(r.comp || "").toUpperCase()}</span></td>
      ${pctCell(r.modelPct, null)}
      ${pctCell(r.oddsApiPct, r.modelPct)}
      ${pctCell(r.polymarketPct, r.modelPct)}
      ${pctCell(r.kalshiPct, r.modelPct)}
      <td class="${spreadCls}">${r.spread != null ? r.spread : "—"}</td>
      <td>${sparkline(r.history)}</td>
    </tr>`;
  }).join("");
}

document.getElementById("clear").addEventListener("click", () => {
  chrome.storage.local.set({ watchedMarkets: {} }, renderDashboard);
});

chrome.storage.onChanged.addListener((changes) => {
  if (changes.watchedMarkets) renderDashboard();
});

renderDashboard();

// --- settings ---
const FIELDS = ["origin", "oddsApiKey", "oddsApiRegion", "kalshiApiKey", "alertThreshold"];
const STORAGE_KEYS = {
  origin: "dataOrigin", oddsApiKey: "oddsApiKey",
  oddsApiRegion: "oddsApiRegion", kalshiApiKey: "kalshiApiKey",
  alertThreshold: "alertThreshold",
};
const status = document.getElementById("status");

chrome.storage.local.get(Object.values(STORAGE_KEYS), (stored) => {
  document.getElementById("origin").value = stored.dataOrigin || DEFAULT_DATA_ORIGIN;
  document.getElementById("oddsApiKey").value = stored.oddsApiKey || "";
  document.getElementById("oddsApiRegion").value = stored.oddsApiRegion || DEFAULT_REGION;
  document.getElementById("kalshiApiKey").value = stored.kalshiApiKey || "";
  document.getElementById("alertThreshold").value = stored.alertThreshold || "";
});

document.getElementById("save").addEventListener("click", () => {
  const update = {};
  for (const field of FIELDS) {
    update[STORAGE_KEYS[field]] = document.getElementById(field).value.trim();
  }
  update.dataOrigin = update.dataOrigin.replace(/\/$/, "") || DEFAULT_DATA_ORIGIN;
  update.oddsApiRegion = update.oddsApiRegion || DEFAULT_REGION;
  update.alertThreshold = Number(update.alertThreshold) || 0;
  chrome.storage.local.set(update, () => {
    status.textContent = "Saved. Reload any open Polymarket tabs to apply.";
  });
});
