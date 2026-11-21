# Tab-switch lag (2026-11-21, Build 1121F)

**Status:** shipped in 1121F.
**Question:** why do tab switches still lag after 1114/1115 (view reuse, parked views), and what does it take to make them instant?

## Method
Click-to-painted-frame per nav tab (click, then the next `requestAnimationFrame` with its style and layout forced), in headless Edge through Playwright. The baseline was `main` at 226788e, served side by side with the branch on the same `data_*.json`. Runs covered 1700px, 1150px and 390px, both sports, at normal speed and with the CPU slowed 4×. The scripts were throwaway (scratchpad), not committed.

The Claude desktop browser pane is unsuitable for frame timing while it is hidden, because `requestAnimationFrame` is throttled there. It also overstates the restyle cost of `history.pushState` compared with real Edge.

## Findings
1. **The entrance animation was the largest cost.** `playViewEntrance()` called `getAnimations()`/`animate()` on every card. That forced the newly shown view's style to resolve inside the click: 370-600ms on each return to Games or Results. Even when cheap, it kept the view half-faded for ~325ms. Removed, together with the `meterReveal` bar growth that replayed on every build.
2. **First visits were built inside the click:** Rankings 330ms (football) and 1.7s (basketball), Research ~300ms, Results ~200ms. Views that don't measure their own layout are now built during idle time into their parked host. Each one is then laid out once in a separate idle slice (unparked as an absolutely positioned box for one task, never painted), so the first showing reuses that layout. Games is built ahead too, and its height-fitting step runs at that layout pass or at first show. Home and the bracket measure throughout their build and are still built on visit.
3. **Stale views were rebuilt before showing.** A view past its 60s or 10-minute stamp, or after any storage write, used to be rebuilt synchronously. It is now shown as it stands and rebuilt right after it paints. A view built for the other sport or language is never shown that way.
4. **`ratingWeekGames()` was O(teams × results × picks).** It was called twice per row of the ratings table, scanning every result and re-splitting every pick's event name with a regex. That cost ~800ms of a basketball Rankings build. It is now indexed once per table edition, with the same match test in the same order. Verified identical output for all 497 rows of both tables (762 games, 703 chances).
5. **Any `pushState`, even to the same URL, makes Chromium restyle the document.** In the pane this was 40-80ms per unpark. In real Edge it was ~10-30ms at 4× CPU. The URL update now runs after the new view paints.

## Results (click to painted frame, ms)
| Run | `main` first visit (worst) | 1121F first visit (worst) | `main` return (worst) | 1121F return (worst) |
|---|---|---|---|---|
| 1700px football | 256 (Rankings) | 34 | 103 | 42 |
| 1700px basketball | 967 (Rankings) | 31 | 174 | 18 |
| 390px football, 4× CPU | 2294 (Rankings) | 64 | 355 | 112 |
| 390px basketball, 4× CPU | 8184 (Rankings) | 88 | 103 | 184 |

The median return is 5-6ms on desktop. At 4× CPU the return median is ~60ms, made up of frame wait plus the restyle after the URL update. Games layout (cards, heights, both sports, 1700/1150) and back/forward behaviour are identical to `main`.

## Left as is
- The longest background slices are Research's build (~200ms cold) and its layout pass (~210ms) on desktop. A tap that lands inside one waits for it. That cost used to be paid in every first click.
- Home and the bracket are still built on visit (~30-40ms desktop).
