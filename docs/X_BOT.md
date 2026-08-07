# Matchday Terminal X bot

The bot runs after a successful data refresh and publishes at most one promotional post per day through X's official
`POST /2/tweets` API. It does not reply, follow, like, repost, mention users, or
send direct messages. Prediction posts are created only from an immutable
official receipt in Matchday Terminal's durable `picks_log*.json` ledgers. The
publisher calls the same integrity validator as postgame grading; preliminary,
legacy, quarantined, already-graded, and post-kickoff records are rejected.

When there is no eligible locked pick, the bot promotes a recap, research
article, methodology explainer, tactics guide, or the main product. A private
state ledger plus a private per-run Actions artifact prevents the same campaign from being published twice and keeps
the X post ID, time, campaign key, and a hash of the published copy for audit.
If a POST ends without a definitive response, the ledger blocks every later
campaign. After checking the Matchday Terminal X account, use the workflow's
`reconcile_key` inputs to mark the attempt `success` (with its X post ID) or
`failed`; only then can automation continue.

## Set up X

1. Create or use an X developer project and App with permission to write posts.
2. Generate OAuth 1.0a user-context credentials for the Matchday Terminal
   account.
3. Make the account transparent: its profile bio should say that it is an
   automated Matchday Terminal account and identify who operates it.
4. Add these GitHub Actions repository secrets:
   `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, and
   `X_ACCESS_TOKEN_SECRET`.
5. Run **Promote Matchday Terminal on X** manually with `dry_run` left enabled.
   Review the proposed copy in the workflow log.
6. Add the repository variable `X_BOT_ENABLED` with the exact value `true`.
   Successful refreshes can then publish, with a hard limit of one success per UTC day. A manual live run additionally
   requires turning off the `dry_run` input.

Credentials stay in GitHub Actions secrets and are used only in the publishing
step. They are never written to the repository, the state ledger, or the public
site.

## Local preview and tests

```powershell
python x_bot.py --dry-run
python -m unittest test_x_bot
```

The preview reads the tracked pick ledgers and live public article feeds and does not change the ledger. A
A live local run additionally requires the explicit `--publish` switch plus all
four credential environment variables, and should be used only from a secured
shell. Keep the cadence measured and review X's current
[Automation Rules](https://help.x.com/en/rules-and-policies/x-automation) and
[Create Post API documentation](https://docs.x.com/x-api/posts/create-post)
before changing the workflow to add interactions or increase posting frequency.
