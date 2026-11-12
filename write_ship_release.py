"""Append a release entry for a changed engine shipment; never edit past notes."""
from datetime import datetime, timezone
import json
from pathlib import Path
from build_updates import load_entries


def main():
    entries = load_entries()
    rank = max(entry['rank'] for entry in entries) + 1
    build = datetime.now(timezone.utc).strftime('%m%d') + 'S' + str(rank)
    entry = {'rank': rank, 'date': 'Build ' + build, 'tag': 'Data',
             'title': 'Engine publication refreshed',
             'items': ['Refreshed the engine publication. Market comparisons use the probabilities frozen before the game; missing historical prices remain unavailable.']}
    with (Path('updates') / (build + '.json')).open('x', encoding='utf-8', newline='\n') as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
