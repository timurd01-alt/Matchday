# Game archive integrity: truncated FCS names and cross-provider basketball duplicates

Date: 2026-11-12. Build 1112T. Files: `archive_backfill.py`, `archive_repair.py`,
`game_archive.py`, `fetch_data.py`, `app-1-core.js`, `archive/corrections.jsonl`.

## 1. Football: FCS opponents archived as FBS schools

**Symptom.** Rows in `archive/games/ncaaf/2026-27.csv` with `source=ncaaf`
(seeded by `archive_backfill.py --source handoff` on 2026-10-21) named an FBS school
where the opponent was FCS: "UTEP 51-10 Texas" was Texas Southern, and "BYU 63-7
Utah" was Utah Tech.

**Cause.** `source_handoff()` mapped each handoff name ("Texas Southern Tigers") to
the *longest pipeline name that is a character prefix of it*
(`trdlab_handoff._compatible`). The pipeline's name list (`data_ncaaf.json` plus
archive names) holds FBS schools only, so for an FCS team the longest prefix was the
FBS school sharing its first word. The mascot was meant to be the only thing
dropped, but nothing checked that the remainder was a mascot.

**Fix.** `handoff_name_map()` now matches whole words only, and rejects a match when
the next word is a school qualifier (`State`, `Tech`, `A&M`, `A&T`, `Southern`,
`Central`, `Christian`, …), starts with `(` ("Miami (OH)"), or is hyphenated
("Arkansas-Pine Bluff"). As a backstop, if two handoff names would still land on the
same pipeline name, both keep their full handoff names: a long name costs only
looks, while a guessed one records a game that never happened. A name with no fitting
pipeline name keeps its full handoff form, as before.

**Repair.** `python archive_repair.py names --handoff <2026-10-21 handoff> --handoff
trdlab_picks.json`. The 10-21 handoff (`git show 4024eac:betbetter_picks.json`) is the
exact input that seeded the rows. The current handoff no longer carries 85 of the
early games, and where both carry a game they agree. 473 rows checked, **15
corrected, 0 skipped, 0 score changes** (diffed column by column against the pre-repair
file). Each change is in `archive/corrections.jsonl` (`kind: team_name_correction`,
before/after/handoff names/score):

| game | was | is |
|---|---|---|
| Missouri 54-14 | Arkansas | Arkansas-Pine Bluff Golden Lions |
| Purdue 44-19 | Indiana | Indiana State Sycamores |
| Georgia State 59-10 | North Carolina | North Carolina A&T Aggies |
| Georgia 63-3 | Tennessee | Tennessee State Tigers |
| Rice 31-3 | Houston | Houston Christian Huskies |
| Louisiana Tech 80-6 | Northwestern | Northwestern State Demons |
| BYU 63-7 | Utah | Utah Tech Trailblazers |
| Miami 77-7 | Florida | Florida A&M Rattlers |
| Troy 34-17 | Alabama | Alabama State Hornets |
| Northern Illinois 24-28 | Illinois | Illinois State Redbirds |
| UTEP 51-10 | Texas | Texas Southern Tigers |
| South Florida 59-17 | Delaware | Delaware State Hornets |
| East Carolina 42-9 | North Carolina | North Carolina Central Eagles |
| North Texas 63-14 | Houston | Houston Christian Huskies |
| Florida Atlantic 66-10 | Texas | Texas Southern Tigers |

Before release, the old and new mappings were compared over every football name in
both handoffs. The only differences were these truncations. One false positive
appeared on the way: "North Carolina A&T" first collided with the Tar Heels, which is
why `at` is on the qualifier list.

With the rows fixed, the Results tab's archive merge (`seasonFinalMatches`) is no
longer limited to basketball. Against production's `data_ncaaf.json` it adds the 651
earlier-season finals to the feed's 40.

## 2. Basketball: 308 games stored twice

**Symptom.** `archive/games/ncaam/2026-27.csv` held 937 rows: 414 `source=cbbd`
(ids like `ncaam-377909`) and 523 `source=ncaam` (ids like `ncaam-401920982`).

**Cause, three parts.**
1. The handoff's event ids are **ESPN's**. For football, CFBD uses ESPN's ids
   (212 of 218 pipeline football rows share an id with the handoff), so the
   docstring's claim that "its event ids are CFBD/CBBD ids" held for football only.
   CBBD numbers games itself, so no handoff NCAAM row could ever dedupe.
2. The handoff rows were labelled `ncaam`, which `canonical_source()` aliases to
   `cbbd`. That is right for the CBBD college bundle, which uses the same label (all
   of 2025-26), but wrong for ESPN ids. So `resolve_overlaps()` saw one provider.
3. Even with correct labels it would have resolved nothing. The hourly CI step runs
   `--source handoff` alone, and `resolve_overlaps()` only compared the rows of
   that one run, never what the season already held.

The duplicates had a source too. `record_build()` archived only the display window,
and `fetch_data` keeps the **40 newest** finals there. On opening night (115 of the
ESPN-only games are dated 2026-11-03) most of the slate never reached the archive
under CBBD ids, which is the gap the handoff backfill was papering over.

**Fix.**
- `source_handoff()` is football-only (`HANDOFF_COMPETITIONS`).
- `resolve_overlaps(rows, archived)` counts the season's on-disk providers when it
  picks a winner, and returns only the incoming rows of that winner.
- `fetch_data.fetch_college_bundle()` keeps the full fetched season on the adapter
  (`_season_matches`), and `build()` passes it to `record_build()`. This costs zero
  provider calls, because the season bundle is already fetched for standings and
  training.
- `game_archive.cross_id_duplicates()`, wired into `validate()`, reports a game
  stored under two ids: same final in the same orientation, kickoffs within 36h,
  and one side's name matching word for word. Labels alone could not catch it.
  Against the pre-repair archive it reported exactly the 308 NCAAM 2026-27 pairs,
  and nothing among the 691 football or 6,299 NCAAM 2025-26 games.
- `normalize_match()` refuses a 0-0 college "final". CBBD has reported two unplayed
  games as FINISHED 0-0, and once archived, a placeholder blocks the real score as
  a "revision". Widening the hook to the whole season would have let more in.

**Repair.** `python archive_repair.py foreign-ids --handoff trdlab_picks.json`
removed the **523** handoff-id rows. **308** had a CBBD twin; **215** had none (the
games the 40-game window missed). Each removed row is logged in full in
`archive/corrections.jsonl` (`kind: foreign_id_row_removed`, with `pipeline_twin`),
so any of them can be restored. After repair the file holds 414 rows, all `cbbd`,
and the duplicate count is 0.

**Open check: the 215 games.** The hook now archives the whole fetched season, so
the next scheduled (non-push) deploy run should re-record those games under CBBD ids
from the season bundle. The bundle already supplies the CBBD finals archived every
hour, so this is expected but not yet seen. Confirm after the next hourly commit
with `grep -c ',cbbd,' archive/games/ncaam/2026-27.csv`, which should rise from
414 toward ~630. Until then, basketball Results lacks those early-November games.

## Not fixed here (follow-ups)

- Two CBBD rows already archived as 0-0 finals: `ncaam-374807` (Alabama State v
  Georgia College, 2026-11-10) and `ncaam-372765` (South Carolina Beaufort v Nevada,
  2026-11-12). They will block the real scores, which `upsert_games` refuses as
  revisions. They need the same logged removal.
- FCS teams now appear under full handoff names ("Texas Southern Tigers"), while
  CFBD rows for the same school use the short form. That is correct but
  inconsistent, so team form for an FCS team can split across two spellings.
