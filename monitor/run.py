import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from .core import evaluate, identity
from .sources import collect


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def process(jobs, profile, state, sink=None, now=None):
    now = now or datetime.now(timezone.utc).isoformat()
    destination = getattr(sink, 'delivery_key', 'docs')
    matches, cycle = [], set()
    for job in jobs:
        key = identity(job)
        if key in cycle:
            continue
        cycle.add(key)
        previous = state.setdefault(key, {'first_seen': now, 'reported': False})
        if (destination == 'docs' and previous['reported']) or destination in previous.get('reported_to', []):
            continue
        result = evaluate(job, profile)
        if result:
            result.update(first_seen=previous['first_seen'], checked_at=now)
            matches.append(result)
    matches.sort(key=lambda j: (-j['fit_score'], j['company'], j['title']))
    if sink:
        for offset in range(0, len(matches), 20):
            batch = matches[offset:offset + 20]
            delivered = sink.append(batch)
            for key in delivered:
                if destination == 'docs':
                    state[key]['reported'] = True
                elif destination not in state[key].setdefault('reported_to', []):
                    state[key]['reported_to'].append(destination)
    return matches


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', help='Local private profile JSON; defaults to PROFILE_JSON secret')
    parser.add_argument('--sources', default='sources.json')
    parser.add_argument('--state', default='state.json')
    parser.add_argument('--output', default='matches.json')
    parser.add_argument('--deliver', action='store_true')
    parser.add_argument('--destination', choices=['docs', 'sheets'], default=os.environ.get('DELIVERY_TARGET', 'docs'))
    args = parser.parse_args()
    profile = json.loads(Path(args.profile).read_text(encoding='utf-8') if args.profile else os.environ['PROFILE_JSON'])
    if not isinstance(profile.get('skills'), list) or not profile['skills']:
        raise ValueError('A nonempty resume-derived skills profile is required')
    state_path = Path(args.state)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    sources = json.loads(Path(args.sources).read_text())
    jobs, errors = collect(sources)
    save('run-status.json', {'sources': len(sources), 'jobs_fetched': len(jobs), 'source_errors': errors})
    if len(errors) == len(sources):
        raise RuntimeError('All sources failed; no delivery attempted')
    sink = None
    if args.deliver:
        if args.destination == 'sheets':
            from .sheets import GoogleSheet
            sink = GoogleSheet()
        else:
            from .docs import GoogleDoc
            sink = GoogleDoc()
    try:
        matches = process(jobs, profile, state, sink)
        save(args.output, matches)
    finally:
        save(args.state, state)
    print(f"Fetched {len(jobs)} postings; {len(matches)} matches; {len(errors)} source failures.")
    if errors:
        print('Source failures: ' + ', '.join(x['source'] for x in errors))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
