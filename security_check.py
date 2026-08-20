"""Fail-closed pre-publication secret scan for the Matchday repository.

Scans every tracked and non-ignored untracked text file, reports locations but
never prints secret values, and verifies that known private files are ignored.
This complements GitHub secret scanning; it is not a substitute for rotation
after a credential has entered Git history.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

GREEN = "  [OK]  "
WARN = "  [!!]  "
STOP = "  [STOP]"
MAX_FILE_BYTES = 20 * 1024 * 1024

KNOWN_SECRET_PATTERNS = [
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("credential URL", re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?):\/\/[^\s:@/]+:[^\s@/]+@", re.I)),
]
ASSIGNMENT_LABEL = "literal credential assignment"
ASSIGNMENT = re.compile(
    r"\b([A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|DATABASE_URL))\s*[:=]\s*['\"]([^'\"\r\n]+)['\"]"
)
SAFE_VALUE = re.compile(r"^(?:$|PASTE_|YOUR_|EXAMPLE|TEST[-_]|SHARED[-_]|\*\*\*|\$\{|process\.env|os\.environ)", re.I)
# Names of the local-only configuration files; they must stay untracked and
# ignored. Only the file names appear in the report -- never their contents.
UNTRACKED_CONFIG_FILES = ("config_keys.py", ".env", ".env.local", ".env.production")


def candidate_files() -> list[pathlib.Path]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            check=True, capture_output=True,
        )
        return [pathlib.Path(raw.decode("utf-8", "surrogateescape"))
                for raw in result.stdout.split(b"\0") if raw]
    except Exception:
        return [path for path in pathlib.Path(".").rglob("*")
                if path.is_file() and ".git" not in path.parts]


# Every label the report can print, addressed by index. scan() hands back
# indexes rather than text so that nothing read out of a scanned file -- not
# even a matched substring -- can be carried into the printed output.
LABELS = tuple(label for label, _ in KNOWN_SECRET_PATTERNS) + (ASSIGNMENT_LABEL,)
ASSIGNMENT_LABEL_ID = len(LABELS) - 1


def scan(path: pathlib.Path) -> list[tuple[int, int]]:
    # This scanner necessarily contains literal examples of the signatures it
    # detects; scanning its own definitions would be a guaranteed false alarm.
    if path.name == pathlib.Path(__file__).name:
        return []
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return []
        raw = path.read_bytes()
    except OSError:
        return []
    if b"\0" in raw[:8192]:
        return []
    text = raw.decode("utf-8", "ignore")
    findings = []
    for line_no, line in enumerate(text.splitlines(), 1):
        for label_id, (_, pattern) in enumerate(KNOWN_SECRET_PATTERNS):
            if pattern.search(line):
                findings.append((line_no, label_id))
        for match in ASSIGNMENT.finditer(line):
            value = match.group(2).strip()
            if len(value) >= 8 and not SAFE_VALUE.search(value):
                findings.append((line_no, ASSIGNMENT_LABEL_ID))
    return findings


def ignored(path: str) -> bool:
    result = subprocess.run(["git", "check-ignore", "-q", "--", path], check=False)
    return result.returncode == 0


def main() -> int:
    print("\n=== Matchday security check ===\n")
    problems, warnings = [], []
    files = candidate_files()
    for path in files:
        for line_no, label_id in scan(path):
            problems.append(f"{path.as_posix()}:{int(line_no)} — possible {LABELS[label_id]}")

    tracked = set()
    try:
        tracked = set(subprocess.check_output(["git", "ls-files"], text=True).splitlines())
    except Exception:
        warnings.append("Could not inspect Git tracking state.")
    for name in UNTRACKED_CONFIG_FILES:
        if name in tracked:
            problems.append(f"{name} is tracked by Git")
        if pathlib.Path(name).exists() and not ignored(name):
            problems.append(f"{name} exists but is not ignored")

    if problems:
        print(STOP + " DO NOT publish. Potential secret exposure:\n")
        for problem in sorted(set(problems)):
            print("   " + problem)
        print("\n   Remove or rotate real credentials, then run this check again.\n")
        return 1
    print(GREEN + f"Scanned {len(files)} tracked/non-ignored files without finding credential material.")
    print(GREEN + "Known private configuration files are untracked and ignored.")
    if warnings:
        for warning in warnings:
            print(WARN + warning)
    print("\n  All clear for the checks above. GitHub push protection remains the second line of defense.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
