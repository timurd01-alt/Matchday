const DEFAULT_DATA_ORIGIN = "https://matchdayterminal.com";
const DEFAULT_REGION = "eu";
const FIELDS = ["origin", "oddsApiKey", "oddsApiRegion", "kalshiApiKey"];
const STORAGE_KEYS = {
  origin: "dataOrigin", oddsApiKey: "oddsApiKey",
  oddsApiRegion: "oddsApiRegion", kalshiApiKey: "kalshiApiKey",
};
const status = document.getElementById("status");

chrome.storage.local.get(Object.values(STORAGE_KEYS), (stored) => {
  document.getElementById("origin").value = stored.dataOrigin || DEFAULT_DATA_ORIGIN;
  document.getElementById("oddsApiKey").value = stored.oddsApiKey || "";
  document.getElementById("oddsApiRegion").value = stored.oddsApiRegion || DEFAULT_REGION;
  document.getElementById("kalshiApiKey").value = stored.kalshiApiKey || "";
});

document.getElementById("save").addEventListener("click", () => {
  const update = {};
  for (const field of FIELDS) {
    update[STORAGE_KEYS[field]] = document.getElementById(field).value.trim();
  }
  update.dataOrigin = update.dataOrigin.replace(/\/$/, "") || DEFAULT_DATA_ORIGIN;
  update.oddsApiRegion = update.oddsApiRegion || DEFAULT_REGION;
  chrome.storage.local.set(update, () => {
    status.textContent = "Saved. Reload any open Polymarket tabs to apply.";
  });
});
