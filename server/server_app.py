"""
Matchday Leaderboard — tiny always-on app (Path B: simpler, small monthly cost)
Single-file Flask app + SQLite. Run anywhere that hosts a Python process.

Deploy:
  pip install flask
  python server_app.py           # local test on :5000
  (on a host: run behind gunicorn, set PORT env)

Endpoints:
  POST /score        {deviceId, handle, hits, graded, streak}
  GET  /leaderboard  -> {ok, board:[{handle,hits,graded,streak}]}
"""
import os, re, time, sqlite3, json
from flask import Flask, request, jsonify

APP = Flask(__name__)
DB = os.environ.get("MATCHDAY_DB", "leaderboard.db")
_RATE = {}

def db():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS scores(
        device_id TEXT PRIMARY KEY, handle TEXT NOT NULL,
        hits INT, graded INT, streak INT, updated INT)""")
    return c

def bad(s): return bool(re.search(r"[<>{}$]", s or ""))

@APP.after_request
def cors(r):
    r.headers["Access-Control-Allow-Origin"] = "*"
    r.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return r

@APP.route("/leaderboard")
def leaderboard():
    c = db()
    rows = c.execute(
        "SELECT handle,hits,graded,streak FROM scores WHERE graded>=10 "
        "ORDER BY (CAST(hits AS FLOAT)/graded) DESC, graded DESC LIMIT 100").fetchall()
    c.close()
    return jsonify(ok=True, board=[
        {"handle":h,"hits":ht,"graded":g,"streak":s} for (h,ht,g,s) in rows])

@APP.route("/score", methods=["POST","OPTIONS"])
def score():
    if request.method == "OPTIONS": return ("", 200)
    b = request.get_json(force=True, silent=True) or {}
    did, handle = b.get("deviceId"), b.get("handle")
    if not did or not handle: return jsonify(ok=False, error="missing id/handle"), 400
    if bad(handle) or len(handle) > 24: return jsonify(ok=False, error="bad handle"), 400
    try: H,G,S = int(b["hits"]), int(b["graded"]), int(b["streak"])
    except Exception: return jsonify(ok=False, error="bad numbers"), 400
    # GUARDRAIL 1: sanity
    if min(H,G,S) < 0 or H > G or S > G or G > 5000:
        return jsonify(ok=False, error="impossible record"), 400
    # GUARDRAIL 2: rate limit
    now, last = time.time(), _RATE.get(did, 0)
    if now - last < 60: return jsonify(ok=False, error="slow down"), 429
    _RATE[did] = now
    c = db()
    prev = c.execute("SELECT graded FROM scores WHERE device_id=?", (did,)).fetchone()
    if prev and G - prev[0] > 50:
        c.close(); return jsonify(ok=False, error="graded jump too large"), 400
    c.execute("INSERT INTO scores VALUES(?,?,?,?,?,?) "
              "ON CONFLICT(device_id) DO UPDATE SET handle=?,hits=?,graded=?,streak=?,updated=?",
              (did, handle[:24], H, G, S, int(now), handle[:24], H, G, S, int(now)))
    c.commit(); c.close()
    return jsonify(ok=True)

if __name__ == "__main__":
    APP.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
