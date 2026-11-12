# Website design review (2026-11-11)

**Status:** review only, nothing changed. Live site, Build 1111C.
**Method:** every tab opened in the browser for both sports at 1700x950, and football at 375x812 and 820x1000. A script read each tab's fonts, text sizes, section-label styles, truncation, overflow and tap-target sizes; Research blocks were measured for height and bottom gap. Checked against the owner's rules: one font per role, no intro sentences or boxed intros, lime for interface and green for results, long lists behind "View all" or tabs, no dead space.

## What holds up
- Three typefaces, each tied to a role on all ten tabs: Barlow Condensed for titles, JetBrains Mono for labels and numbers, Inter for names and body.
- No boxed `.banner` intros anywhere. No page-level horizontal overflow at any width.
- Research: all 12 blocks have the 21px bottom gap; paired blocks match in height (one pair is 522 vs 526).
- Scorecard and Research have a clear reading order. Home works well on a phone.

## Findings, most important first
1. **Phone Rankings shows no numbers.** At 375px the table keeps rank, move and team; Rating, Conference, SoS, Off, Def and Record are all hidden, with no sideways scroll.
2. **Conference Standings shows zeros as if they were data.** PF, PA and Diff read 0 for most teams (Miami 8-1: 0, 0, 0) and real values for a few (Louisville 367, 233, 134). "Overall 8-1" is repeated by separate P, W, L columns.
3. **Standings is one very long page.** Every conference is stacked: 7,245px for football, 19,359px for basketball (32 conferences). The rule is long lists behind "View all" and related views behind tabs.
4. **Results leads with games that have no result.** The top row is four games marked "past kickoff" with no score (Tuesday's games), above the finished ones.
5. **Home and Research disagree about the same things.** Home's featured game is LSU-Texas; Research's is USC-Indiana. UCLA-Illinois is "-11.4 pts" in red on Home and "+11.3" in green on Research, the same gap from opposite sides.
6. **Intro sentences under titles**, which the rules say not to have: Home ("What matters now, before you choose where to go deeper."), Games (inside a boxed header with a lime bar), Learn, Rankings, Standings, the football bracket and Pick 'Em. Home, Games, Learn and both bracket tabs also lack the right-hand uppercase descriptor the other tabs carry.
7. **Very small text.** 9.7px and 8.1px are used heavily: desktop Games has 214 text elements at 9.7px and 40 at 8.1px; on a phone 265 of its 509 text elements are under 11px. Any fix has to be scoped, not a change to the type scale.
8. **Section labels are not one style.** 10px on Rankings and Pick 'Em, 11px on Research and Scorecard; the football bracket sets one in Inter; Bracketology headings use a gold accent (rgb 214,189,128) that is outside the lime and green roles.
9. **Phone details.** A stray "N" sits in the top strip on every page (the "Next ..." line cut to one letter). Games filter chips are 27px tall (46 of 87 tap targets under 40px). "Methodology" is a 14px-tall link on Research and Scorecard. The day header's game count is clipped at the right edge.
10. **Pick 'Em reads as empty.** Every row says "no picks yet", the leaderboard says nobody has 10 graded picks, and the "Pick" links appear blue, not lime.
11. **Clipped names at desktop.** The sidebar reads "Conferen..."; Bracketology cards truncate team names (St. John's Red Storm, Alabama Crimson Tide, Michigan State Spartans and others).
12. Basketball Games: several cards read "No published pregame forecast" (non-Division I opponents); the top strip's next-game ticker was cut mid-word ("UI v LU(").

## Not covered
- The match window, team pages, account screens and the welcome page beyond a glance.
- Basketball at phone width.
- Contrast ratios and focus order. `ui_audit.py` ran but wrote no report in this checkout, so the automated accessibility findings are not included.

## Applied 2026-11-11: findings 1, 2, 4 and 5 (Build 1111D, commit 39f8864)
- **1, phone Rankings.** Rating and Record stay visible at 375px (`styles.css`, the `.powerTable` phone rules). Columns measure 40 / 44 / 166 / 58 / 46px with no sideways overflow. Nine of the top 25 names now end in an ellipsis ("Notre Dame Fig...").
- **2, Standings.** P, W and L are gone for college tables; PF, PA and Diff appear only when every team that has played has them (`_collegeTable`, `_tableLacksPoints` in `app-3-panels.js`). Today that hides them in all 11 football tables. The cause of the zeros, team names not matching the results ledger, is not fixed.
- **4, Results.** Finished games first; games past kickoff without a final follow under "Awaiting final score" (`renderResults` in `app-1-core.js`).
- **5, Home vs Research.** Research's Featured Read now takes the engine's game of the week, as Home does (`featuredPick` in `app-2-views.js`). Home's largest-differences list states each gap from the side the model rates above the market (`gamesDifferencesHTML`), matching Research's Model-Market Watch. The two can still differ by a few tenths (35.2% vs 35.9% for Illinois) because Home reads the hourly payload and Research reads the weekly handoff.
- Checked in the browser at 1700px and 375px with live data; Research blocks kept their 21px gaps. Findings 3 and 6 to 12 are untouched.
