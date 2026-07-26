"""Independent calibration check: Matchday's own model probability vs. an
outside reference (cached consensus market odds, or AP-style polls where no
market exists), for every currently-live competition except NHL (disabled
this session).

This is an AUDIT / validation tool, not a feature. It is deliberately kept
out of build()/main() and does not write anything back into data_*.json,
picks_log_*.json, or any file the live site reads. Nothing it prints is
displayed on the site.

Why this exists
----------------
The user asked for the model's predictions to be checked against an
independent predictor as a calibration sanity-check. The Odds API's match-
level odds account is quota-exhausted (confirmed live: HTTP 401
OUT_OF_USAGE_CREDITS, x-requests-remaining: 0, checked on the day of this
audit), so this script uses whatever "opening odds" snapshots are already
cached on disk (odds_open_<comp>.json), captured before the quota ran out.
ESPN is never used, in any form, per the standing rule in
PROVIDER_COMPLIANCE.md.

Methodology / leakage guard
----------------------------
- Only UPCOMING fixtures are compared. Comparing a FINISHED match's model
  output against a cached pre-kickoff market snapshot would silently feed
  the model *today's* team stats (which include every game played since,
  for an in-season sport) into what's supposed to be a pre-game prediction
  -- exactly the kind of post-event recomputation leakage this audit exists
  to catch. Competitions whose only cached matches are already FINISHED
  (NCAAM, UCL -- both off-season right now) are reported as "could not
  verify" instead of silently backtested with leaky inputs.
- The model side is recomputed fresh via fetch_data.predict(home, away, {},
  m) with an explicitly empty markets dict, so the returned "model" field
  is guaranteed pre-market-blend (the model's own judgment), never
  something already partly derived from a market. The site's own cached
  "prediction" field is NOT trusted here, because data_*.json's mtimes
  predate this session's four predict()/_upset_adjustment() fixes -- this
  script always reflects current fetch_data.py.
- The market side is the cached odds_open_<comp>.json snapshot, matched by
  fetch_data.pairkey(home, away) (falls back to a fuzzy name match the same
  way fetch_data.find_odds does). The "last" sub-snapshot is preferred (the
  most recently observed odds before the account ran dry); the top-level
  entry (first-seen "opening" odds) is used when "last" is absent.
- For NCAAF/NCAAM, where no match-level odds cache exists at all, AP-poll
  rank (m['home']/m['away']['model_rank'], sourced live from CFBD/CBBD --
  not ESPN) is used as a secondary independent reference: does the model
  favor the higher-ranked (lower number) team when exactly one side is
  ranked, or the better-ranked side when both are?

Usage
-----
    python audit_model_vs_market.py            # all in-scope competitions
    python audit_model_vs_market.py NFL MLB     # just these
"""
import json
import sys

import fetch_data as fd

# WC/UCL/EPL/LALIGA/SERIEA/BUNDESLIGA/LIGUE1/NFL/NCAAF/NCAAM/NBA/MLB per the
# explicit scope handed down this session. NHL is being disabled from the
# live site this session and is intentionally excluded.
COMPS = ["WC", "UCL", "EPL", "LALIGA", "SERIEA", "BUNDESLIGA", "LIGUE1",
         "NFL", "NCAAF", "NCAAM", "NBA", "MLB"]

DATA_FILE = {c: f"data_{c.lower()}.json" for c in COMPS}
ODDS_FILE = {c: f"odds_open_{c.lower()}.json" for c in COMPS}


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_odds_cache(comp):
    paths = [ODDS_FILE[comp]]
    if comp == "WC":
        paths.append("odds_open.json")  # legacy shared WC file, same convention as fetch_data._load_open
    for p in paths:
        d = _load_json(p)
        if d:
            return d
    return {}


def _market_pct(odds_cache, home, away):
    """Mirror fetch_data.find_odds()'s matching (exact pairkey, then fuzzy
    name overlap) but read straight off the on-disk cache dict rather than
    fetch_data's module-level _OPEN cache, so this never depends on which
    competition fetch_data.py's globals were last pointed at."""
    key = fd.pairkey(home, away)
    rec = odds_cache.get(key)
    match_kind = "exact"
    if rec is None:
        for k, r in odds_cache.items():
            names = k.split("|")
            if len(names) != 2:
                continue
            n1, n2 = names
            if (fd._name_match(home, n1) and fd._name_match(away, n2)) or \
               (fd._name_match(home, n2) and fd._name_match(away, n1)):
                rec, match_kind = r, "fuzzy"
                break
    if rec is None:
        return None, None
    snap = rec.get("last") or rec
    h, a, d = snap.get("h"), snap.get("a"), snap.get("d", 0)
    if h is None or a is None:
        return None, None
    # normalize snap's h/a/d ordering: on-disk keys are pairkey-sorted
    # (alphabetical), not necessarily home-first, so re-orient to the
    # fixture's actual home/away using the same norm() fetch_data uses.
    sorted_names = sorted([fd.norm(home), fd.norm(away)])
    if sorted_names[0] == fd.norm(home):
        home_pct, away_pct = h, a
    else:
        home_pct, away_pct = a, h
    return {"home_pct": home_pct, "away_pct": away_pct, "draw_pct": d}, match_kind


def _model_probs(comp, m):
    fd.COMP_KEY = comp
    fd.COMP = dict(fd.COMPETITIONS[comp])
    home, away = dict(m["home"]), dict(m["away"])
    pred = fd.predict(home, away, {}, m)
    return pred["model"], pred["why"]


def check_market_comp(comp):
    """Return (results, skip_reason). results is a list of per-fixture dicts;
    skip_reason is a human string when nothing could be verified."""
    data = _load_json(DATA_FILE.get(comp, ""))
    if not data or not data.get("matches"):
        return [], f"no cached data_{comp.lower()}.json / no matches in it"
    matches = [m for m in data["matches"] if m.get("status") == "UPCOMING"]
    if not matches:
        finished = sum(1 for m in data["matches"] if m.get("status") == "FINISHED")
        return [], (f"{len(data['matches'])} cached matches, but 0 are UPCOMING "
                     f"({finished} FINISHED, presumably off-season) -- skipped "
                     f"to avoid post-event recomputation leakage (see module docstring)")
    odds_cache = _load_odds_cache(comp)
    if not odds_cache:
        return [], f"no odds_open_{comp.lower()}.json cache (or it's empty) to compare against"

    out = []
    for m in matches:
        home_name, away_name = m["home"]["name"], m["away"]["name"]
        mkt, kind = _market_pct(odds_cache, home_name, away_name)
        if mkt is None:
            continue
        model, why = _model_probs(comp, m)
        out.append({
            "home": home_name, "away": away_name, "kickoff": m.get("kickoff"),
            "id": m.get("id"), "stage": m.get("stage"),
            "model_home_pct": model["h"], "model_away_pct": model["a"], "model_draw_pct": model.get("d", 0),
            "market_home_pct": mkt["home_pct"], "market_away_pct": mkt["away_pct"], "market_draw_pct": mkt.get("draw_pct", 0),
            "match_kind": kind,
            "abs_diff_home_pct": abs(model["h"] - mkt["home_pct"]),
            "model_favorite": "h" if model["h"] >= model["a"] else "a",
            "market_favorite": "h" if mkt["home_pct"] >= mkt["away_pct"] else "a",
        })
    if not out:
        return [], (f"{len(matches)} UPCOMING matches, but none matched any entry in "
                     f"odds_open_{comp.lower()}.json by team-name pair")
    return out, None


def check_poll_comp(comp):
    """AP-style poll rank comparison for NCAAF/NCAAM, used only where no
    match-level odds cache exists at all."""
    data = _load_json(DATA_FILE.get(comp, ""))
    if not data or not data.get("matches"):
        return [], f"no cached data_{comp.lower()}.json / no matches in it"
    matches = [m for m in data["matches"] if m.get("status") == "UPCOMING"]
    if not matches:
        finished = sum(1 for m in data["matches"] if m.get("status") == "FINISHED")
        return [], (f"{len(data['matches'])} cached matches, but 0 are UPCOMING "
                     f"({finished} FINISHED) -- skipped to avoid recomputation leakage")
    out = []
    for m in matches:
        hr, ar = m["home"].get("model_rank"), m["away"].get("model_rank")
        if not hr and not ar:
            continue
        model, why = _model_probs(comp, m)
        model_fav = "h" if model["h"] >= model["a"] else "a"
        if hr and ar:
            poll_fav = "h" if hr < ar else "a"
        else:
            poll_fav = "h" if hr else "a"  # the ranked side is the poll's favorite over an unranked team
        out.append({
            "home": m["home"]["name"], "away": m["away"]["name"], "kickoff": m.get("kickoff"),
            "home_rank": hr, "away_rank": ar,
            "model_home_pct": model["h"], "model_away_pct": model["a"],
            "model_favorite": model_fav, "poll_favorite": poll_fav,
            "agrees": model_fav == poll_fav,
        })
    if not out:
        return [], f"{len(matches)} UPCOMING matches, none had an AP-poll model_rank on either side"
    return out, None


def summarize(comp, results):
    n = len(results)
    mad = sum(r["abs_diff_home_pct"] for r in results) / n
    disagree = [r for r in results if r["model_favorite"] != r["market_favorite"]]
    lopsided_disagree = [r for r in disagree
                          if max(r["market_home_pct"], r["market_away_pct"]) >= 70]
    print(f"\n=== {comp}: {n} fixtures matched vs. cached market odds ===")
    print(f"  mean abs diff (model vs market home-win %%): {mad:.1f} pts")
    print(f"  favorite disagreements: {len(disagree)}/{n}")
    if lopsided_disagree:
        print(f"  *** {len(lopsided_disagree)} disagreement(s) on a LOPSIDED market (>=70/30) ***")
        for r in lopsided_disagree:
            print(f"      {r['home']} vs {r['away']} ({r['kickoff']}): "
                  f"model {r['model_home_pct']}/{r['model_away_pct']} "
                  f"vs market {r['market_home_pct']}/{r['market_away_pct']} "
                  f"[{r['match_kind']} match]")
    return {"comp": comp, "n": n, "mad": mad, "disagree": len(disagree),
            "lopsided_disagree": len(lopsided_disagree)}


def summarize_poll(comp, results):
    n = len(results)
    agree = sum(1 for r in results if r["agrees"])
    print(f"\n=== {comp}: {n} fixtures matched vs. AP-style poll rank ===")
    print(f"  model agrees with poll favorite: {agree}/{n}")
    for r in results:
        if not r["agrees"]:
            print(f"      DISAGREE: {r['home']} (#{r['home_rank'] or 'NR'}) vs "
                  f"{r['away']} (#{r['away_rank'] or 'NR'}) -- model favors "
                  f"{'home' if r['model_favorite']=='h' else 'away'} "
                  f"{r['model_home_pct']}/{r['model_away_pct']}")
    return {"comp": comp, "n": n, "agree": agree}


def main():
    only = set(a.upper() for a in sys.argv[1:]) or None
    market_summaries, poll_summaries, skipped = [], [], []
    for comp in COMPS:
        if only and comp not in only:
            continue
        results, reason = check_market_comp(comp)
        if reason:
            # NCAAF/NCAAM specifically have a poll-based fallback; try it
            # before giving up on the competition entirely.
            if comp in ("NCAAF", "NCAAM"):
                poll_results, poll_reason = check_poll_comp(comp)
                if poll_reason:
                    skipped.append((comp, f"{reason}; poll fallback also unavailable: {poll_reason}"))
                else:
                    print(f"\n[{comp}] no usable match-level odds cache ({reason}); "
                          f"falling back to AP-poll-rank comparison")
                    poll_summaries.append(summarize_poll(comp, poll_results))
                continue
            skipped.append((comp, reason))
            continue
        market_summaries.append(summarize(comp, results))

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for s in market_summaries:
        print(f"  {s['comp']:10s} n={s['n']:4d}  MAD={s['mad']:5.1f}pts  "
              f"favorite-disagree={s['disagree']}/{s['n']}  lopsided-disagree={s['lopsided_disagree']}")
    for s in poll_summaries:
        print(f"  {s['comp']:10s} n={s['n']:4d}  poll-agree={s['agree']}/{s['n']} (rank-based, no market)")
    if skipped:
        print("\nCould not verify (no leak-free comparison possible right now):")
        for comp, reason in skipped:
            print(f"  {comp:10s} -- {reason}")


if __name__ == "__main__":
    main()
