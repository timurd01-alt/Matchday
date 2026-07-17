"""
Matchday Terminal — safe launcher
---------------------------------
Starts the local server and opens Matchday in an Edge/Chrome app-style window.
This version uses football-data.org for soccer fixtures/scores and BALLDONTLIE
for free NBA/NFL schedules and scores. CollegeFootballData and
CollegeBasketballData supply NCAAF/NCAAM. Sportmonks supplies optional
soccer detail, and The Odds API supplies
market comparison and title odds.

Run:                  python app.py
Plain browser:        python app.py --browser
No live fetcher:      python app.py --no-fetch
Old pywebview mode:   python app.py --webview
"""

from __future__ import annotations

import functools
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEFAULT_PORT = 8000
HERE = Path(__file__).resolve().parent
PROFILE_DIR = HERE / ".browser-profile"

os.environ.setdefault(
    "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
    "--disable-gpu --disable-gpu-compositing --disable-extensions",
)
os.environ.setdefault("WEBVIEW2_USER_DATA_FOLDER", str(HERE / ".webview2-profile"))

import fetch_data  # noqa: E402


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def make_server() -> tuple[ReusableThreadingHTTPServer, int]:
    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def end_headers(self):
            # never let the browser cache app files — updates show immediately
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            super().end_headers()

    handler = functools.partial(Quiet, directory=str(HERE))
    for port in range(DEFAULT_PORT, DEFAULT_PORT + 50):
        try:
            return ReusableThreadingHTTPServer(("127.0.0.1", port), handler), port
        except OSError:
            continue
    raise RuntimeError("Could not open a local port from 8000 to 8049.")


def wait_for_server(port: int, timeout: float = 8.0) -> None:
    url = f"http://127.0.0.1:{port}/index.html"
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.75) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_error = exc
            time.sleep(0.1)
    raise RuntimeError(f"Local server did not respond at {url}: {last_error}")


def keys_are_set() -> bool:
    return (
        "PASTE_" not in getattr(fetch_data, "FOOTBALL_DATA_KEY", "PASTE_")
        and "PASTE_" not in getattr(fetch_data, "ODDS_API_KEY", "PASTE_")
        and bool(getattr(fetch_data, "FOOTBALL_DATA_KEY", ""))
        and bool(getattr(fetch_data, "ODDS_API_KEY", ""))
    )


def fetch_loop() -> None:
    while True:
        live = 0
        failed = False
        try:
            live = fetch_data.build()
        except Exception as exc:
            failed = True
            print("  ! fetch error:", exc)
        if failed:
            delay = 180  # retry soon after an error instead of waiting the idle hour
        else:
            delay = fetch_data.LIVE_SECONDS if live else fetch_data.IDLE_MINUTES * 60
        time.sleep(delay)


def browser_candidates() -> list[Path | str]:
    candidates: list[Path | str] = []
    for exe in ("msedge", "chrome", "chromium"):
        found = shutil.which(exe)
        if found:
            candidates.append(found)
    if platform.system() == "Windows":
        roots = [os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")]
        rels = [r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"]
        for root in roots:
            if not root:
                continue
            for rel in rels:
                candidates.append(Path(root) / rel)
    out: list[Path | str] = []
    seen: set[str] = set()
    for item in candidates:
        key = str(item).lower()
        if key not in seen:
            out.append(item)
            seen.add(key)
    return out


def launch_app_mode(url: str) -> bool:
    PROFILE_DIR.mkdir(exist_ok=True)
    for browser in browser_candidates():
        browser_path = Path(browser)
        if isinstance(browser, Path) and not browser_path.exists():
            continue
        if isinstance(browser, str) and not Path(browser).exists() and shutil.which(browser) is None:
            continue
        try:
            subprocess.Popen([
                str(browser),
                f"--app={url}",
                "--new-window",
                "--no-first-run",
                f"--user-data-dir={PROFILE_DIR}",
            ], cwd=str(HERE))
            print(f"Opened app window with: {browser}")
            return True
        except Exception as exc:
            print(f"Could not launch {browser}: {exc}")
    return False


def open_plain_browser(url: str) -> None:
    webbrowser.open(url)
    print("Opened in your default browser.")


def open_webview(url: str) -> bool:
    try:
        import webview
    except ImportError:
        print("pywebview is not installed.")
        return False
    try:
        webview.create_window("Matchday Terminal", url, width=1180, height=820, min_size=(420, 620))
        icon_path = HERE / "matchday.ico"
        try:
            webview.start(icon=str(icon_path) if icon_path.exists() else None)
        except TypeError:
            webview.start()
        return True
    except Exception as exc:
        print("WebView failed:", exc)
        return False


def keep_alive(httpd: ReusableThreadingHTTPServer) -> None:
    print("\nKeep this window open while using Matchday Terminal.")
    print("Press Enter here to stop the local server.\n")
    try:
        input()
    except EOFError:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    finally:
        httpd.shutdown()


def main() -> None:
    httpd, port = make_server()
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    wait_for_server(port)
    url = f"http://127.0.0.1:{port}/index.html"
    print(f"Server running at {url}")

    if "--no-fetch" in sys.argv:
        print("Live fetcher disabled for this launch.")
    elif keys_are_set():
        _single = any(f in sys.argv for f in ("--wc", "--ucl", "--epl", "--laliga", "--seriea",
                                               "--bundesliga", "--ligue1", "--nfl", "--ncaaf", "--ncaam", "--nba",
                                               "--mlb", "--nhl"))
        if _single:
            threading.Thread(target=fetch_loop, daemon=True).start()
        else:
            import multi_fetch
            threading.Thread(target=multi_fetch.loop, daemon=True).start()
            print("Multi-sport fetcher running — all sports stay fresh automatically.")
        print("Data fetcher started in the background.")
    else:
        print("Missing football-data.org or Odds API key — using existing/sample data.json.")

    if "--webview" in sys.argv:
        if not open_webview(url):
            open_plain_browser(url)
    elif "--browser" in sys.argv:
        open_plain_browser(url)
    else:
        if not launch_app_mode(url):
            print("Could not find Edge/Chrome app mode; using normal browser.")
            open_plain_browser(url)

    keep_alive(httpd)


if __name__ == "__main__":
    main()
