"""Export the engine's already-graded cards without rerunning ratings or forecasts.

The poller owns ingestion and settlement. This reader cannot change its SQLite
database, and updating a scorecard must not re-date the rest of the handoff.
"""
import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys


# A card still pending six hours after tip-off is overdue. A few are normal: an
# exhibition opponent ESPN names differently from the odds feed, or a game the
# poller caught mid-play before an outage. Those stay on the page as pending
# and are named in the ship log. Only a pile of them means the poller has
# stopped settling games, and that is what blocks publication.
#
# This used to refuse on a single overdue card. From 2026-11-15 to 11-23 there
# was always at least one (Paine at Bethune-Cookman, whose opponent changed;
# twenty late games from 11-18 the engine's repair pass re-fetched from the
# wrong date's board), so the basketball scorecard froze on Monday's 4-0 while
# the engine held 259-93 for the week.
OVERDUE_FLOOR = 10
OVERDUE_SHARE = 0.10


def overdue_cards(card, now):
    """Names of this week's cards still pending after tip-off, and how many were graded."""
    overdue, graded = [], 0
    for row in card.get('recent', []):
        kickoff = datetime.fromisoformat(row['starts_at'].replace('Z', '+00:00'))
        if not now - timedelta(days=7) <= kickoff < now - timedelta(hours=6):
            continue
        if row.get('result') == 'pending':
            overdue.append(row['event_name'])
        else:
            graded += 1
    return overdue, graded


def merge_scorecard(document, exported, sport, now):
    card = deepcopy(exported['sports'][sport])
    if not card.get('available'):
        raise ValueError('Engine scorecard is unavailable; retaining published record')
    old = document.get('scorecard', {}).get('sports', {}).get(sport, {})
    if card['record']['picks'] < old.get('record', {}).get('picks', 0):
        raise ValueError('Graded record shrank; manual review required')
    # The Scorecard, Research and Learn pages read the record against the
    # market: agreed vs disagreed with the lock-time price, and the outright
    # calls against the favourite. A card without them would publish a hit
    # rate with nothing to read it against, so it is not published at all.
    market = card.get('versus_market') or {}
    for key in ('agreed_with_market', 'disagreed_with_market'):
        if not isinstance(market.get(key), dict) or 'picks' not in market[key]:
            raise ValueError('Engine card lacks ' + key + '; retaining published record')
    if not isinstance((card.get('conviction') or {}).get('outright_disagreements'), dict):
        raise ValueError('Engine card lacks outright market disagreements; retaining published record')
    for key in ('agreed_with_market', 'disagreed_with_market'):
        before = ((old.get('versus_market') or {}).get(key) or {}).get('picks', 0)
        if market[key]['picks'] < before:
            raise ValueError('Market split ' + key + ' shrank; manual review required')
    overdue, graded = overdue_cards(card, now)
    if len(overdue) > max(OVERDUE_FLOOR, OVERDUE_SHARE * graded):
        raise ValueError('%d overdue ungraded cards against %d graded this week (first: %s); '
                         'the poller is not settling games' % (len(overdue), graded, overdue[0]))
    result = deepcopy(document)
    scorecard = result.setdefault('scorecard', {})
    for key in ('caveat', 'scope'):
        if key in scorecard and scorecard[key] != exported[key]:
            raise ValueError('Shared scorecard methodology changed; full export required')
        scorecard[key] = exported[key]
    # A no-op must not trigger another publication merely to change a timestamp.
    comparable = {k: v for k, v in old.items() if k != 'refreshed_at'}
    if comparable == card:
        return document
    card['refreshed_at'] = now.isoformat()
    scorecard.setdefault('sports', {})[sport] = card
    return result


class ReadOnlyDatabase:
    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def connect(self):
        yield self.connection


def read_engine(engine, sport):
    sys.path.insert(0, str(engine.resolve()))
    from trdlab.config import settings, load_dotenv
    from trdlab.matchday import _scorecard
    load_dotenv(engine / '.env')
    database = settings().db_path
    if not database.is_absolute():
        database = engine / database
    database = database.resolve()
    connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('BEGIN')  # one consistent view while the poller writes
        last = connection.execute('SELECT MAX(updated_at) FROM events WHERE sport=?', (sport,)).fetchone()[0]
        if not last or datetime.now(timezone.utc) - datetime.fromisoformat(last.replace('Z', '+00:00')) > timedelta(hours=24):
            raise ValueError('Engine event feed is over 24 hours old; refresh the poller first')
        return _scorecard(ReadOnlyDatabase(connection), [sport])
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', required=True, type=Path)
    parser.add_argument('--sport', choices=('ncaaf', 'ncaam'), default='ncaam')
    parser.add_argument('--handoff', type=Path, default=Path('trdlab_picks.json'))
    args = parser.parse_args()
    original = json.loads(args.handoff.read_text(encoding='utf-8-sig'))
    exported = read_engine(args.engine, args.sport)
    now = datetime.now(timezone.utc)
    if exported['sports'][args.sport].get('available'):
        for name in overdue_cards(exported['sports'][args.sport], now)[0]:
            print('overdue ungraded card, published as pending: ' + name)
    updated = merge_scorecard(original, exported, args.sport, now)
    if updated != original:
        temporary = args.handoff.with_suffix('.scorecard.tmp')
        temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
        temporary.replace(args.handoff)
    print(json.dumps(updated['scorecard']['sports'][args.sport]['record']))


if __name__ == '__main__':
    main()
