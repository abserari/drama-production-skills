"""Expand immutable evaluation inputs into separate fresh agent workspaces."""
import argparse
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def prepare(target):
 target=Path(target)
 if target.exists() and any(target.iterdir()):raise ValueError('Use a fresh empty directory; never overwrite evaluation evidence')
 cases=json.loads((ROOT/'examples/agent-evaluation/input-cases.json').read_text(encoding='utf-8'))
 for repeat in range(1,4):
  for case in cases:
   base=target/f'run-{repeat}'/case['id'];base.mkdir(parents=True,exist_ok=True)
   (base/'task.md').write_text(case['task'],encoding='utf-8')
   for key,value in case.items():
    if key not in ('id','task','files'):(base/(key+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
   for relative,content in case.get('files',{}).items():
    path=base/relative
    if base.resolve() not in path.resolve().parents:raise ValueError('Fixture path escapes case')
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content,encoding='utf-8')
 return target
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('target',type=Path);a=p.parse_args();print(prepare(a.target))
