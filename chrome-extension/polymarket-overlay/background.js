// Service worker: routes messages between the content script (on the
// Polymarket tab) and the offscreen document (which holds the WebSocket --
// service workers get suspended after ~30s idle in MV3 and can't keep a
// socket open, so all networking lives in the offscreen doc instead).

const OFFSCREEN_URL = chrome.runtime.getURL("offscreen.html");
let creatingOffscreen = null;
// slug -> Set<tabId>
const watchers = new Map();

async function ensureOffscreenDocument() {
  const existing = await chrome.runtime.getContexts({
    contextTypes: ["OFFSCREEN_DOCUMENT"],
    documentUrls: [OFFSCREEN_URL],
  });
  if (existing.length > 0) return;
  if (creatingOffscreen) {
    await creatingOffscreen;
    return;
  }
  creatingOffscreen = chrome.offscreen.createDocument({
    url: "offscreen.html",
    reasons: ["WORKERS"],
    justification: "Holds a live WebSocket to Polymarket's CLOB API for the market being viewed.",
  });
  await creatingOffscreen;
  creatingOffscreen = null;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || typeof message !== "object") return;

  if (message.type === "WATCH_MARKET" && message.target === "background") {
    const tabId = sender.tab && sender.tab.id;
    if (tabId == null) return;
    if (!watchers.has(message.slug)) watchers.set(message.slug, new Set());
    watchers.get(message.slug).add(tabId);
    ensureOffscreenDocument().then(() => {
      chrome.runtime.sendMessage({ type: "WATCH_MARKET", target: "offscreen", slug: message.slug });
    });
    return;
  }

  if (message.type === "UNWATCH_MARKET" && message.target === "background") {
    const tabId = sender.tab && sender.tab.id;
    const set = watchers.get(message.slug);
    if (set && tabId != null) {
      set.delete(tabId);
      if (set.size === 0) {
        watchers.delete(message.slug);
        chrome.runtime.sendMessage({ type: "UNWATCH_MARKET", target: "offscreen", slug: message.slug });
      }
    }
    return;
  }

  // Relay from offscreen -> whichever tabs are watching this slug.
  if (message.target === "content" && (message.type === "MARKET_SNAPSHOT" || message.type === "MARKET_ERROR")) {
    const set = watchers.get(message.slug);
    if (!set) return;
    for (const tabId of set) {
      chrome.tabs.sendMessage(tabId, message).catch(() => {});
    }
    return;
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  for (const [slug, set] of watchers.entries()) {
    set.delete(tabId);
    if (set.size === 0) {
      watchers.delete(slug);
      chrome.runtime.sendMessage({ type: "UNWATCH_MARKET", target: "offscreen", slug }).catch(() => {});
    }
  }
});
