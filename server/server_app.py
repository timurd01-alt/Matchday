"""
Legacy Matchday leaderboard reader.

The old SQLite write endpoint trusted browser-supplied totals and is permanently
disabled. Production writes must use api/leaderboard.js, which locks individual
picks before kickoff and grades them server-side.

Deploy:
  pip install flask
  python server_app.py           # local test on :5000
  (on a host: run behind gunicorn, set PORT env)

Endpoints:
  POST /score        disabled (HTTP 410)
  GET  /leaderboard  -> {ok, board:[{handle,hits,graded,streak}]}
"""
import os, sqlite3
from flask import Flask, request, jsonify

APP = Flask(__name__)
DB = os.environ.get("MATCHDAY_DB", "leaderboard.db")

def db():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS scores(
        device_id TEXT PRIMARY KEY, handle TEXT NOT NULL,
        hits INT, graded INT, streak INT, updated INT)""")
    return c

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
    return jsonify(ok=False, error="legacy writes disabled; use the verified API"), 410

if __name__ == "__main__":
    APP.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
