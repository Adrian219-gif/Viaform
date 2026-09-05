"""One query, one request per search edition, no extraction or page fetch."""
import json
import os
import time
from pathlib import Path
import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
QUERY = 'University of Oxford MSc Advanced Computer Science entry requirements'
key = os.getenv('DOUBAOSEARCH_API_KEY') or dotenv_values(ROOT/'backend/.env').get('DOUBAOSEARCH_API_KEY')
if not key:
    raise SystemExit('DOUBAOSEARCH_API_KEY missing')
report = {'query':QUERY,'domain_filter':'none for both editions','results':{}}
for edition, endpoint, body in [
    ('global','global_search',{'Query':QUERY,'SearchType':'web','DocCount':5}),
    ('custom','web_search',{'Query':QUERY,'SearchType':'web','Count':5}),
]:
    row = {'request':body,'requests':1,'endpoint':'https://open.feedcoopapi.com/search_api/'+endpoint}
    report['results'][edition] = row
    start = time.perf_counter()
    try:
        with httpx.Client(timeout=120,trust_env=False,follow_redirects=False) as client:
            response = client.post(row['endpoint'],json=body,headers={'Authorization':'Bearer '+key})
        row.update(latency_seconds=round(time.perf_counter()-start,3),http_status=response.status_code)
        response.raise_for_status()
        row['response'] = response.json()
    except Exception as error:
        row['error'] = type(error).__name__+': '+str(error)
    print(edition+' '+json.dumps({k:v for k,v in row.items() if k!='response'}).replace(key,'[REDACTED]'),flush=True)
(ROOT/'docs/evals/oxford_global_vs_custom.json').write_text(json.dumps(report,ensure_ascii=False,indent=2).replace(key,'[REDACTED]'),encoding='utf-8')
