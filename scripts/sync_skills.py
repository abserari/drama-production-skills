"""Publish canonical skills to a workspace; check by default, never delete files."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {'__pycache__', '.pytest_cache', 'checks'}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def sync(target, apply=False):
    source = ROOT / 'skills'
    target = Path(target).resolve()
    if target == source or source in target.parents or target in source.parents:
        raise ValueError('Source and publication directory must be separate')
    changes = []
    for path in sorted(source.rglob('*')):
        rel = path.relative_to(source)
        if not path.is_file() or any(p in IGNORED for p in rel.parts) or path.suffix == '.pyc':
            continue
        destination = target / rel
        if not destination.exists() or digest(path) != digest(destination):
            changes.append(str(rel))
            if apply:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
    return changes

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, default=ROOT.parent / '.agents' / 'skills')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    changes = sync(args.target, args.apply)
    print(json.dumps({'mode': 'publish' if args.apply else 'check', 'changed': changes}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if args.apply or not changes else 1)
