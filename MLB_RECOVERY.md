# MLB forecast recovery contract

MLB fixture forecasts remain paused until both the model-evidence gate and the
personnel-data gate pass independent review.  Research forecasts may continue
to run at zero production weight, but they must never enter the official picks
log, public API forecast fields, alerts, Outcome Tree, or social candidates.

**Current state (2026-08-23): publication resumed on the incumbent route.**  The
deployed `v6-calibrated` forecast publishes at zero challenger weight and zero
personnel weight under §2b and §3.  The run-strength challenger remains
unpromoted and subject to §2 in full.

## 1. Frozen research evidence

At the normal two-hour MLB lock boundary, Matchday records at most one
tamper-evident research lock per fixture and model artifact.  The lock must be
strictly before first pitch and freeze:

- fixture, teams, scheduled first pitch, and observation/lock timestamps;
- the independent incumbent, league/home prior, challenger, and lock-time
  no-vig market probabilities when each is available;
- challenger model version, artifact SHA-256, feature schema, training cutoff,
  and exact zero-weight input snapshot;
- pregame readiness, source provenance, and explicit missing personnel fields.

Results are appended as separate grade events.  A grade never mutates a lock.
Replay is idempotent, duplicate or ambiguous locks fail closed, mixed model
artifacts cannot be pooled, and no observation at or after first pitch is
eligible.

## 2. Model-evidence gate

The first canary may be reviewed only after one frozen cohort reaches at least
500 paired graded games and 30 game-date blocks.  On identical fixtures:

- the exact deployable transformation, not merely its raw challenger signal,
  must improve both log loss and Brier score over the independent incumbent;
- the 95% game-date block-bootstrap interval for its paired log-loss delta must
  have an upper bound below zero;
- exclusions, daily coverage, missingness, artifact identity, and calibration
  bands must be present in the frozen report;
- a named independent reviewer must approve the exact report SHA-256.

The first reviewed canary remains capped at 10% signal weight and a maximum
three-percentage-point move, with no winner flip.  The final applied shift must
respect the cap after no-flip logic and display rounding.

These are minimum promotion controls, not a promise that passing them is enough
to resume publication.  The personnel-data gate must pass separately.

### 2a. Calibration is not a signal promotion

Correcting a probability the incumbent already emits — temperature or shrink
applied to its own independent read, with no new input and no new feature — is
a defect fix, not a model promotion, and does not pass through §2.  It changes
how confidently an existing signal is stated, not what the forecast knows.

Such a change must still: be justified by measured, held-out evidence from the
graded ledger (not an in-sample fit); move `PREDICTION_MODEL_VERSION` and
`MODEL_SIGNAL_SCHEMA` so no cohort pools mixed artifacts; and leave every sport
without its own measured evidence bit-for-bit unchanged.  It may never flip a
pick, and it may only reduce stated confidence, never inflate it.

The 500-paired-game requirement in §2 exists to stop an unproven *signal* from
moving forecasts.  Applying it to a calibration fix would keep a known-
miscalibrated number in production while the evidence to replace it accumulates,
which inverts the control's purpose.

### 2b. Publishing the incumbent is not a signal promotion

§2 governs promoting a *challenger* into production.  Publishing the already-
deployed incumbent at zero challenger weight promotes nothing: the forecast that
resumes is the same one §2 measures every challenger against.  Applying §2's
500-paired-game bar to it would withhold the baseline while waiting for evidence
about a signal that carries no weight — the same inversion §2a identifies.

Taking this route is an explicit, signed decision, not a default.  The policy
must set `model_gate.challenger_weighted` to exactly `false`, may not name a
`promotion_policy`, and is contradicted outright if any promotion policy is
approved for non-zero production weight.  A missing, malformed, or non-boolean
flag is treated as a challenger promotion and §2 applies in full.

The route still requires its own hash-bound manual review of the incumbent's
measured evidence, and it binds the exact artifact it approved:
`incumbent_model_version` and `incumbent_model_signal_schema` must match what
the build ships.  A later model version or signal schema is not what was
reviewed, and publication returns to paused until it is reviewed again.

This route approves no signal weight for any challenger, now or later, and its
evidence may never be pooled into a §2 promotion cohort.

## 3. Personnel-data gate

This gate governs personnel data that a forecast actually reads.  A model in
which every personnel feature carries zero weight is out of its scope: blocking
such a model on confirmed-starter coverage gates it on the correctness of data
it never consumes, and — with no contracted confirmed source available — makes
resumption unreachable for a reason unrelated to forecast quality.

Taking that route is an explicit, signed decision, not a default.  The policy
must set `features_weighted` to exactly `false` and carry a hash-bound
`zero_weight_attestation` that the release review binds to; it may not
simultaneously name a confirmed source.  A missing, malformed, or non-boolean
flag is treated as weighted and every requirement below applies.  The moment any
personnel feature takes non-zero weight, this gate applies in full.

BALLDONTLIE remains the fixture/result backbone.  SportsGameOdds player props
are market-derived candidates only; they cannot populate canonical lineups or
confirmed starters.  Schedule-derived bullpen rest remains a zero-weight proxy.

Before a confirmed-personnel source is enabled, Matchday must record a current
compliance review covering the contracted endpoint/tier, public derived-use and
retention rights, provenance under the ESPN exclusion, confirmed-versus-
projected semantics, provider timestamps, and verified quota headers and
reserves.  Enabling a key alone is not approval.

Operational review then requires 30 consecutive days with both exact-game
starters confirmed by the lock boundary for at least 95% of eligible games,
zero wrong-fixture or wrong-team joins in the audited sample, and no stale,
cached, projected, or market-inferred row labeled confirmed.  Doubleheaders
must join by provider game identity and scheduled time; ambiguous joins attach
nothing.  Personnel features remain zero weight until their own frozen
predictive evaluation passes.

## 4. Publication and rollback

Publication eligibility is fail closed and requires all of the following:

1. an explicitly approved, hash-bound model policy — either a §2 challenger
   promotion or a §2b incumbent-only approval;
2. either an explicitly approved personnel-source policy with a completed
   coverage audit, or a signed zero-weight attestation under §3;
3. a deliberate production switch naming both approvals;
4. a lock receipt containing the policy/evidence hashes and pregame readiness.

Historical MLB locks and grades are immutable.  Rolling back publication must
restore the pause without rewriting any receipt.

