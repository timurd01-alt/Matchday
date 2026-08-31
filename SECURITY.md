# Matchday Security — the plain-English version

You don't code, so this explains what matters in normal words. There are only a
few real risks, and the app now protects you from most of them automatically.

## The one habit that matters most
**Never paste an API key into a chat, email, or any file except `config_keys.py`.**
Your keys are like house keys. `config_keys.py` is the only place they belong, it
never leaves your computer, and it's excluded from everything the app shares.

## Before you ever put this online or send the folder to anyone
Double-click **`scripts\windows\check_security.bat`** and read the report.
- Green "All clear" = safe to share.
- "[STOP]" = it found something unsafe and tells you exactly what and how to fix it.
Run it every single time before publishing. It changes nothing — it only checks.

## What's already protected for you
- **Your keys** live only in `config_keys.py`. Every file the app packages up for
  sharing leaves that file out.
- **`.gitignore`** stops credentials, private odds snapshots, and provider caches
  from being uploaded. The public model pick ledger is intentionally versioned
  and contains no community device identifiers.
- **The code masks every configured provider key** in diagnostics, including
  credentials carried in provider URLs.
- **The public leaderboard never trusts browser-supplied totals.** Picks are
  locked by the server before kickoff and graded there from published finals.

## The three real risks, ranked
1. **A key leaking.** Handled: keys stay in `config_keys.py`; the security check
   catches accidents. Your one job: if a key ever appears anywhere else, treat it
   as compromised and regenerate it (see ROTATE_KEYS.md — takes 10 minutes).
2. **Publishing secrets by accident.** Handled by `.gitignore` + the security check.
   Just run the check before publishing.
3. **The online leaderboard being abused.** The server locks individual picks,
   derives totals itself, validates identifiers and request sizes, and applies a
   PostgreSQL-backed limit shared across serverless instances.

## What you do NOT need to worry about right now
- Password storage: Matchday has no user accounts or passwords.
- Raw device identifiers appearing on the public board: only assigned handles
  and derived records are returned.
- Viruses in the app: it's your own code plus public sports data.

## If something ever feels wrong
Regenerating keys is free and takes minutes — when in doubt, rotate (ROTATE_KEYS.md).
That single action fixes almost any key-related scare.
