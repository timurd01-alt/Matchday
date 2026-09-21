import pathlib
import unittest

import build_cfb_snapshot


ROOT = pathlib.Path(__file__).resolve().parent


class CurrentCfbSnapshotTests(unittest.TestCase):
    def test_fallback_header_uses_the_fresh_prediction_sync(self):
        builder = (ROOT / "build_cfb_snapshot.py").read_text(encoding="utf-8")
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        self.assertIn("MATCHDAY_BETBETTER_GENERATED_AT", builder)
        self.assertIn("Predictions synced ${ago(syncedAt)}", panels)
        self.assertNotIn("fallback snapshot ${ago", panels)

    def test_pending_cards_are_not_called_losses(self):
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        recent = panels[panels.index("function _scRecent(rows)"):panels.index("function renderScore()")]
        self.assertIn("['win','loss'].includes", recent)
        self.assertIn("graded.slice(0,10)", recent)

    def test_ap_poll_is_separate_and_drives_the_cfp_projection(self):
        builder = (ROOT / "build_cfb_snapshot.py").read_text(encoding="utf-8")
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        features = (ROOT / "app-4-features.js").read_text(encoding="utf-8")
        self.assertIn("MATCHDAY_CFB_AP_POLL", builder)
        self.assertIn("MATCHDAY_CFB_AP_BRACKET", builder)
        self.assertIn("table_type:'official_poll'", panels)
        self.assertIn("?MATCHDAY_CFB_AP_BRACKET", panels)
        self.assertIn("Projected from the current AP Poll", features)
        self.assertIn("!['PROJECTED','TBD'].includes", features)

    def test_ap_poll_rows_include_record_and_matchday_power(self):
        builder = (ROOT / "build_cfb_snapshot.py").read_text(encoding="utf-8")
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        self.assertIn('"record": rated.get("record") or "—"', builder)
        self.assertIn('"rating": rated.get("rating")', builder)
        self.assertIn('"external_rank": rated.get("rank")', builder)
        self.assertIn('>Record</th>', panels)
        self.assertIn('>Power</th>', panels)

    def test_snapshot_replaces_old_record_and_stale_bracket(self):
        snapshot = (ROOT / "matchday-cfb-snapshot.js").read_text(encoding="utf-8")
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        self.assertIn("scorecard:{graded:8,model_hits:6,pending:0", snapshot)
        self.assertEqual(snapshot.count("result:'HIT'"), 6)
        self.assertEqual(snapshot.count("result:'MISS'"), 2)
        self.assertIn("?MATCHDAY_CFB_AP_BRACKET:(MATCHDAY_CFB_SNAPSHOT.bracket||[])", panels)
        self.assertIn("applyCurrentCfbSnapshot(DATA)", panels)
        self.assertIn("g.group!=='Matchday Top 25'", panels)
        self.assertIn("DATA.comp_key==='NCAAF'?'Conferences'", panels)

    def test_the_owners_ballot_ships_apart_from_the_power_rating(self):
        """My Top 25 is a person's call and must never borrow the model table's name."""
        builder = (ROOT / "build_cfb_snapshot.py").read_text(encoding="utf-8")
        views = (ROOT / "app-2-views.js").read_text(encoding="utf-8")
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        self.assertIn('const MATCHDAY_BETBETTER_BALLOT="', builder)
        self.assertIn('document.get("ballots")', builder)
        self.assertIn("modBallot(),modTop25()", views)
        self.assertIn("!b?.available", views)
        self.assertIn("collegeBallotTableHTML()", panels)

    def test_board_card_explanations_sit_behind_a_question_mark(self):
        """The notes moved behind each card's ?; they must not creep back or be reparsed."""
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        views = (ROOT / "app-2-views.js").read_text(encoding="utf-8")
        render = core[core.index("$('#view-matches').innerHTML=html"):]
        self.assertLess(render.index("collapseBoardNotes("), render.index("fitRankingCard()"))
        collapse = views[views.index("function collapseBoardNotes("):views.index("function boardTip(")]
        self.assertIn("textContent", collapse)
        self.assertNotIn("innerHTML", collapse)

    def test_board_packs_every_module_to_one_bottom_edge(self):
        """Every card stays visible and the three columns form one rectangle."""
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        views = (ROOT / "app-2-views.js").read_text(encoding="utf-8")
        styles = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertIn("balanceBoardMods()", core)
        self.assertIn("function balanceBoardMods(){", views)
        self.assertIn("column.cards.push(item.card)", views)
        self.assertIn(".modsCol>.boardMod:last-child{flex:1;display:flex;flex-direction:column}", styles)
        self.assertIn(".modsCol>.boardMod:last-child>.tsTable{flex:1}", styles)
        self.assertNotIn('class="boardMore"', views)

    def test_bottom_cards_are_filled_with_real_ranking_context(self):
        views = (ROOT / "app-2-views.js").read_text(encoding="utf-8")
        self.assertIn("Math.max(25,Math.min(items.length,fits))", views)
        self.assertIn("function modConferenceTable(){", views)
        self.assertIn("<h3>Conference table</h3>", views)
        self.assertIn('class="confLeader"', views)
        self.assertIn("modConferenceTable()", views)
        self.assertNotIn("<h3>Power vs Group of Five</h3>", views)
        parity = views[views.index("function modConferenceParity(){"):views.index("function collegeModules(){")]
        self.assertIn("const body=stats.map", parity)
        self.assertIn("every rated league", parity)
        self.assertNotIn("stats.slice", parity)

    def test_games_home_leads_with_predictions_not_analysis_modules(self):
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        render = core[core.index("function renderMatches(){"):]
        render = render[:render.index(chr(10) + "function ", 1)]
        self.assertIn("gamesSummaryHTML(active)", render)
        self.assertIn("groupedBoardHTML(shown)", render)
        self.assertLess(render.index("gamesSummaryHTML(active)"),
                        render.index("groupedBoardHTML(shown)"))
        self.assertNotIn("collegeModules", render)
        summary = core[core.index("function gamesSummaryHTML("):
                       core.index("function renderMatches(){")]
        for destination in ("Featured game", "Largest model / market differences",
                            "Public record", "Explore"):
            self.assertIn(destination, summary)

    def test_games_home_uses_one_model_and_null_safe_comparisons(self):
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        read = core[core.index("function gamesBoardRead("):
                    core.index("function gamesSummaryHTML(")]
        self.assertIn("betbetterReadFor", read)
        self.assertIn("v==null||v===''?null", read)
        self.assertIn("market==null?null", read)
        for banned in ("m.prediction", "_v10OfficialPick", "officialPrediction"):
            self.assertNotIn(banned, read)

    def test_news_is_a_primary_navigation_item(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-primary data-v="news"', html)

    def test_the_welcome_cards_model_read_is_bet_betters(self):
        """The gate quotes one model, the same one every other screen quotes.

        The IN FOCUS card read m.prediction through _v10OfficialPick -- that is
        Matchday's own forecast, not the engine behind the card, the Top 25 and
        the expanded view. On one live fixture the two disagreed 96.5% to 50%,
        under the same word, MODEL, on the first screen a visitor ever sees.
        Same rule as the card and the expanded panel: the engine's read, or no
        number at all.
        """
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        start = core.index("function _welcomeCardHTML(m){")
        body = core[start:core.index(chr(10) + "function ", start + 1)]
        self.assertIn("betbetterReadFor", body,
                      "the welcome card must resolve its read through the engine")
        for banned in ("_v10OfficialPick", "officialPrediction", "m.prediction"):
            self.assertNotIn(banned, body,
                             f"the welcome card reads {banned} -- that is the other "
                             "model, and the site publishes one")
        # The card shows a model read or it shows nothing: renderWelcome only
        # ever hands it a fixture the engine has priced, so an out-of-season
        # board falls through to the standing panel instead of putting a
        # fixture on screen with no number beside it.
        render = core[core.index("function renderWelcome()"):]
        render = render[:render.index(chr(10) + "}")]
        self.assertIn("betbetterReadFor", render,
                      "renderWelcome must filter the card's pool to priced fixtures")
        self.assertIn("welcomeFallback", render,
                      "with nothing priced the gate needs its standing panel")

    def test_there_is_no_merged_all_college_board(self):
        # The merged board showed both sports' fixtures with every sport-specific
        # view stripped out -- a strictly smaller version of the sport pages it
        # sat above. Nothing may reintroduce it: each board is one sport's file.
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("competition:'All college'", panels)
        self.assertNotIn('<option value="">', html)
        self.assertIn("const DEFAULT_SPORT_FILE=", core)

    def test_ncaam_keeps_conferences_and_gets_rankings_bracketology(self):
        snapshot = (ROOT / "matchday-cfb-snapshot.js").read_text(encoding="utf-8")
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        self.assertIn("const MATCHDAY_NCAAM_SNAPSHOT", snapshot)
        self.assertIn("buildNcaamBracketology", panels)
        self.assertIn("applyCurrentNcaamSnapshot(DATA)", panels)

    def test_external_ratings_freshness_and_expanded_view(self):
        snapshot = (ROOT / "matchday-cfb-snapshot.js").read_text(encoding="utf-8")
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        features = (ROOT / "app-4-features.js").read_text(encoding="utf-8")
        # The rankings are generated from the Bet Better handoff now, not typed
        # into the file, so the marker and the reference are what to assert on.
        self.assertIn("BEGIN GENERATED RANKINGS", snapshot)
        self.assertIn("rankings:MATCHDAY_CFB_RANKINGS.rankings", snapshot)
        self.assertIn('"sos"', snapshot)
        self.assertIn("rating:ranked?.rating??null", panels)
        # The snapshot's stamp is reconciled with the payload's, not written
        # over it. It used to overwrite, and because the snapshot is rebuilt
        # only when a new handoff arrives while data_*.json is refetched hourly,
        # the board reported itself days stale whenever the handoff was the
        # older of the two -- "data 4 days ago" above fixtures fetched that
        # morning. See test_data_age.py.
        self.assertIn(
            "payload.updated=_freshestUpdated(payload.updated,MATCHDAY_CFB_SNAPSHOT.updated)",
            panels)
        # renderInsight() lives in app-4-features.js, so it cannot bound a slice of
        # app-3-panels.js. _v4TitleRows is the function that actually follows
        # details() in this file.
        details = panels[panels.index("function details(m){"):panels.index("function _v4TitleRows(")]
        self.assertNotIn("pregameContextPanel(m)", details)
        self.assertIn("modernExpandedView", details)
        self.assertIn("modernMatchSheet", features)
        # The caption used to call this rating "context only" and a preseason
        # tiebreaker, which was false -- the model does use it. It now names the
        # rating and ships the schedule beside it.
        self.assertIn("Opponent-adjusted rating and strength of schedule", panels)
        self.assertIn("sosTag", panels)





def _entry(rows):
    return {"rankings": rows}


def _row(rank, name, conference, tier="power"):
    return {"rank": rank, "team_name": name, "team_key": name.lower().replace(" ", "-"),
            "conference": conference, "tier": tier}


def _season(**overrides):
    """A rated table shaped like a real one: four Power Four conferences, a
    handful of Group of Five conferences well down the ranking, and one
    independent."""
    rows = [
        _row(1, "Indiana", "Big Ten"),
        _row(2, "Ohio State", "Big Ten"),
        _row(3, "Notre Dame", "FBS Independents"),
        _row(4, "Oregon", "Big Ten"),
        _row(5, "Miami", "ACC"),
        _row(6, "Texas", "SEC"),
        _row(7, "Georgia", "SEC"),
        _row(8, "Utah", "Big 12"),
        _row(9, "Ole Miss", "SEC"),
        _row(10, "Texas Tech", "Big 12"),
        _row(11, "Alabama", "SEC"),
        _row(12, "Penn State", "Big Ten"),
        _row(13, "Clemson", "ACC"),
    ]
    rows += [_row(50 + i, f"G5 {conf}", conf, "group_of_five")
             for i, conf in enumerate(("Sun Belt", "American Athletic", "Mid-American"))]
    rows += overrides.get("extra", [])
    return _entry(rows)


class CfpBracketFormatTests(unittest.TestCase):
    def field(self, entry=None):
        return build_cfb_snapshot.cfp_field(entry or _season())

    def test_field_is_twelve_seeded_straight_by_ranking(self):
        field = self.field()
        self.assertEqual(len(field), 12)
        self.assertEqual([r["cfp_seed"] for r in field], list(range(1, 13)))
        # Straight seeding: seed order is ranking order, whatever a team won.
        self.assertEqual([r["rank"] for r in field], sorted(r["rank"] for r in field))

    def test_every_power_four_champion_is_in(self):
        names = {r["team_name"] for r in self.field()}
        # Best-rated team in each of the four, which is the projected champion.
        for champion in ("Indiana", "Miami", "Texas", "Utah"):
            self.assertIn(champion, names)

    def test_one_group_of_five_champion_takes_the_last_bid(self):
        field = self.field()
        g5 = [r for r in field if r["tier"] == "group_of_five"]
        self.assertEqual(len(g5), 1)
        # The best-ranked one, and it displaces the twelfth-best team rather
        # than being left out of a top-twelve cut.
        self.assertEqual(g5[0]["team_name"], "G5 Sun Belt")
        self.assertEqual(g5[0]["cfp_seed"], 12)
        self.assertNotIn("Penn State", {r["team_name"] for r in field})

    def test_an_independent_gets_in_on_ranking_alone(self):
        # Notre Dame has no conference and so no automatic bid. Ranked third, it
        # is in as an at-large and seeded third.
        nd = next(r for r in self.field() if r["team_name"] == "Notre Dame")
        self.assertEqual(nd["cfp_bid"], "at-large")
        self.assertEqual(nd["cfp_seed"], 3)

    def test_an_independent_outside_the_twelve_is_out(self):
        entry = _season()
        for row in entry["rankings"]:
            if row["team_name"] == "Notre Dame":
                row["rank"] = 40
        names = {r["team_name"] for r in self.field(entry)}
        self.assertNotIn("Notre Dame", names)

    def test_bids_are_the_five_highest_ranked_champions_not_a_power_four_quota(self):
        # Two Group of Five champions rated above the Big 12's best. The format
        # takes the five highest-ranked champions, so the Big 12 misses the
        # automatic bid -- Utah is still in, but on ranking as an at-large.
        entry = _season()
        for row in entry["rankings"]:
            if row["team_name"] == "G5 Sun Belt":
                row["rank"] = 6.5
            if row["team_name"] == "G5 American Athletic":
                row["rank"] = 7.5
        field = self.field(entry)
        bids = {r["team_name"]: r["cfp_bid"] for r in field}
        self.assertEqual(bids["G5 Sun Belt"], "champion")
        self.assertEqual(bids["G5 American Athletic"], "champion")
        self.assertEqual(bids["Utah"], "at-large")

    def test_bracket_paths_pair_the_byes_with_the_right_winners(self):
        rounds = build_cfb_snapshot.cfp_bracket(_season())
        first, quarters = rounds[0]["matches"], rounds[1]["matches"]
        self.assertEqual([(m["home_slot"], m["away_slot"]) for m in first],
                         [("5", "12"), ("6", "11"), ("7", "10"), ("8", "9")])
        self.assertEqual([(m["home_slot"], m["away_slot"]) for m in quarters],
                         [("1", "8/9"), ("2", "7/10"), ("3", "6/11"), ("4", "5/12")])
        for rnd in rounds:
            self.assertIn("projected", rnd["round"])

    def test_a_short_table_produces_no_bracket_rather_than_a_partial_one(self):
        self.assertEqual(build_cfb_snapshot.cfp_bracket(_entry([_row(1, "A", "SEC")])), [])

    def test_shipped_snapshot_carries_a_group_of_five_seed(self):
        snapshot = (ROOT / "matchday-cfb-snapshot.js").read_text(encoding="utf-8")
        self.assertIn("five conference champions, seven at-large", snapshot)
        self.assertIn('"away_slot": "8/9"', snapshot)


if __name__ == "__main__":
    unittest.main()
