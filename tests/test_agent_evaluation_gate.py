import importlib.util,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('eval_gate',ROOT/'scripts/verify_agent_evaluation.py')
gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)

def test_declared_outputs_and_review_hash_are_required(tmp_path):
 case=tmp_path/'run-1/01-create';case.mkdir(parents=True)
 def write(name,data):
  p=case/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data),encoding='utf-8')
 write('plan.json',{'segs':[],'stages':[{'id':'planning','outputs':['planning.md']},{'id':'review','skill':'drama-production-review','outputs':['checks/review.json']}]})
 write('result.json',{'status':'passed','evidence':['plan.json'],'next_action':'deliver','deliverable':True})
 text='Two characters negotiate a debt; conflict, reversal, and final hook.'
 (case/'planning.md').write_text(text,encoding='utf-8')
 first=gate.verify(tmp_path)['results'][0]
 assert not first['passed'] and any('missing required' in x for x in first['errors'])
 review={'status':'passed','artifact_path':'planning.md','artifact_sha256':'wrong','evidence':['planning.md']}
 write('checks/review.json',review)
 assert any('not bound' in x for x in gate.verify(tmp_path)['results'][0]['errors'])
 review['artifact_sha256']=hashlib.sha256(text.encode()).hexdigest();write('checks/review.json',review)
 assert gate.verify(tmp_path)['results'][0]['passed']
