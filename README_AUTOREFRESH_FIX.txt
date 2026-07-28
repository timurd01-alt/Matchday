Matchday refresh and integrity notes
====================================

Matchday now operates as a pregame/postgame analysis product, not a live-score
terminal.

- Production fetches are scheduled hourly.
- Picks become eligible for a verified lock inside 12 hours of kickoff.
- A locked pick's side and confidence are immutable.
- In-progress fixtures are displayed as "Result pending."
- Only official final results grade the locked ledger.
- Lock and grading persistence are verified before a successful fetch completes.
- Pregame odds are requested only close to kickoff and cached to conserve quota.
- News older than seven days, or without a usable publication date, is rejected.

Run one adaptive all-sport fetch:

    python multi_fetch.py --once

Run the local scheduler:

    python multi_fetch.py

Run the integrity regression suite shown in SETUP.md before deploying changes.
