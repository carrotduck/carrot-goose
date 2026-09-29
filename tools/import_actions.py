"""Import a TonyPi SQLite action folder into the browser workbench."""
import argparse
import json
import math
import sqlite3
from contextlib import closing
from pathlib import Path


def read_action(path, idle):
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        columns = [r[1] for r in db.execute('PRAGMA table_info(ActionGroup)')]
        if len(columns) < 3 or columns[:2] != ['Index', 'Time']:
            raise ValueError(f'{path.name}: expected Index, Time, servo columns')
        rows = db.execute('SELECT * FROM ActionGroup ORDER BY "Index"').fetchall()
    if not rows:
        raise ValueError(f'{path.name}: empty action')
    frames, previous, elapsed = [], None, 0.0
    initial = None
    for row in rows:
        duration = float(row[1]) / 1000
        values = row[2:]
        if not math.isfinite(duration) or duration <= 0 or len(values) > 18:
            raise ValueError(f'{path.name}: invalid frame timing or channel count')
        if any(not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1000 for v in values):
            raise ValueError(f'{path.name}: invalid servo value')
        target = {**idle, **{str(i + 1): v for i, v in enumerate(values)}}
        if previous is None:
            previous = target.copy()
            initial = target.copy()
        frames.append({'from': previous, 'target': target, 'start': elapsed,
                       'duration': duration, 'move': duration,
                       'label': f'帧 / Frame {len(frames)+1}', 'gate': None, 'utterance': None})
        previous = target.copy()
        elapsed += duration
    return {'name': path.name, 'initial': initial, 'frames': frames, 'duration': elapsed,
            'status': 'Imported', 'source': path.name}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'apps/studio/library.json')
    args = parser.parse_args()
    library = json.loads(args.output.read_text(encoding='utf-8'))
    idle = {k: v['neutral'] for k, v in library['mapping'].items()}
    paths = sorted(args.folder.glob('*.d6a'))
    if not paths:
        raise SystemExit('No .d6a action files found')
    actions = [read_action(p, idle) for p in paths]
    names = {a['name'] for a in actions}
    library['actions'] = [a for a in library['actions'] if a['name'] not in names] + actions
    temp = args.output.with_suffix('.json.tmp')
    temp.write_text(json.dumps(library, ensure_ascii=False), encoding='utf-8')
    temp.replace(args.output)
    print(f'Imported {len(actions)} actions')


if __name__ == '__main__':
    main()
