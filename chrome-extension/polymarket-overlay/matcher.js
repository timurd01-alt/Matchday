// Team-name normalization + market-question matching.
// Ported (simplified, not identical) from Matchday's fetch_data.py norm()/_canon().
// Kept intentionally dependency-free so it can run in an offscreen document.

const NAME_SWAPS = {
  "korea republic": "south korea", "ir iran": "iran", "usa": "united states",
  "united states america": "united states", "cote d ivoire": "ivory coast",
  "cape verde islands": "cape verde", "turkiye": "turkey",
  "china pr": "china", "czechia": "czech republic",
};
const DROP_TOKENS = new Set(["and", "the", "of", "fc", "afc", "cf", "sc"]);

function canon(s) {
  if (!s) return "";
  const stripped = s.normalize("NFKD").replace(/[̀-ͯ]/g, "");
  const cleaned = stripped.toLowerCase().replace(/&/g, " and ").replace(/[^a-z0-9 ]+/g, " ");
  return cleaned.split(/\s+/).filter(t => t && !DROP_TOKENS.has(t)).join(" ");
}

function norm(name) {
  const s = canon(name);
  return NAME_SWAPS[s] || s;
}

// A team "appears" in a market question if its normalized tokens are all
// present (order-independent) in the normalized question text. Heuristic --
// tune per sport if false matches/misses show up.
function teamAppearsIn(teamName, questionText) {
  const teamTokens = norm(teamName).split(" ").filter(Boolean);
  if (!teamTokens.length) return false;
  const questionTokens = new Set(norm(questionText).split(" ").filter(Boolean));
  return teamTokens.every(t => questionTokens.has(t));
}

// Given a Polymarket question ("Will Arsenal beat Chelsea?", "Lakers vs
// Celtics", "Will Arsenal win the Premier League?") and a Matchday match
// record ({home:{name}, away:{name}, ...}), decide which side ("h" or "a")
// the market is asking about. Returns null if neither/both sides match.
function marketSide(questionText, match) {
  const homeIn = teamAppearsIn(match.home?.name || "", questionText);
  const awayIn = teamAppearsIn(match.away?.name || "", questionText);
  if (homeIn && !awayIn) return "h";
  if (awayIn && !homeIn) return "a";
  return null; // ambiguous (both/neither) -- don't guess
}

// Find the best-matching UPCOMING match for a market question across a list
// of already-fetched Matchday competition payloads ({comp, data}).
function findMatch(questionText, competitionPayloads) {
  for (const { comp, data } of competitionPayloads) {
    for (const match of (data && data.matches) || []) {
      if (match.status !== "UPCOMING") continue;
      const side = marketSide(questionText, match);
      if (side) return { comp, match, side };
    }
  }
  return null;
}

if (typeof self !== "undefined") {
  self.MatchdayMatcher = { norm, teamAppearsIn, marketSide, findMatch };
}
