# Matchday Terminal X bot

> **Publishing is paused.** The GitHub workflow is manual-preview-only: it has
> no automatic trigger, X credentials, or live publishing step. The code is
> retained for a future account, but it cannot post from GitHub in its current
> configuration.

The retained publisher is designed to send at most one promotional post per day
through X's official `POST /2/tweets` API when it is eventually re-enabled. It
does not reply, follow, like, repost, mention users, or send direct messages.
Prediction posts are created only from an immutable
official receipt in Matchday Terminal's durable `picks_log*.json` ledgers. The
publisher calls the same integrity validator as postgame grading; preliminary,
legacy, quarantined, already-graded, and post-kickoff records are rejected.

When there is no eligible locked pick, the bot promotes a recap, research
article, methodology explainer, tactics guide, or the main product. Its private
state ledger prevents the same campaign from being published twice and keeps
the X post ID, time, campaign key, and a hash of the published copy for audit.
If a POST ends without a definitive response, the ledger blocks later campaigns
until the account is reconciled manually.

## Set up X

1. Create or use an X developer project and App with permission to write posts.
2. Generate OAuth 1.0a user-context credentials for the Matchday Terminal
   account.
3. Make the account transparent: its profile bio should say that it is an
   automated Matchday Terminal account and identify who operates it.
4. After publishing is deliberately restored, add these GitHub Actions
   repository secrets:
   `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, and
   `X_ACCESS_TOKEN_SECRET`.
5. Run **Preview Matchday Terminal X bot (publishing paused)** manually and
   review the proposed copy in the workflow log.
6. Ask to re-enable publishing after the account and credentials are ready.
   The workflow must be deliberately restored and reviewed before it can use
   the credentials; setting a repository variable alone no longer enables it.

When publishing is eventually restored, credentials must stay in GitHub Actions
secrets and must never be written to the repository, state ledger, or public site.

## Local preview and tests

```powershell
python x_bot.py --dry-run
python -m unittest test_x_bot
```

The preview reads the tracked pick ledgers and live public article feeds and
does not change the ledger. A live local run additionally requires the explicit
`--publish` switch plus all four credential environment variables, and should
be used only from a secured shell. Keep the cadence measured and review X's
current [Automation Rules](https://help.x.com/en/rules-and-policies/x-automation)
and [Create Post API documentation](https://docs.x.com/x-api/posts/create-post)
before changing the workflow to add interactions or increase posting frequency.
