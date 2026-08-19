# MLB personnel weight: verification evidence

Prepared 2026-08-19. **This is a findings document, not an attestation.** It
records what was verified and by what method, so that a reviewer can check the
claim rather than take it on trust. It carries no reviewer, no decision, and no
signature; those are the owner's to add.

## Why it exists

`mlb_recovery_policy.json`'s personnel gate offers an alternative route:

> Set `features_weighted=false` and supply a signed `zero_weight_attestation`
> to publish a model that reads no personnel data; the coverage requirements
> below then do not apply.

That route is only honest if the claim is true. This is the check.

## Method

Every occurrence of `personnel` in the production fetch/model path was located
and classified by role (`grep -n "personnel" fetch_data.py`), then each site
was read to determine whether it can influence a published probability.

## Finding

Personnel data appears in three roles. None of them weights a forecast.

**1. Upset-promotion gate — `fetch_data.py:2225-2236`.** For MLB,
`starting_pitchers_confirmed` sets `personnel_gate`, which is ANDed into
`base_trigger` alongside the market and evidence gates. Its only possible
effect is to withhold an upset pick that would otherwise have been promoted.
It is strictly one-directional: it can block a selection, never create,
strengthen, or reweight one.

**2. Display and provenance — `fetch_data.py:1570-1588`.** The class/personnel
comparison and its `depth_chart` reading are descriptive output shown to
readers, and report "No verified sport-specific personnel source is
configured" when absent.

**3. Persistence plumbing — `fetch_data.py:2941, 2955, 3361`.** `personnel` is
carried in the preserved-context key list and restored across runs so a live
overlay refresh cannot drop it. Movement of a field, not use of it.

No site was found where a personnel value enters a probability computation.

## What this does and does not support

**Supported:** MLB's published probabilities carry zero personnel weight.

**NOT supported:** the literal words "reads no personnel data". The published
*selection* does consult `starting_pitchers_confirmed` at the upset gate. An
attestation worded as "reads no personnel data" would be inaccurate, even
though the substance of the zero-weight claim holds.

An accurate wording would be, in substance:

> Personnel data carries zero weight in the MLB forecast. It is consulted only
> as a one-directional safety gate that can withhold an upset promotion, and
> can never influence a probability, create a selection, or strengthen one.

## Open question for the reviewer

Whether a gate that can only ever *withhold* a pick counts as the policy's
"reads no personnel data" is a governance judgement, not a code fact, and is
deliberately left undecided here. Both readings are defensible: the gate makes
published output depend on personnel confirmation, and it does so only in the
conservative direction the gate exists to enforce.

Note also that this route clears three of the six reasons currently returned by
`mlb_recovery.publication_decision()`. `model_evidence_not_approved` and
`release_review_not_approved` are unaffected by it, so MLB forecasts remain
paused either way.
