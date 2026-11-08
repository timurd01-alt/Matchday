# Social publishing (X and TikTok)

`.github/workflows/social-post.yml` runs once per posting slot. Each run
builds the content queue, renders the studio PNGs and the one TikTok video it
plans to send, then hands them to `social_publish.py`. **By default nothing is
sent**: every run prints a dry run of the one post each platform would make.
(`social-graphics.yml` still renders the full weekly set on Sunday and Tuesday
as a downloadable artifact; it posts nothing.)

| | X | TikTok |
|---|---|---|
| What is sent | One post per content item, with its studio graphic when there is one; the Top 25 gets the full list as replies | One video per item, to the account's **inbox as a draft** |
| Goes public | Immediately | Only when a person opens TikTok, adds a sound and posts |
| Pace | 1 per run, ≥3 h apart, ≤3 per 24 h | 1 per run, ≥1 h apart, ≤3 per 24 h (TikTok allows 5 pending drafts) |
| Ledger | `social/ledger_x.jsonl` | `social/ledger_tiktok.jsonl` |

## The weekly schedule

Slots are in US Eastern time (`social_schedule.py`); the cron times sit inside
them in both EST and EDT, with room for GitHub's usual start delay.

| When (Eastern) | Runs | Posts first |
|---|---|---|
| Sunday 18:00–24:00 | ~18:45 and ~23:00 | New power Top 25, then the ballot |
| Monday 11:00–17:00 | ~12:00 and ~15:15 | Ballot, Top 25, bracketology |
| Tuesday 11:00–17:00 | ~12:00 and ~15:15 | The receipts: scorecards, last week's upset calls |
| Wednesday 11:00–17:00 | ~12:00 and ~15:15 | Research articles, basketball Top 25, bracketology |
| Thursday 11:00–17:00 | ~12:00 and ~15:15 | The weekend slate, Upset Watch |
| Friday 11:00–17:00 | ~12:00 and ~15:15 | Game of the Week, Upset Watch |
| Saturday 08:00–13:00 | ~9:30 | Upset Watch before the first kickoff |

(Times shown are EST; add an hour in daylight time.) A slot posts its own
kinds first. Anything that would expire before its next slot is **urgent**
and may go in any slot, so a Monday upset pick does not wait for Thursday.
Off-season weeks produce no items and so no posts. Bracketology posts begin
once the projection leaves its early phase. A manual run of the workflow can
tick *ignore schedule* to post outside the slots; the caps still apply.

## Turning it on

1. **Kill switch.** Repository → Settings → Secrets and variables → Actions →
   *Variables*: set `SOCIAL_PUBLISHING` to `on`. Any other value (or none)
   means dry run. Setting it back to `off` stops the next run.
2. **X.** In the X developer portal, give the app *Read and write*
   permission, then generate the access token and secret **for the Matchday
   account**. Add four repository secrets:
   `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`.
   The X docs do not state whether the v2 media endpoints accept OAuth 1.0a,
   so the first live run is the confirmation: if the image upload is refused
   while text posts work, that is the cause.
3. **TikTok.** Create an app at developers.tiktok.com with Login Kit and the
   Content Posting API, request the `video.upload` scope (TikTok must approve
   it), and register a redirect URI. Add `TIKTOK_CLIENT_KEY` and
   `TIKTOK_CLIENT_SECRET` as secrets, then on your own machine:

   ```bash
   python social_publish.py tiktok-auth --redirect-uri https://YOUR-REDIRECT
   ```

   Open the printed URL signed in as the Matchday TikTok account, approve,
   copy `code` from the redirect, and run it again with `--code CODE`. That
   writes `.tiktok_token.json` (gitignored). Store the token value once as
   the `TIKTOK_REFRESH_TOKEN` secret.

   TikTok replaces the refresh token on **every** use and invalidates the old
   one, so CI must be able to write the new one back. Add a fine-grained
   personal access token for this repository with *Secrets: read and write*
   as the secret `SOCIAL_SECRETS_PAT`. Without it the TikTok step stays a dry
   run rather than refreshing a token it could not save.

## When a run reports an unknown outcome

A request that times out may still have posted. The ledger marks it
`ambiguous` and that platform sends nothing more until someone checks the
account and records what happened:

```bash
python social_publish.py x --resolve KEY --resolution success --post-id 1234567890
python social_publish.py x --resolve KEY --resolution failed
```

Commit the updated ledger to `main`.

## Running locally

```bash
python render_social.py --out out/graphics
python render_reels.py --out out/videos
python social_publish.py x --graphics out/graphics
python social_publish.py tiktok --videos out/videos
```

Add `--publish` to send. Locally the TikTok token lives in
`.tiktok_token.json`; do not use the same TikTok token in CI and locally, as
whichever refreshes second will find the other's token dead.
