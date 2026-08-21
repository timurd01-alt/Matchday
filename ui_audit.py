"""Audit Matchday's shipped front-end for interface defects that are checkable.

The product loop this feeds needs findings, not opinions. "Does the site look
modern?" asked on a schedule produces invented work -- the exact failure mode
`next_task.py` exists to prevent -- because a loop with nothing concrete to
say still has to say something. So this module reports only violations it can
point at: a file, a line, and a rule that was broken. Taste is left to the
agent that picks the task up, and it arrives holding evidence rather than a
prompt to go and have an opinion.

Every rule here encodes a published interface requirement (WCAG 2.2 AA, the
Core Web Vitals layout-shift guidance) or a budget stated in this file. None
of them are stylistic preferences, because a loop cannot referee taste and
should not try.

Deliberately NOT checked here:

  * Anything requiring layout. Rendered geometry, overlap, and actual contrast
    after compositing need a browser; this runs inside the hourly publish
    workflow, which must not depend on a headless browser to deploy the site.
  * Any file under posts/ or updates/ -- generated output, not authored
    source. A finding there is a bug in the generator, and pointing an agent
    at the artifact instead of the generator sends it to the wrong file.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from js_toplevel import top_level_declarations

SCHEMA_VERSION = 1

# The pages a visitor actually loads. mini.html and qa.html are internal
# diagnostic surfaces, deliberately excluded: holding a debug view to the
# product's interface bar generates work nobody wants done.
AUDITED_HTML = ("index.html", "content.html", "legal.html",
                "tactics-baseball.html", "tactics-basketball.html",
                "tactics-football.html", "tactics-hockey.html",
                "tactics-soccer.html")
AUDITED_CSS = ("styles.css", "content.css", "research-signals.css")

# Most of this interface is rendered from template literals in these files, not
# from the .html shells, so an audit that reads only HTML sees a fraction of
# the markup that actually ships. Confirmed the hard way: the 1.18MB logo was
# removed from index.html and the audit went green while app-1-core.js was
# still injecting the same image into the hero band on every page view.
#
# Only the <img> rules run here. Heading order and document-level rules
# (lang, viewport) are meaningless across fragments that get composed at
# runtime in an order this cannot know.
AUDITED_JS = ("app-1-core.js", "app-2-views.js", "app-3-panels.js",
              "app-4-features.js", "app-5-outcome-tree.js", "content.js",
              "research-signals.js")

# WCAG 2.2 AA: 4.5:1 for body text, 3:1 for large text. Without layout we
# cannot know which rules render large, so the lower bar is applied and only
# pairs failing even that are reported. A rule that fails 3:1 fails at every
# size, so this cannot produce a false positive from font size alone.
CONTRAST_FLOOR = 3.0

# WCAG 2.2 AA SC 2.5.8 (Target Size, Minimum) is 24x24 CSS px. Apple's 44pt
# guidance is larger but is a recommendation, not a conformance bar, so the
# conformance number is used to keep every finding actionable rather than
# arguable.
MIN_TAP_TARGET_PX = 24

# Render-blocking bytes in <head>, uncompressed. Not a conformance rule --
# a stated budget, so that growth has to be a decision somebody makes rather
# than something that happens. Raise it deliberately if the site outgrows it.
RENDER_BLOCKING_BUDGET_BYTES = 320_000

# Per-image budget. The first version of this module counted only CSS and JS,
# so logo.png -- 1254x1254, 1.18MB, displayed at 76px -- passed every check
# while being several times the weight of the entire render-blocking budget it
# was measured alongside. An image nobody sees at full resolution is the
# easiest weight on a page to remove, and the hardest to notice.
IMAGE_BUDGET_BYTES = 150_000

INTERACTIVE_HINT = re.compile(
    r"(^|[\s,>+~])(button|a|summary|\[role=[\"']?(button|link|tab)[\"']?\])(?![\w-])"
    r"|\.(btn|button|tab|chip|pill|nav-|icon-btn)", re.I)

_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_HEX = re.compile(r"^#([0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$", re.I)
_RGB = re.compile(r"^rgba?\(([^)]+)\)$", re.I)
_VAR = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^)]+))?\)", re.I)


def _finding(rule: str, severity: str, file: str, line: int, detail: str,
             snippet: str = "") -> dict[str, Any]:
    return {"rule": rule, "severity": severity, "file": file, "line": line,
            "detail": detail, "snippet": snippet[:160]}


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


# --------------------------------------------------------------------------
# colour handling
# --------------------------------------------------------------------------

def _parse_color(value: str) -> tuple[float, float, float] | None:
    """Opaque sRGB 0-255 triple, or None for anything not statically resolvable.

    Returning None for keywords, gradients and unresolved vars is the point:
    a rule this cannot read is skipped silently rather than guessed at, so
    every contrast finding rests on two colours actually written down.

    Translucent colours are unresolvable in exactly that sense and are
    rejected rather than flattened. This codebase tints badges with the same
    hue as their text -- `.etag.value{color:var(--win);background:rgba(58,
    209,122,.12)}` -- so dropping the alpha and treating the tint as solid
    compares a colour against itself and reports a perfect 1.00:1 failure for
    a pill that renders as legible green on near-black. Composited over an
    unknown ancestor, the real background simply is not knowable from here.
    """
    value = value.strip().lower()
    match = _HEX.match(value)
    if match:
        digits = match.group(1)
        if len(digits) in (3, 4):
            digits = "".join(char * 2 for char in digits)
        if len(digits) == 8 and int(digits[6:8], 16) < 255:
            return None
        return tuple(float(int(digits[i:i + 2], 16)) for i in (0, 2, 4))
    match = _RGB.match(value)
    if match:
        parts = [part for part in re.split(r"[,\s/]+", match.group(1).strip()) if part]
        numbers = []
        for part in parts[:3]:
            try:
                numbers.append(float(part[:-1]) * 255 / 100 if part.endswith("%")
                               else float(part))
            except ValueError:
                return None
        if len(parts) > 3:
            alpha = parts[3]
            try:
                if (float(alpha[:-1]) / 100 if alpha.endswith("%")
                        else float(alpha)) < 1.0:
                    return None
            except ValueError:
                return None
        if len(numbers) == 3:
            return tuple(min(255.0, max(0.0, number)) for number in numbers)
    return {"white": (255.0, 255.0, 255.0), "black": (0.0, 0.0, 0.0)}.get(value)


def _resolve_vars(value: str, variables: dict[str, str], depth: int = 0) -> str:
    """Expand var(--x) against declared custom properties, fallback included.

    A design system defines its palette once and references it everywhere, so
    a contrast check that cannot follow var() can only see the handful of
    literal colours -- which on this codebase would be nearly none of them.
    """
    if depth > 6:
        return value

    def swap(match: re.Match) -> str:
        name, fallback = match.group(1), match.group(2)
        if name in variables:
            return _resolve_vars(variables[name], variables, depth + 1)
        return _resolve_vars(fallback, variables, depth + 1) if fallback else ""

    return _VAR.sub(swap, value)


def _relative_luminance(rgb: tuple[float, float, float]) -> float:
    channels = []
    for raw in rgb:
        channel = raw / 255.0
        channels.append(channel / 12.92 if channel <= 0.03928
                        else ((channel + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(foreground: tuple[float, float, float],
                   background: tuple[float, float, float]) -> float:
    light, dark = sorted((_relative_luminance(foreground),
                          _relative_luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


# --------------------------------------------------------------------------
# CSS
# --------------------------------------------------------------------------

def _rules(css: str) -> list[tuple[str, str, int]]:
    """(selector, body, line) for each declaration block, at-rules flattened."""
    stripped = _COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), css)
    found = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", stripped):
        raw = match.group(1)
        selector = " ".join(raw.split())
        if selector.startswith("@") or not selector:
            continue
        # `[^{}]+` starts matching at the character after the previous rule's
        # closing brace, so it swallows the newline and indentation in front
        # of the selector. Reporting match.start() therefore names the line
        # the PREVIOUS rule ended on, and an agent sent to fix a finding opens
        # the wrong rule. Offset to where the selector text actually begins.
        offset = len(raw) - len(raw.lstrip())
        found.append((selector, match.group(2),
                      _line_of(stripped, match.start(1) + offset)))
    return found


def _subject(selector: str) -> str:
    """The final compound of each comma-separated selector -- the element the
    rule actually styles, as opposed to the ancestors that merely scope it."""
    subjects = []
    for part in selector.split(","):
        pieces = re.split(r"[\s>+~]+", part.strip())
        subjects.append(pieces[-1] if pieces else "")
    return ",".join(piece for piece in subjects if piece)


def _declarations(body: str) -> dict[str, str]:
    out = {}
    for part in body.split(";"):
        if ":" not in part:
            continue
        name, _, value = part.partition(":")
        name, value = name.strip().lower(), value.strip()
        if name:
            out[name] = value
    return out


def _custom_properties(rules: list[tuple[str, str, int]]) -> dict[str, str]:
    variables: dict[str, str] = {}
    for _selector, body, _line in rules:
        for name, value in _declarations(body).items():
            if name.startswith("--"):
                variables.setdefault(name, value)
    return variables


def audit_css(path: Path) -> list[dict[str, Any]]:
    try:
        css = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    name = path.name
    rules = _rules(css)
    variables = _custom_properties(rules)
    findings: list[dict[str, Any]] = []

    focus_visible_selectors = {
        selector for selector, _body, _line in rules if ":focus-visible" in selector}

    for selector, body, line in rules:
        declarations = _declarations(body)

        # Focus indicator removed. Only flagged when nothing anywhere restores
        # a visible focus ring for the same base selector -- this codebase
        # pairs `outline:none` with a `:focus-visible` rule 18 times, and a
        # check that could not see the pair would report every one of them.
        outline = declarations.get("outline", "")
        if re.match(r"^(none|0)(\s|$)", outline) and ":focus" in selector:
            base = selector.split(":focus")[0].strip()
            restored = any(candidate.startswith(base) or base in candidate
                           for candidate in focus_visible_selectors)
            if not restored and "box-shadow" not in declarations:
                findings.append(_finding(
                    "focus-indicator-removed", "blocker", name, line,
                    "Focus outline removed with no :focus-visible rule and no "
                    "box-shadow substitute, leaving keyboard users with no "
                    "visible focus (WCAG 2.4.7).", selector))

        # Fixed tap targets below the conformance floor. Matched against the
        # selector's SUBJECT (its final compound) rather than anywhere in the
        # selector: `.pill.LIVE .blink` styles a decorative 5px pulsing dot
        # inside a pill, and testing the whole string flags the dot because an
        # ancestor happens to be interactive. What gets tapped is the subject.
        if INTERACTIVE_HINT.search(_subject(selector)) and ":" not in selector:
            for prop in ("height", "width", "min-height", "min-width"):
                raw = declarations.get(prop, "")
                match = re.match(r"^(\d+(?:\.\d+)?)px$", raw.strip())
                if match and float(match.group(1)) < MIN_TAP_TARGET_PX:
                    findings.append(_finding(
                        "tap-target-undersized", "warn", name, line,
                        f"Interactive element fixes {prop} at {match.group(1)}px, "
                        f"below the {MIN_TAP_TARGET_PX}px WCAG 2.5.8 minimum.",
                        selector))
                    break

        # Statically resolvable text-on-background contrast.
        foreground_raw = declarations.get("color")
        background_raw = (declarations.get("background-color")
                          or declarations.get("background"))
        if foreground_raw and background_raw:
            foreground = _parse_color(_resolve_vars(foreground_raw, variables))
            background = _parse_color(_resolve_vars(background_raw, variables))
            if foreground and background:
                ratio = contrast_ratio(foreground, background)
                if ratio < CONTRAST_FLOOR:
                    findings.append(_finding(
                        "contrast-below-floor", "blocker", name, line,
                        f"Declared text/background contrast is {ratio:.2f}:1, "
                        f"below the {CONTRAST_FLOOR}:1 floor that applies at "
                        f"every font size (WCAG 1.4.3).", selector))

    # Motion without a reduced-motion escape hatch.
    animated = re.search(r"(^|[\s;{])(transition|animation)\s*:", css)
    if animated and "prefers-reduced-motion" not in css:
        findings.append(_finding(
            "reduced-motion-unsupported", "warn", name,
            _line_of(css, animated.start()),
            "Stylesheet animates but never honours prefers-reduced-motion, so "
            "users who asked the OS for less motion still get all of it "
            "(WCAG 2.3.3).", animated.group(0).strip()))
    return findings


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

def css_sized_classes(base: Path) -> set[str]:
    """Class names whose stylesheet rules already reserve a box.

    `img-dimensions-missing` exists to catch layout shift, and an element the
    stylesheet gives both a width and a height does not shift -- the space is
    reserved before the image arrives. Judging the HTML attribute alone
    reported `.welcomeLogo`, which is sized `76px` square in styles.css and
    cannot move. A rule that flags markup for a problem the CSS already solved
    trains its reader to skip it.
    """
    sized: set[str] = set()
    for name in AUDITED_CSS:
        path = base / name
        if not path.is_file():
            continue
        try:
            css = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for selector, body, _line in _rules(css):
            declarations = _declarations(body)
            has_box = (("width" in declarations and "height" in declarations)
                       or "aspect-ratio" in declarations)
            if not has_box:
                continue
            for match in re.finditer(r"\.([\w-]+)", _subject(selector)):
                sized.add(match.group(1))
    return sized


def audit_html(path: Path, sized_classes: set[str] | None = None,
               root: Path | None = None) -> list[dict[str, Any]]:
    try:
        html = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    name = path.name
    sized_classes = sized_classes or set()
    root = root or path.parent
    findings: list[dict[str, Any]] = []

    html_tag = re.search(r"<html\b([^>]*)>", html, re.I)
    if html_tag and not re.search(r"\blang\s*=", html_tag.group(1), re.I):
        findings.append(_finding(
            "html-lang-missing", "blocker", name, _line_of(html, html_tag.start()),
            "<html> has no lang attribute, so screen readers cannot pick a "
            "pronunciation for the page (WCAG 3.1.1).", html_tag.group(0)))

    viewport = re.search(r"<meta[^>]*name=[\"']viewport[\"'][^>]*>", html, re.I)
    if viewport:
        content = viewport.group(0).lower()
        if "user-scalable=no" in content.replace(" ", "") or re.search(
                r"maximum-scale\s*=\s*(1(\.0+)?|0?\.\d+)\b", content):
            findings.append(_finding(
                "viewport-zoom-blocked", "blocker", name,
                _line_of(html, viewport.start()),
                "Viewport meta blocks pinch-zoom, which low-vision users rely "
                "on to read the page (WCAG 1.4.4).", viewport.group(0)))

    findings.extend(_image_findings(html, name, sized_classes, root))

    # Heading order. A jump downward skips a level and breaks the outline
    # screen-reader users navigate by; jumps back up are how sections close
    # and are not a defect.
    previous = 0
    for match in re.finditer(r"<h([1-6])\b", html, re.I):
        level = int(match.group(1))
        if previous and level > previous + 1:
            findings.append(_finding(
                "heading-level-skipped", "warn", name,
                _line_of(html, match.start()),
                f"Heading jumps from h{previous} to h{level}, skipping a level "
                f"in the document outline (WCAG 1.3.1).", match.group(0)))
        previous = level

    return findings


def _image_findings(html: str, name: str, sized_classes: set[str],
                    root: Path) -> list[dict[str, Any]]:
    """The <img> rules, over any markup source."""
    findings = []
    for match in re.finditer(r"<img\b[^>]*>", html, re.I):
        tag, line = match.group(0), _line_of(html, match.start())
        if not re.search(r"\balt\s*=", tag, re.I):
            findings.append(_finding(
                "img-alt-missing", "blocker", name, line,
                "<img> has no alt attribute. Decorative images need alt=\"\" "
                "so assistive tech can skip them (WCAG 1.1.1).", tag))
        has_dimensions = (re.search(r"\bwidth\s*=", tag, re.I)
                          and re.search(r"\bheight\s*=", tag, re.I))
        class_attr = re.search(r'\bclass\s*=\s*["\']([^"\']*)["\']', tag, re.I)
        classes = set((class_attr.group(1) if class_attr else "").split())
        if (not has_dimensions and "style=" not in tag.lower()
                and not (classes & sized_classes)):
            findings.append(_finding(
                "img-dimensions-missing", "warn", name, line,
                "<img> declares no width/height and no stylesheet rule "
                "reserves a box for it, so the page shifts as it loads (CLS).",
                tag))
        source = re.search(r'\bsrc\s*=\s*["\']([^"\']+)["\']', tag, re.I)
        if source and not source.group(1).startswith(
                ("http://", "https://", "//", "data:", "$")):
            asset = root / source.group(1).split("?", 1)[0].lstrip("./")
            if asset.is_file() and asset.stat().st_size > IMAGE_BUDGET_BYTES:
                findings.append(_finding(
                    "image-over-budget", "warn", name, line,
                    f"{asset.name} is {asset.stat().st_size:,} bytes, over the "
                    f"{IMAGE_BUDGET_BYTES:,}-byte per-image budget. Check the "
                    f"size it actually renders at before shipping the "
                    f"full-resolution file.", tag))
    return findings


def audit_js_markup(path: Path, sized_classes: set[str],
                    root: Path) -> list[dict[str, Any]]:
    """Image rules over markup built in JavaScript template literals."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return _image_findings(source, path.name, sized_classes, root)


def audit_render_budget(root: Path, page: str = "index.html") -> list[dict[str, Any]]:
    """Render-blocking bytes referenced from <head>, against a stated budget."""
    path = root / page
    try:
        html = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    head = html.split("</head>", 1)[0]
    total, counted = 0, []
    for match in re.finditer(
            r"<link[^>]+rel=[\"']stylesheet[\"'][^>]*href=[\"']([^\"']+)[\"']"
            r"|<script(?![^>]*\b(?:async|defer|type=[\"']module[\"']))[^>]*"
            r"src=[\"']([^\"']+)[\"']", head, re.I):
        href = match.group(1) or match.group(2) or ""
        if href.startswith(("http://", "https://", "//")):
            continue  # third-party bytes this repo cannot change
        asset = root / href.split("?", 1)[0].lstrip("./")
        if asset.is_file():
            total += asset.stat().st_size
            counted.append(asset.name)
    if total > RENDER_BLOCKING_BUDGET_BYTES:
        return [_finding(
            "render-blocking-over-budget", "warn", page, 1,
            f"{total:,} bytes of render-blocking CSS/JS in <head> exceeds the "
            f"{RENDER_BLOCKING_BUDGET_BYTES:,}-byte budget "
            f"({', '.join(sorted(counted))}). Every one of these blocks first "
            f"paint on a phone connection.")]
    return []


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

SEVERITY_ORDER = {"blocker": 0, "warn": 1}


# The scripts index.html loads, in the order it loads them. They are classic
# <script> tags, not modules, so all nine share one global lexical scope.
INDEX_BUNDLE = ("translations.js", "updates.js", "app-1-core.js",
                "official-selections.js", "app-2-views.js",
                "app-5-outcome-tree.js", "app-3-panels.js",
                "app-4-features.js", "research-signals.js")


def audit_js_globals(root: str | Path = ".",
                     bundle: tuple[str, ...] = INDEX_BUNDLE) -> list[dict[str, Any]]:
    """Two scripts must never declare the same top-level name.

    These files share one global lexical scope, so a `const`/`let`/`class`
    declared twice across them is a SyntaxError -- and a SyntaxError in a
    classic script takes the whole app down, not one panel. There is no
    bundler, linter, or build step in this project to catch it, and the 462
    top-level declarations currently in the bundle are spread across nine
    files with no index, so the collision is a live risk every time a helper
    is added. Nothing was watching; this is.

    `var` and `function` are legal to redeclare, so those are reported at
    `warn` rather than `blocker`: the app keeps running, but whichever file
    loads last silently wins, which is its own hard-to-find bug.
    """
    base = Path(root)
    seen: dict[str, tuple[str, int, str]] = {}
    findings: list[dict[str, Any]] = []
    for name in bundle:
        path = base / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for decl in top_level_declarations(text):
            previous = seen.get(decl.name)
            if previous is None:
                seen[decl.name] = (name, decl.line, decl.kind)
                continue
            first_file, first_line, first_kind = previous
            fatal = "const" in (decl.kind, first_kind) or \
                    "let" in (decl.kind, first_kind) or \
                    "class" in (decl.kind, first_kind)
            findings.append(_finding(
                "js-global-collision",
                "blocker" if fatal else "warn",
                name, decl.line,
                f"`{decl.name}` is declared at the top level of both "
                f"{first_file}:{first_line} ({first_kind}) and {name}:{decl.line} "
                f"({decl.kind}); these scripts share one global scope, so this "
                + ("is a SyntaxError that blanks the entire app"
                   if fatal else
                   "silently keeps whichever loads last"),
                decl.name))
    return findings


def build_report(root: str | Path = ".") -> dict[str, Any]:
    base = Path(root)
    findings: list[dict[str, Any]] = []
    scanned: list[str] = []
    sized = css_sized_classes(base)
    for name in AUDITED_HTML:
        path = base / name
        if path.is_file():
            scanned.append(name)
            findings.extend(audit_html(path, sized, base))
    for name in AUDITED_CSS:
        path = base / name
        if path.is_file():
            scanned.append(name)
            findings.extend(audit_css(path))
    for name in AUDITED_JS:
        path = base / name
        if path.is_file():
            scanned.append(name)
            findings.extend(audit_js_markup(path, sized, base))
    findings.extend(audit_render_budget(base))
    findings.extend(audit_js_globals(base))
    scanned.extend(n for n in INDEX_BUNDLE if (base / n).is_file())
    findings.sort(key=lambda item: (SEVERITY_ORDER.get(item["severity"], 9),
                                    item["file"], item["line"], item["rule"]))
    counts: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    for item in findings:
        counts[item["severity"]] = counts.get(item["severity"], 0) + 1
        by_rule[item["rule"]] = by_rule.get(item["rule"], 0) + 1
    return {"schema_version": SCHEMA_VERSION, "scanned": sorted(scanned),
            "findings": findings, "counts": counts, "by_rule": by_rule,
            "blockers": counts.get("blocker", 0), "warnings": counts.get("warn", 0)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", help="write the report JSON to this path")
    parser.add_argument("--fail-on-blocker", action="store_true",
                        help="exit non-zero when a blocker is present "
                             "(off in the publish workflow: an interface "
                             "defect must not take the live site down)")
    args = parser.parse_args(argv)

    report = build_report(args.root)
    if args.output:
        Path(args.output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8", newline="\n")
    if not report["findings"]:
        print("ui_audit: no interface defects found in "
              f"{len(report['scanned'])} file(s)")
    else:
        print(f"ui_audit: {report['blockers']} blocker(s), "
              f"{report['warnings']} warning(s)")
        for item in report["findings"][:40]:
            print(f"  [{item['severity']}] {item['file']}:{item['line']} "
                  f"{item['rule']} -- {item['detail']}")
        if len(report["findings"]) > 40:
            print(f"  ... {len(report['findings']) - 40} more in the report")
    return 1 if args.fail_on_blocker and report["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
