"""Replay KTH stopping request once; only reasoning high -> low changes."""
import copy
import hashlib
import json
import os
import time
from collections import Counter
from pathlib import Path
import httpx
from dotenv import dotenv_values
from pydantic import ValidationError
from experiment_responses_requirements import Requirements, forensic_output

ROOT = Path(__file__).resolve().parents[2]
source = ROOT / 'docs/evals/deepseek_responses_kth_stopping_live.json'
baseline_bytes = source.read_bytes()
original = json.loads(baseline_bytes)['results'][0]['request_payload']
request = copy.deepcopy(original)
assert request['reasoning'] == {'effort': 'high'}
request['reasoning'] = {'effort': 'low'}
assert {k:v for k,v in original.items() if k != 'reasoning'} == {k:v for k,v in request.items() if k != 'reasoning'}
assert request['text']['format']['schema'] == Requirements.model_json_schema()
assert request['tools'] == [{'type':'web_search'}] and request['tool_choice'] == 'auto'
key = os.getenv('DEEPSEEK_API_KEY') or dotenv_values(ROOT / 'backend/.env').get('DEEPSEEK_API_KEY')
if not key:
    raise SystemExit('DEEPSEEK_API_KEY missing')
report = {'case':'kth', 'request_payload':request, 'deepseek_http_requests':1,
          'baseline_sha256':hashlib.sha256(baseline_bytes).hexdigest(), 'only_reasoning_changed':True}
print('PASS: only reasoning high -> low; one request starting', flush=True)
start = time.perf_counter()
try:
    with httpx.Client(timeout=600, trust_env=False, follow_redirects=False) as client:
        response = client.post('https://api.deepseek.com/responses', json=request, headers={'Authorization':'Bearer '+key})
    report.update(total_seconds=round(time.perf_counter()-start,3), http_status=response.status_code)
    response.raise_for_status()
    body = response.json()
    output = body.get('output',[])
    calls = [x for x in output if x.get('type') == 'web_search_call']
    messages = [''.join(p.get('text','') for p in x.get('content',[]) if p.get('type') == 'output_text') for x in output if x.get('type') == 'message']
    answer = messages[-1] if messages else ''
    report.update(response_id=body.get('id'), status=body.get('status'), usage=body.get('usage'),
                  web_search_call_count=len(calls), web_search_calls=calls,
                  tool_actions=dict(Counter(x.get('action',{}).get('type','unknown') for x in calls)),
                  message_texts=messages, output_text=answer)
    try:
        parsed = Requirements.model_validate_json(answer)
        report.update(schema_valid=True, result=parsed.model_dump(), requirement_count=len(parsed.requirements))
    except ValidationError as error:
        report.update(schema_valid=False, validation_error=str(error), posthoc_output_audit=forensic_output(report))
except Exception as error:
    report['error'] = type(error).__name__+': '+str(error)
report['baseline_unchanged'] = source.read_bytes() == baseline_bytes
content = json.dumps(report,ensure_ascii=False,indent=2).replace(key,'[REDACTED]')
(ROOT / 'docs/evals/deepseek_responses_kth_stopping_low.json').write_text(content,encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k not in {'request_payload','result','output_text','message_texts','web_search_calls','posthoc_output_audit'}},ensure_ascii=False).replace(key,'[REDACTED]'))
