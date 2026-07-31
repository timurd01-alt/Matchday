const DEFAULT_DATA_ORIGIN = "https://matchdayterminal.com";
const originInput = document.getElementById("origin");
const status = document.getElementById("status");

chrome.storage.local.get(["dataOrigin"], (stored) => {
  originInput.value = stored.dataOrigin || DEFAULT_DATA_ORIGIN;
});

document.getElementById("save").addEventListener("click", () => {
  const value = originInput.value.trim().replace(/\/$/, "");
  chrome.storage.local.set({ dataOrigin: value || DEFAULT_DATA_ORIGIN }, () => {
    status.textContent = "Saved. Reload any open Polymarket tabs to apply.";
  });
});
