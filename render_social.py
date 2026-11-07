"""render_social.py -- render this week's Matchday Studio graphics headlessly.

Phase 2 of the X/TikTok content bot. content_engine.py decides what there is to
say and writes it as a Matchday Studio edition; this script loads that edition
into the vendored studio (social/studio/) in a headless browser and saves one
2160x3840 PNG per graphic, plus a manifest tying each image to the content
item, caption, source hash and expiry it came from.

It publishes nothing. The images are a workflow artifact (social-graphics.yml)
or a local folder; a person still decides what goes out.

Why it drives the real studio instead of redrawing the graphics
---------------------------------------------------------------
The studio is the design the owner edits by hand. A second renderer in Python
would drift from it the first time either changed. Loading the edition through
the studio's own "Load edition" input also means its own validation runs: a
file it would reject by hand fails here too, loudly.

Silence is a valid result. With no complete edition this week (stale handoff,
fewer than five games, a short ranking) it renders nothing and exits 0.

Usage:
    python render_social.py --out out/graphics
    python render_social.py --out out/graphics --now 2026-11-05T15:00:00Z
    python render_social.py --out out/graphics --channel msedge   # use installed Edge

Needs Playwright (`pip install playwright` and `python -m playwright install
chromium`, or `--channel msedge`/`chrome` to use an installed browser).
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import functools
import hashlib
import http.server
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Iterator

import content_engine

ROOT = Path(__file__).resolve().parent
STUDIO_DIR = ROOT / "social" / "studio"
STUDIO_FILES = ("index.html", "collections.js", "brand.png", "matchday.ttf")
READY = "Ready to save."
LOAD_FAILED = "Could not load this edition"
# Studio format -> the content item it illustrates. "prediction" (a typed score
# guess) is not drawn from data and is never rendered here.
MODE_ITEMS = {
    "rankings": ("power_top25", "ncaaf"),
    "ballot": ("ballot_top25", "ncaaf"),
    "matchups": ("slate_preview", "ncaaf"),
    "upset": ("upset_watch", "ncaaf"),
}
RENDER_TIMEOUT_MS = 30_000


def modes_for(edition: dict[str, Any]) -> list[str]:
    """The formats this edition can fill. Ballot and upsets are optional in it."""
    modes = ["rankings", "matchups"]
    if edition.get("ballot"):
        modes.insert(1, "ballot")
    if edition.get("upsets"):
        modes.append("upset")
    return modes


def logos_js(logo_dir: Path, override_dir: Path, names: dict[str, str]) -> tuple[str, dict[str, Path]]:
    """window.STUDIO_LOGOS for the studio's team pickers, and the files it references.

    Keys are the artwork file stems, which are the studio's own team keys.
    An override wins over social/logos for the same key.
    """
    files: dict[str, Path] = {}
    for directory in (logo_dir, override_dir):
        if directory.is_dir():
            files.update({p.stem: p for p in directory.glob("*.png")})
    table = {key: {"name": names.get(key, key), "src": f"logos/{key}.png"}
             for key in sorted(files)}
    return "window.STUDIO_LOGOS=" + json.dumps(table, ensure_ascii=False) + ";\n", files


def stage(build: Path, edition: dict[str, Any]) -> Path:
    """Copy the studio, its logos and the edition into one servable directory."""
    for name in STUDIO_FILES:
        shutil.copy2(STUDIO_DIR / name, build / name)
    names = json.loads((STUDIO_DIR / "logo-names.json").read_text(encoding="utf-8"))
    script, files = logos_js(content_engine.LOGO_DIR, content_engine.LOGO_OVERRIDE_DIR, names)
    (build / "logos.js").write_text(script, encoding="utf-8")
    (build / "logos").mkdir()
    for key, path in files.items():
        shutil.copy2(path, build / "logos" / f"{key}.png")
    edition_path = build / "edition.json"
    edition_path.write_text(json.dumps(edition), encoding="utf-8")
    return edition_path


@contextlib.contextmanager
def serve(directory: Path) -> Iterator[str]:
    """A local origin, so the canvas stays untainted and can be exported."""
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

    handler = functools.partial(Quiet, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/index.html"
    finally:
        server.shutdown()
        server.server_close()


def _wait_ready(page: Any) -> None:
    page.wait_for_function(
        """([ready, failed]) => {
            const s = document.getElementById('status').textContent;
            if (s.startsWith(failed)) throw new Error(s);
            return s === ready && !document.getElementById('png').disabled;
        }""",
        arg=[READY, LOAD_FAILED], timeout=RENDER_TIMEOUT_MS)


def render(url: str, edition_path: Path, modes: list[str], out: Path,
           channel: str | None = None) -> dict[str, Path]:
    from playwright.sync_api import sync_playwright

    written: dict[str, Path] = {}
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**({"channel": channel} if channel else {}))
        try:
            page = browser.new_page(viewport={"width": 1300, "height": 1000})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(url)
            _wait_ready(page)
            # Clear the status so "ready" can only mean the edition has drawn.
            page.evaluate("document.getElementById('status').textContent = ''")
            page.set_input_files("#loadFile", str(edition_path))
            _wait_ready(page)
            for mode in modes:
                page.select_option("#format", mode)
                _wait_ready(page)
                data_url = page.evaluate("document.getElementById('art').toDataURL('image/png')")
                header, _, payload = data_url.partition(",")
                if header != "data:image/png;base64" or not payload:
                    raise RuntimeError(f"studio returned no PNG for {mode}")
                path = out / f"{mode}.png"
                path.write_bytes(base64.b64decode(payload))
                written[mode] = path
        finally:
            browser.close()
    if errors:
        raise RuntimeError("studio raised: " + "; ".join(errors))
    return written


def manifest(queue: dict[str, Any], edition: dict[str, Any], images: dict[str, Path]) -> dict[str, Any]:
    by_kind = {(i["kind"], i["sport"]): i for i in queue["items"]}
    entries = []
    for mode, path in images.items():
        item = by_kind.get(MODE_ITEMS[mode]) or {}
        entries.append({
            "mode": mode,
            "file": path.name,
            "png_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "item_key": item.get("key"),
            "caption": item.get("caption"),
            "expires_at": item.get("expires_at"),
            "source_sha256": (item.get("source") or {}).get("sha256"),
            "caveat": item.get("caveat"),
        })
    return {
        "generated_at": queue["generated_at"],
        "handoff_generated_at": queue.get("handoff_generated_at"),
        "edition": edition.get("edition"),
        "missing_logos": edition.get("_matchday", {}).get("missing_logos", []),
        "images": entries,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", required=True, help="folder for the PNGs and manifest.json")
    parser.add_argument("--now", help="evaluate as of this UTC time (ISO 8601)")
    parser.add_argument("--channel", help="Playwright browser channel, e.g. msedge or chrome")
    args = parser.parse_args(argv)
    now = content_engine.parse_time(args.now) if args.now else None
    if args.now and now is None:
        parser.error("--now must be an ISO 8601 time")

    queue = content_engine.build_queue(now, ROOT)
    edition = content_engine.studio_edition(queue)
    if edition is None:
        reasons = "; ".join(w["reason"] for w in queue["withheld"]) or "no complete edition this week"
        print(f"Nothing to render: {reasons}.")
        return 0

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        build = Path(tmp)
        edition_path = stage(build, edition)
        with serve(build) as url:
            images = render(url, edition_path, modes_for(edition), out, args.channel)
    (out / "content_queue.json").write_text(
        json.dumps(queue, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report = manifest(queue, edition, images)
    (out / "manifest.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                       encoding="utf-8")
    for entry in report["images"]:
        print(f"{entry['file']}: {entry['caption']}")
    if report["missing_logos"]:
        print("missing logos (drawn blank): " + ", ".join(report["missing_logos"]))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
