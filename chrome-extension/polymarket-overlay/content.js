// Runs on every polymarket.com page (broadened from just /event/* -- the
// exact URL structure for sports markets couldn't be verified live, so
// instead of guessing one pattern and silently doing nothing when it's
// wrong, this now shows a status chip everywhere and *tries* whatever the
// last path segment is, letting the Gamma API lookup itself decide whether
// it's a real market. That also means the panel is now always visible as a
// diagnostic: if you see "idle" instead of nothing, the extension is alive
// and the problem is elsewhere.

const NON_MARKET_SEGMENTS = new Set([
  "", "markets", "sports", "elections", "profile", "portfolio", "leaderboard",
  "activity", "rewards", "about", "terms", "privacy", "search", "watchlist",
]);

let currentSlug = null;
let panel = null;
let lastSnapshot = null;
let lastWarning = null;
let alertThreshold = 0;
let dragOffset = null;

function candidateSlug() {
  const segments = location.pathname.split("/").filter(Boolean);
  if (!segments.length) return null;
  const last = segments[segments.length - 1];
  if (NON_MARKET_SEGMENTS.has(last.toLowerCase())) return null;
  return last;
}

function ensurePanel() {
  if (panel) return panel;
  panel = document.createElement("div");
  panel.id = "mdx-roi-overlay";
  panel.innerHTML = `
    <div class="mdx-roi-head">
      <span class="mdx-roi-title">Matchday edge</span>
      <span class="mdx-roi-status"></span>
      <button type="button" class="mdx-roi-close" title="Hide">×</button>
    </div>
    <div class="mdx-roi-body">Idle -- not on a market page.</div>
  `;
  document.body.appendChild(panel);
  panel.querySelector(".mdx-roi-close").addEventListener("click", () => {
    panel.style.display = "none";
  });
  makeDraggable(panel, panel.querySelector(".mdx-roi-head"));
  applySavedPosition(panel);
  return panel;
}

function makeDraggable(el, handle) {
  handle.addEventListener("mousedown", (e) => {
    if (e.target.closest(".mdx-roi-close")) return;
    const rect = el.getBoundingClientRect();
    dragOffset = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    el.classList.add("mdx-dragging");
  });
  window.addEventListener("mousemove", (e) => {
    if (!dragOffset) return;
    el.style.left = `${Math.max(0, e.clientX - dragOffset.x)}px`;
    el.style.top = `${Math.max(0, e.clientY - dragOffset.y)}px`;
    el.style.right = "auto";
    el.style.bottom = "auto";
  });
  window.addEventListener("mouseup", () => {
    if (!dragOffset) return;
    dragOffset = null;
    el.classList.remove("mdx-dragging");
    chrome.storage.local.set({ panelPos: { left: el.style.left, top: el.style.top } });
  });
}

function applySavedPosition(el) {
  chrome.storage.local.get(["panelPos"], (stored) => {
    if (stored.panelPos && stored.panelPos.left) {
      el.style.left = stored.panelPos.left;
      el.style.top = stored.panelPos.top;
      el.style.right = "auto";
      el.style.bottom = "auto";
    }
  });
}

function sparkline(history) {
  if (!history || history.length < 2) return "";
  const values = history.map(h => h.v);
  const min = Math.min(...values), max = Math.max(...values);
  const range = max - min || 1;
  const w = 100, h = 24;
  const points = history.map((pt, i) => {
    const x = (i / (history.length - 1)) * w;
    const y = h - ((pt.v - min) / range) * h;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return `<svg class="mdx-spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <polyline points="${points}" fill="none" stroke="currentColor" stroke-width="1.5"/>
  </svg>`;
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

function updateAlertHighlight(snapshot) {
  if (!panel || !alertThreshold) { panel && panel.classList.remove("mdx-alert"); return; }
  const gap = snapshot.spread != null ? snapshot.spread
    : (snapshot.modelPct != null && snapshot.polymarketPct != null
      ? Math.abs(snapshot.modelPct - snapshot.polymarketPct) : null);
  panel.classList.toggle("mdx-alert", gap != null && gap >= alertThreshold);
}

function render() {
  const el = ensurePanel();
  const status = el.querySelector(".mdx-roi-status");
  const body = el.querySelector(".mdx-roi-body");

  if (!currentSlug) {
    status.textContent = "idle";
    body.textContent = "Not on a market page.";
    el.classList.remove("mdx-alert");
    return;
  }
  if (!lastSnapshot && lastWarning) {
    status.textContent = "no match";
    body.textContent = lastWarning;
    return;
  }
  if (!lastSnapshot) {
    status.textContent = "loading…";
    body.textContent = "Looking up this market…";
    return;
  }
  const s = lastSnapshot;
  status.textContent = "watching";
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
    ${sparkline(s.history)}
    ${spreadText ? `<div class="mdx-roi-note">${spreadText}</div>` : ""}
    ${lastWarning ? `<div class="mdx-roi-note">${lastWarning}</div>` : ""}
    <div class="mdx-roi-note">Not betting advice. Updated ${new Date(s.at).toLocaleTimeString()}</div>
  `;
  updateAlertHighlight(s);
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

chrome.storage.local.get(["alertThreshold"], (stored) => {
  alertThreshold = Number(stored.alertThreshold) || 0;
});
chrome.storage.onChanged.addListener((changes) => {
  if (changes.alertThreshold) alertThreshold = Number(changes.alertThreshold.newValue) || 0;
});

function checkForNavigation() {
  const slug = candidateSlug();
  if (slug === currentSlug) return;
  unwatch(currentSlug);
  currentSlug = null;
  if (slug) watch(slug);
  else render();
}

window.addEventListener("pagehide", () => unwatch(currentSlug));
setInterval(checkForNavigation, 1000);
ensurePanel();
checkForNavigation();
