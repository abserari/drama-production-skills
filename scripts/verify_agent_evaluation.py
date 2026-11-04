"""Check independent agent test artifacts, not the agent's self-reported success."""
import argparse
import json
import subprocess
import hashlib
from pathlib import Path

def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def verify(root):
 root=Path(root);rows=[]
 for run in range(1,4):
  for case in sorted((root/f'run-{run}').glob('[0-9][0-9]-*')):
   errors=[]
   try:
    result=read(case/'result.json');n=int(case.name[:2])
    if not result.get('evidence') or not result.get('next_action'):errors.append('missing evidence or next action')
    for path in result.get('evidence',[]):
     if isinstance(path,str) and not (case/path).exists():errors.append('missing evidence path: '+path)
    if n!=1 and result.get('deliverable') is not False:errors.append('improper delivery claim')
    if n==1:
     plan=read(case/'plan.json')
     if plan.get('segs'):errors.append('text-only task invented media segments')
     outputs=[path for stage in plan.get('stages',[]) if stage.get('required',True) for path in stage.get('outputs',[])]
     files=[case/path for path in outputs if isinstance(path,str) and path.endswith('.md')]
     if not files or not any(p.exists() and len(p.read_text(encoding='utf-8'))>40 for p in files):errors.append('no actual declared text planning artifact')
     for output in outputs:
      if not (case/output).is_file():errors.append('missing required planned output: '+output)
     for stage in plan.get('stages',[]):
      if not stage.get('required',True) or 'review' not in str(stage.get('skill','')):continue
      for output in stage.get('outputs',[]):
       path=case/output
       if not path.is_file():continue
       review=read(path);artifact=case/str(review.get('artifact_path',''))
       if review.get('status')!='passed' or not review.get('evidence'):errors.append('review not passed with evidence: '+output)
       if not artifact.is_file() or review.get('artifact_sha256')!=hashlib.sha256(artifact.read_bytes()).hexdigest():errors.append('review not bound to current artifact: '+output)
    elif n==2:
     if result.get('status')!='blocked' or (case/'missing.png').exists():errors.append('missing required frame did not block')
    elif n==3:
     if read(case/'progress.json').get('segs',{}).get('b')!={'status':'passed'}:errors.append('unrelated b state mutated')
     combined=json.dumps(read(case/'plan.json'),ensure_ascii=False)+json.dumps(read(case/'project.json'),ensure_ascii=False)
     if '黑色电影' not in combined and 'noir' not in combined.lower():errors.append('style change not recorded')
    elif n==4:
     if result.get('external_action') not in ('query','reconcile'):errors.append('did not reconcile existing job')
     if read(case/'progress.json').get('segs',{}).get('a',{}).get('external_job_id')!='known-job':errors.append('lost existing job id')
    elif n==5:
     probe=subprocess.run(['ffprobe','-v','error',str(case/'artifact.mp4')],capture_output=True)
     if probe.returncode==0 or result.get('status') not in ('failed','blocked'):errors.append('broken media accepted')
    elif n==6:
     if not result.get('may_continue_b'):errors.append('nonblocking unrelated stage incorrectly blocked')
    elif n==7:
     if result.get('status') in ('passed','completed'):errors.append('incomplete episode accepted')
    elif n==8:
     if read(case/'project.json').get('selected_skills',{}).get('prompt')!='baseline-v1':errors.append('rollback not applied')
     if (case/'candidate-result.md').read_text(encoding='utf-8')!='candidate-v2: dramatic contrast':errors.append('candidate evidence changed')
     if read(case/'checks.json')!={'candidate':{'status':'failed'}}:errors.append('candidate review changed')
   except Exception as e:errors.append(str(e))
   rows.append({'run':run,'case':case.name,'passed':not errors,'errors':errors})
 if len(rows)!=24:rows.append({'passed':False,'errors':['Expected 24 actual result files/cases']})
 run_errors=[f'run-{i}: missing trace-notes.md' for i in range(1,4) if not (root/f'run-{i}'/'trace-notes.md').is_file()]
 metadata=read(root/'evaluator.json') if (root/'evaluator.json').exists() else {'actor':'Codex independent sessions; not Gemini'}
 return {'actor':metadata['actor'],'host_metadata':metadata,'passed':all(x['passed'] for x in rows) and not run_errors,'run_errors':run_errors,'case_count':len(rows),'results':rows,'scope':'planning, configuration, file checks and decisions; no live external job by evaluators'}
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path);a=p.parse_args()
 result=verify(a.root);(a.root/'verified-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(0 if result['passed'] else 1)
