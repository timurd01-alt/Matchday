# Matchday Security — the plain-English version

You don't code, so this explains what matters in normal words. There are only a
few real risks, and the app now protects you from most of them automatically.

## The one habit that matters most
**Never paste an API key into a chat, email, or any file except `config_keys.py`.**
Your keys are like house keys. `config_keys.py` is the only place they belong, it
never leaves your computer, and it's excluded from everything the app shares.

## Before you ever put this online or send the folder to anyone
Double-click **`check_security.bat`** and read the report.
- Green "All clear" = safe to share.
- "[STOP]" = it found something unsafe and tells you exactly what and how to fix it.
Run it every single time before publishing. It changes nothing — it only checks.

## What's already protected for you
- **Your keys** live only in `config_keys.py`. Every file the app packages up for
  sharing leaves that file out.
- **`.gitignore`** stops your keys, your pick history, and your odds logs from ever
  being uploaded if you put the project on GitHub.
- **The code masks keys** in any error messages, so a screenshot of an error can't
  leak them.

## The three real risks, ranked
1. **A key leaking.** Handled: keys stay in `config_keys.py`; the security check
   catches accidents. Your one job: if a key ever appears anywhere else, treat it
   as compromised and regenerate it (see ROTATE_KEYS.md — takes 10 minutes).
2. **Publishing secrets by accident.** Handled by `.gitignore` + the security check.
   Just run the check before publishing.
3. **The online leaderboard being abused (only once you deploy it).** The server
   code already has guards (rejects fake records, limits how often anyone can post,
   hides tiny samples). Nothing to do until you deploy Tier 2.

## What you do NOT need to worry about right now
- Hackers breaking into the app: it runs only on your computer; there's no public
  door to break into yet.
- Passwords/user data: the app has no logins and stores no one else's data.
- Viruses in the app: it's your own code plus public sports data.

## If something ever feels wrong
Regenerating keys is free and takes minutes — when in doubt, rotate (ROTATE_KEYS.md).
That single action fixes almost any key-related scare.
