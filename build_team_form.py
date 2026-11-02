"""Expose current-season final scores already held in Matchday's game archive."""
import csv
import datetime as dt
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent


def build(output=ROOT, root=ROOT, today=None):
    today = today or dt.date.today()
    year = today.year if today.month >= 7 else today.year - 1
    season = f'{year}-{str(year+1)[-2:]}'
    result = {}
    for comp in ('ncaaf', 'ncaam'):
        games = []
        source = root / 'archive/games' / comp / (season+'.csv')
        if source.exists():
            with source.open(encoding='utf-8', newline='') as handle:
                for row in csv.DictReader(handle):
                    if row['status'] != 'FINISHED':
                        continue
                    try:
                        home, away = int(row['home_score']), int(row['away_score'])
                    except (ValueError, TypeError):
                        continue
                    games.append(dict(id=row['game_id'], kickoff=row['date_utc'], status='FINISHED', home={'name':row['home_name']}, away={'name':row['away_name']}, score={'home':home,'away':away}))
        result[comp] = games
    Path(output).mkdir(parents=True, exist_ok=True)
    (Path(output) / 'team-form-history.js').write_text('/* Generated from Matchday game archive. */\nwindow.MATCHDAY_TEAM_FORM = '+json.dumps(result, separators=(',',':'), ensure_ascii=True)+';\n', encoding='utf-8', newline='\n')
    return result


if __name__ == '__main__':
    build(Path(sys.argv[1]) if len(sys.argv)>1 else ROOT)
