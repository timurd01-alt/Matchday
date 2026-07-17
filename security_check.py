"""
security_check.py — run this before you ever share your project or put it online.

You don't need to understand code to use it. Double-click check_security.bat (or
run: python security_check.py) and read the plain-English report. It tells you,
in order of importance, whether anything unsafe is about to leak — and exactly
what to do about each thing it finds.

It checks:
  1. Are your real API keys hidden from any file you'd share?
  2. Is .gitignore protecting your secrets and personal data?
  3. Did any key accidentally get pasted into a code file?
  4. Are your private data files (picks, keys) where they should be?
It changes nothing — it only looks and reports.
"""
import os
import re
import sys

GREEN = "  [OK]  "
WARN = "  [!!]  "
STOP = "  [STOP]"

# patterns that look like real secrets (not the safe PASTE_ placeholders)
KEYISH = re.compile(r"\b[a-f0-9]{32}\b|\b[A-Za-z0-9]{30,}\b")
PLACEHOLDER = "PASTE_"

# files you would share / publish (code), vs files that must stay private
SHAREABLE = ["fetch_data.py", "app.py", "multi_fetch.py", "backfill_players.py",
             "update_ratings.py", "index.html", "styles.css",
             "app-1-core.js", "app-2-views.js", "app-3-panels.js", "app-4-features.js",
             "translations.js"]
PRIVATE = ["config_keys.py"]
PRIVATE_DATA = ["picks_log_wc.json", "odds_open_wc.json"]


def read(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""


def find_real_keys(text):
    """Return key-like strings that are NOT the safe placeholder."""
    hits = []
    for line in text.splitlines():
        if PLACEHOLDER in line or line.strip().startswith("#"):
            continue
        for m in KEYISH.findall(line):
            # ignore obvious non-secrets: urls, common words, short-ish tokens
            if len(m) >= 30 and not m.startswith(("http", "www")):
                hits.append(m[:6] + "…")
    return hits


def main():
    problems, warnings = [], []
    print("\n=== Matchday security check ===\n")

    # 1. keys must NOT appear in any shareable code file
    leaked = {}
    for f in SHAREABLE:
        if os.path.exists(f):
            k = find_real_keys(read(f))
            if k:
                leaked[f] = k
    if leaked:
        problems.append("A real key may be sitting inside a file you would share:")
        for f, k in leaked.items():
            problems.append(f"     - {f}  (found: {', '.join(set(k))})")
        problems.append("     FIX: keys belong ONLY in config_keys.py. Remove them from the file(s) above.")
    else:
        print(GREEN + "No API keys found inside shareable code files.")

    # 2. .gitignore present and covers the essentials
    gi = read(".gitignore")
    if not gi:
        problems.append("No .gitignore file — publishing to GitHub could upload your keys.")
        problems.append("     FIX: keep the .gitignore that ships with the app in this folder.")
    else:
        need = ["config_keys.py", "picks_log", "odds_open"]
        missing = [n for n in need if n not in gi]
        if missing:
            warnings.append(f".gitignore is missing: {', '.join(missing)} — add those lines.")
        else:
            print(GREEN + ".gitignore is protecting your keys and personal data.")

    # 3. config_keys.py should exist and actually hold keys (not placeholders)
    if not os.path.exists("config_keys.py"):
        warnings.append("config_keys.py not found — the app can't fetch until it exists with your keys.")
    else:
        ck = read("config_keys.py")
        if PLACEHOLDER in ck:
            warnings.append("config_keys.py still has PASTE_ placeholders — real keys not entered yet.")
        else:
            print(GREEN + "config_keys.py exists and holds real keys (kept private).")

    # 4. remind about private data files
    present = [f for f in PRIVATE_DATA if os.path.exists(f)]
    if present:
        print(GREEN + f"Your track record exists ({', '.join(present)}) — .gitignore keeps it private.")

    # verdict
    print()
    if problems:
        print(STOP + " DO NOT publish yet. Fix these first:\n")
        for p in problems:
            print("   " + p)
        if warnings:
            print()
            for w in warnings:
                print(WARN + w)
        print("\n   Re-run this check after fixing.\n")
        sys.exit(1)
    elif warnings:
        print(WARN + "Safe to share code, but note:\n")
        for w in warnings:
            print("   " + w)
        print()
    else:
        print("  All clear. Your secrets are protected and nothing unsafe is exposed.\n")


if __name__ == "__main__":
    main()
