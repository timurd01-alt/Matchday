# Prediction Lifecycle

Matchday's public record has three phases: **pregame analysis**, **result pending**, and **postgame grading**.

## 1. Pregame analysis and lock

Upcoming fixtures first receive a **preliminary forecast**. Matchday refreshes sport-native late information—such as MLB starters, NBA starting lineups, NFL availability, soccer XIs, hockey goalies, weather, and the near-kickoff market—where an authorized provider actually supplies it. The official pick is written to the durable ledger inside a sport-aware lock window: two hours for pro sports and soccer, three hours for college sports.

The readiness receipt records every required input as confirmed, available, or missing, along with provenance and coverage. Missing data is not converted into a neutral observation. Newly collected personnel, workload, and venue context stays at zero production weight until prospective evaluation clears the existing promotion gates.

A missing betting market does not prevent the independent model pick from locking. If valid odds arrive after the lock but before kickoff, Matchday may backfill market-comparison fields such as the market pick or model-market gap. It cannot change the locked side or confidence.

## 2. Result pending

After kickoff, the pick stays frozen. Matchday does not attempt to provide minute-by-minute clocks, live score alerts, or sub-minute refreshes. An in-progress fixture is labeled **Result pending** while the hourly pipeline waits for a provider-confirmed final result.

This phase can last longer when a provider is delayed, a game is suspended, or an event identity needs reconciliation. Waiting is preferable to grading an unofficial or mismatched score.

## 3. Postgame grading

Only a final result grades a verified locked prediction. The graded record includes the actual outcome and whether the model hit. Knockout advancement and regulation-time betting markets can use different settlement rules; Matchday preserves that distinction rather than forcing one result definition onto both.

The pipeline verifies that every expected lock and grade was actually written back to disk. If persistence fails, the fetch fails closed instead of publishing a successful-looking dataset with missing accountability records.

## Public guarantees

- The selected side and confidence are immutable after the verified lock.
- A computed prediction is not counted as a public pick unless the lock exists in the durable ledger.
- A finished game is not counted as graded until the result and hit/miss fields persist.
- Historical provider corrections may update official result facts, but they do not rewrite the original pick.
- Every new verified record freezes the lock window, published probabilities, and match-level pregame readiness/input snapshot used for that competition. Mutable global model state such as Elo, H2H history, and ratings artifacts is identified but is not yet fully embedded for byte-for-byte reruns. Older verified 12-hour records remain valid under their original boundary.
- Auto-generated recaps require both a verified pregame lock and a final grade.

These guarantees are covered by the lock-persistence, score-refresh, recovery, and analysis-mode regression tests documented in [Development and Testing](Development-and-Testing).
