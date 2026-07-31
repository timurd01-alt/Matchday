// Runs on polymarket.com/event/* pages. Extracts the market slug, asks the
// background/offscreen pipeline to watch it, and renders a small overlay
// panel comparing Matchday's model, The Odds API's bookmaker consensus,
// Polymarket, and Kalshi. Polymarket is a SPA, so navigation between
// markets doesn't reload this script -- a cheap local poll of
// location.pathname (no network) catches slug changes.

let currentSlug = null;
let panel = null;
let lastSnapshot = null;
let lastWarning = null;

function slugFromLocation() {
  const match = location.pathname.match(/^\/event\/([^/]+)/);
  return match ? match[1] : null;
}

function ensurePanel() {
  if (panel) return panel;
  panel = document.createElement("div");
  panel.id = "mdx-roi-overlay";
  panel.innerHTML = `
    <div class="mdx-roi-head">
      <span>Matchday edge</span>
      <button type="button" class="mdx-roi-close" title="Hide">×</button>
    </div>
    <div class="mdx-roi-body">Loading…</div>
  `;
  document.body.appendChild(panel);
  panel.querySelector(".mdx-roi-close").addEventListener("click", () => {
    panel.style.display = "none";
  });
  return panel;
}

function pctRow(label, value, baseline) {
  const text = value != null ? `${value.toFixed(1)}%` : "—";
  let cls = "";
  if (value != null && baseline != null) {
    const diff = value - baseline;
    cls = diff > 0.05 ? "mdx-pos" : diff < -0.05 ? "mdx-neg" : "";
  }
  return `<div class="mdx-roi-row ${cls}"><span>${label}</span><span>${text}</span></div>`;
}

function render() {
  const body = ensurePanel().querySelector(".mdx-roi-body");
  if (!lastSnapshot && lastWarning) {
    body.textContent = lastWarning;
    return;
  }
  if (!lastSnapshot) {
    body.textContent = "Loading…";
    return;
  }
  const s = lastSnapshot;
  const rows = [
    pctRow("Model", s.modelPct, null),
    pctRow("Odds API (books)", s.oddsApiPct, s.modelPct),
    pctRow("Polymarket", s.polymarketPct, s.modelPct),
    pctRow("Kalshi", s.kalshiPct, s.modelPct),
  ].join("");
  const spreadText = s.spread != null ? `${s.spread} pt spread across markets` : "";
  body.innerHTML = `
    <div class="mdx-roi-row"><span>${s.home} vs ${s.away}</span></div>
    ${rows}
    ${spreadText ? `<div class="mdx-roi-note">${spreadText}</div>` : ""}
    ${lastWarning ? `<div class="mdx-roi-note">${lastWarning}</div>` : ""}
    <div class="mdx-roi-note">Not betting advice. Updated ${new Date(s.at).toLocaleTimeString()}</div>
  `;
}

function watch(slug) {
  currentSlug = slug;
  lastSnapshot = null;
  lastWarning = null;
  render();
  ensurePanel().style.display = "block";
  chrome.runtime.sendMessage({ type: "WATCH_MARKET", target: "background", slug });
}

function unwatch(slug) {
  if (!slug) return;
  chrome.runtime.sendMessage({ type: "UNWATCH_MARKET", target: "background", slug }).catch(() => {});
}

chrome.runtime.onMessage.addListener((message) => {
  if (!message || message.target !== "content" || message.slug !== currentSlug) return;
  if (message.type === "MARKET_SNAPSHOT") { lastSnapshot = message.snapshot; render(); }
  if (message.type === "MARKET_ERROR") { lastWarning = message.message; render(); }
});

function checkForNavigation() {
  const slug = slugFromLocation();
  if (slug === currentSlug) return;
  unwatch(currentSlug);
  if (slug) watch(slug);
  else if (panel) panel.style.display = "none";
}

window.addEventListener("pagehide", () => unwatch(currentSlug));
setInterval(checkForNavigation, 1000);
checkForNavigation();
