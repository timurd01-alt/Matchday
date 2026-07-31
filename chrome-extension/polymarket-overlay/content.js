// Runs on polymarket.com/event/* pages. Extracts the market slug, asks the
// background/offscreen pipeline to watch it, and renders a small overlay
// panel with the live model-vs-market comparison. Polymarket is a SPA, so
// navigation between markets doesn't reload this script -- a cheap local
// poll of location.pathname (no network) catches slug changes.

let currentSlug = null;
let panel = null;

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

function renderLoading() {
  ensurePanel().querySelector(".mdx-roi-body").textContent = "Loading…";
  ensurePanel().style.display = "block";
}

function renderError(message) {
  ensurePanel().querySelector(".mdx-roi-body").textContent = message;
}

function renderSnapshot(snapshot) {
  const body = ensurePanel().querySelector(".mdx-roi-body");
  const modelText = snapshot.modelPct != null ? `${snapshot.modelPct.toFixed(1)}%` : "n/a";
  const edgeText = snapshot.edgePoints != null
    ? `${snapshot.edgePoints > 0 ? "+" : ""}${snapshot.edgePoints} pt`
    : "n/a";
  const sign = snapshot.edgePoints > 0 ? "mdx-pos" : snapshot.edgePoints < 0 ? "mdx-neg" : "";
  body.innerHTML = `
    <div class="mdx-roi-row"><span>${snapshot.home} vs ${snapshot.away}</span></div>
    <div class="mdx-roi-row"><span>Model</span><span>${modelText}</span></div>
    <div class="mdx-roi-row"><span>Polymarket</span><span>${snapshot.marketPct.toFixed(1)}%</span></div>
    <div class="mdx-roi-row ${sign}"><span>Edge</span><span>${edgeText}</span></div>
    <div class="mdx-roi-note">Not betting advice. Updated ${new Date(snapshot.at).toLocaleTimeString()}</div>
  `;
}

function watch(slug) {
  currentSlug = slug;
  renderLoading();
  chrome.runtime.sendMessage({ type: "WATCH_MARKET", target: "background", slug });
}

function unwatch(slug) {
  if (!slug) return;
  chrome.runtime.sendMessage({ type: "UNWATCH_MARKET", target: "background", slug }).catch(() => {});
}

chrome.runtime.onMessage.addListener((message) => {
  if (!message || message.target !== "content" || message.slug !== currentSlug) return;
  if (message.type === "MARKET_SNAPSHOT") renderSnapshot(message.snapshot);
  if (message.type === "MARKET_ERROR") renderError(message.message);
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
