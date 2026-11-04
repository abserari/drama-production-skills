"""Read-only source import: copy plans/prompts, inventory media, never approve it."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)

def import_project(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if target == source or source in target.parents or target in source.parents:
        raise ValueError('Import must use a separate project directory')
    production = source / '生产' if (source / '生产').is_dir() else source
    plans = list(dict.fromkeys(p for p in [source / 'plan.json', production / 'plan.json'] if p.exists()))
    if not plans:
        raise ValueError('No plan.json found')
    contents = [read(p) for p in plans]
    provenance = {str(p): sha(p) for p in plans}
    if any(p != contents[0] for p in contents[1:]):
        write(target / 'checks' / 'import-conflict.json', {'status': 'blocked', 'sources': provenance,
              'reason': 'Plans differ; compare both sources before selecting a new project plan'})
        return {'status': 'blocked', 'sources': provenance}
    marker = target / 'checks' / 'import.json'
    if marker.exists():
        previous = read(marker)
        if previous.get('sources') != provenance:
            raise ValueError('Source changed after import; use a new destination or review migration')
        return previous
    if any((target / name).exists() for name in ['project.json', 'plan.json', 'progress.json']):
        raise ValueError('Destination already contains project files; refusing overwrite')
    plan = contents[0]
    segs = plan.get('segs', [])
    ids = [s['seg'] for s in segs]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate segment IDs')
    project = read(production / 'project.json') if (production / 'project.json').exists() else {}
    project.update({'schema_version': 1, 'source_project': str(source), 'production_path': 'legacy_import',
                    'status': 'awaiting_review', 'skills': {}, 'review_policy': {'sample_rate': 0.2, 'seed': 42}})
    write(target / 'project.json', project)
    write(target / 'plan.json', plan)
    if (production / 'prompts').exists():
        shutil.copytree(production / 'prompts', target / 'prompts', dirs_exist_ok=True)
    media = []
    for folder in ['segments', 'refined_segments', 'cleaned_segments', 'references', '成片']:
        if not (production / folder).is_dir():
            continue
        for p in sorted((production / folder).rglob('*')):
            if p.is_file():
                media.append({'path': str(p), 'sha256': sha(p), 'size': p.stat().st_size,
                              'status': 'imported_unverified'})
    write(target / 'progress.json', {'schema_version': 1, 'segs': {s: {'status': 'awaiting_review',
          'attempts': 0, 'next_action': 'verify imported artifacts and production path'} for s in ids}})
    write(target / 'checks' / 'imported-artifacts.json', {'artifacts': media})
    report = {'status': 'imported_unverified', 'sources': provenance, 'segment_count': len(ids),
              'artifact_count': len(media), 'source_mutated': False}
    write(marker, report)
    return report

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    args = parser.parse_args()
    result = import_project(args.source, args.target)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(2 if result['status'] == 'blocked' else 0)
