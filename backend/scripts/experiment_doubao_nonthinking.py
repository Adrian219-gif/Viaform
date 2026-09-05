"""Replay saved KTH extraction once, changing only reasoning.effort to none."""
import argparse
import copy
import hashlib
import json
import os
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values
from pydantic import ValidationError
from experiment_doubao_requirements import ROOT, extraction_model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    source = ROOT / 'docs/evals/doubao_custom_kth.json'
    baseline_bytes = source.read_bytes()
    baseline = json.loads(baseline_bytes)
    original = baseline['extraction']['request_payload']
    request = copy.deepcopy(original)
    assert original['reasoning'] == {'effort': 'high'}
    request['reasoning'] = {'effort': 'none'}
    assert request['model'] == 'deepseek-v4-flash'
    assert request['tools'] == [] and request['tool_choice'] == 'none'
    assert {k:v for k,v in request.items() if k != 'reasoning'} == {k:v for k,v in original.items() if k != 'reasoning'}
    model = extraction_model()
    assert model.model_json_schema() == request['text']['format']['schema']
    if args.check:
        print('PASS: only reasoning differs; identical prompt, evidence, schema; no search')
        return
    key = os.getenv('DEEPSEEK_API_KEY') or dotenv_values(ROOT / 'backend/.env').get('DEEPSEEK_API_KEY')
    if not key:
        raise SystemExit('DEEPSEEK_API_KEY missing')
    report = {'baseline_sha256': hashlib.sha256(baseline_bytes).hexdigest(),
              'input_sha256': hashlib.sha256(request['input'].encode()).hexdigest(),
              'request_payload': request, 'doubao_requests': 0, 'deepseek_requests': 1}
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=600, trust_env=False, follow_redirects=False) as client:
            response = client.post('https://api.deepseek.com/responses', json=request,
                                   headers={'Authorization': 'Bearer ' + key})
        report.update(extraction_seconds=round(time.perf_counter()-started, 3), http_status=response.status_code)
        response.raise_for_status()
        body = response.json()
        output = body.get('output', [])
        messages = [''.join(p.get('text','') for p in item.get('content',[]) if p.get('type') == 'output_text')
                    for item in output if item.get('type') == 'message']
        answer = messages[-1] if messages else ''
        report.update(response_id=body.get('id'), status=body.get('status'), usage=body.get('usage'),
                      output_item_types=[x.get('type') for x in output], output_text=answer)
        try:
            parsed = model.model_validate_json(answer)
            report.update(schema_valid=True, result=parsed.model_dump(), requirement_count=len(parsed.requirements))
        except ValidationError as error:
            report.update(schema_valid=False, validation_error=str(error))
    except Exception as error:
        report['error'] = type(error).__name__ + ': ' + str(error)
    report['baseline_unchanged'] = source.read_bytes() == baseline_bytes
    content = json.dumps(report, ensure_ascii=False, indent=2).replace(key, '[REDACTED]')
    destination = ROOT / 'docs/evals/doubao_custom_kth_nonthinking.json'
    destination.write_text(content, encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'request_payload','output_text','result'}}, ensure_ascii=False).replace(key,'[REDACTED]'))


if __name__ == '__main__':
    main()
