"""Bounded staged experiment: explicit search rounds, then one low extraction.

Search evidence is inspected between rounds. Never retries or loads application.
"""
import argparse
import copy
import json
import os
import time
from pathlib import Path
import httpx
from dotenv import dotenv_values
from pydantic import ValidationError
from experiment_doubao_requirements import ROOT, SEARCH_URL, SEARCH_BODY, official, extraction_model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['search','extract'])
    parser.add_argument('--query', default=SEARCH_BODY['Query'])
    parser.add_argument('--reason', required=True)
    parser.add_argument('--oxford-none', action='store_true')
    args = parser.parse_args()
    domain = 'ox.ac.uk' if args.oxford_none else 'kth.se'
    path = ROOT / ('docs/evals/doubao_three_none_oxford.json' if args.oxford_none else 'docs/evals/doubao_three_low_kth.json')
    report = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'search_rounds':[], 'extraction':None}
    env = dotenv_values(ROOT / 'backend/.env')
    names = ['DOUBAOSEARCH_API_KEY','DEEPSEEK_API_KEY']
    keys = [os.getenv(n) or env.get(n) for n in names]
    if not all(keys):
        raise SystemExit('Required API key missing')
    try:
        with httpx.Client(timeout=600,trust_env=False,follow_redirects=False) as client:
            if args.stage == 'search':
                assert len(report['search_rounds']) < 3 and report['extraction'] is None
                assert 0 < len(args.query) <= 100
                body = copy.deepcopy(SEARCH_BODY)
                body['Query'] = args.query
                body['Filter']['Sites'] = domain
                row = {'query':args.query, 'reason_for_search':args.reason, 'request_body':body}
                report['search_rounds'].append(row)
                start = time.perf_counter()
                response = client.post(SEARCH_URL,json=body,headers={'Authorization':'Bearer '+keys[0]})
                row.update(latency_seconds=round(time.perf_counter()-start,3),http_status=response.status_code)
                response.raise_for_status()
                result = response.json()
                row['response'] = result
                if result.get('ResponseMetadata',{}).get('Error'):
                    raise ValueError('Search API application error; no automatic recovery')
                rows = (result.get('Result') or {}).get('WebResults') or []
                row.update(result_count=len(rows),official_count=sum(official(r.get('Url'),domain) for r in rows))
                print(json.dumps({k:v for k,v in row.items() if k!='response'},ensure_ascii=False))
            else:
                assert report['search_rounds'] and report['extraction'] is None
                # No baseline answers are read: only the saved extraction request template.
                saved = json.loads((ROOT/'docs/evals/doubao_custom_kth.json').read_text(encoding='utf-8'))['extraction']['request_payload']
                evidence = []
                seen = set()
                for round_ in report['search_rounds']:
                    for row in (round_.get('response',{}).get('Result') or {}).get('WebResults') or []:
                        url = row.get('Url')
                        if official(url,domain) and url not in seen:
                            seen.add(url)
                            evidence.append({k:row.get(k) for k in ('Title','Url','Summary','Content','Snippet','RankScore','SortId','ContentFormats','PublishTime')})
                serialized = json.dumps(evidence,ensure_ascii=False)
                request = copy.deepcopy(saved)
                prefix = saved['input'].split('EVIDENCE:\n',1)[0]
                if args.oxford_none:
                    prefix = prefix.replace("KTH Master's Programme in Computer Science",'University of Oxford MSc Advanced Computer Science').replace('kth.se','ox.ac.uk')
                request['input'] = prefix+'EVIDENCE:\n'+serialized
                request['reasoning'] = {'effort':'none' if args.oxford_none else 'low'}
                model = extraction_model()
                assert model.model_json_schema() == request['text']['format']['schema']
                assert request['tools'] == [] and request['tool_choice'] == 'none'
                report.update(stop_reason=args.reason,evidence_count=len(evidence),evidence_json_chars=len(serialized),
                              evidence_json_bytes=len(serialized.encode()), evidence_text_chars=sum(len(r.get(k) or '') for r in evidence for k in ('Title','Summary','Content','Snippet')))
                extraction = {'requests':1,'request_payload':request}
                report['extraction'] = extraction
                start = time.perf_counter()
                response = client.post('https://api.deepseek.com/responses',json=request,headers={'Authorization':'Bearer '+keys[1]})
                extraction.update(latency_seconds=round(time.perf_counter()-start,3),http_status=response.status_code)
                response.raise_for_status()
                result = response.json()
                output = result.get('output',[])
                messages = [''.join(p.get('text','') for p in x.get('content',[]) if p.get('type')=='output_text') for x in output if x.get('type')=='message']
                answer = messages[-1] if messages else ''
                extraction.update(usage=result.get('usage'),status=result.get('status'),response_id=result.get('id'),output_text=answer,
                                  web_search_calls=sum(x.get('type')=='web_search_call' for x in output))
                try:
                    parsed = model.model_validate_json(answer)
                    extraction.update(schema_valid=True,result=parsed.model_dump(),requirement_count=len(parsed.requirements))
                except ValidationError as error:
                    extraction.update(schema_valid=False,validation_error=str(error))
                print(json.dumps({k:v for k,v in extraction.items() if k not in {'request_payload','output_text','result'}},ensure_ascii=False))
    except Exception as error:
        report['error'] = type(error).__name__+': '+str(error)
    finally:
        report['retrieval_seconds'] = round(sum(r.get('latency_seconds',0) for r in report['search_rounds']),3)
        report['active_api_total_seconds'] = round(report['retrieval_seconds']+(report.get('extraction') or {}).get('latency_seconds',0),3)
        content = json.dumps(report,ensure_ascii=False,indent=2)
        for key in keys:
            content = content.replace(key,'[REDACTED]')
        path.write_text(content,encoding='utf-8')


if __name__ == '__main__':
    main()
