"""One Global discovery, allowlisted live fetch, one none extraction."""
import copy
import json
import os
import time
from urllib.parse import urlparse, urljoin
import httpx
from html.parser import HTMLParser
from dotenv import dotenv_values
from pydantic import ValidationError
from experiment_doubao_requirements import ROOT, extraction_model


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skipped = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script','style','noscript','svg'):
            self.skipped += 1
    def handle_endtag(self, tag):
        if tag in ('script','style','noscript','svg') and self.skipped:
            self.skipped -= 1
    def handle_data(self, data):
        if not self.skipped and data.strip():
            self.parts.append(data.strip())


def allowed(url):
    p = urlparse(url)
    h = (p.hostname or '').lower()
    return p.scheme == 'https' and (h == 'ox.ac.uk' or h.endswith('.ox.ac.uk')) and not p.username and not p.password and p.port in (None,443)


def main():
    start = time.perf_counter()
    env = dotenv_values(ROOT/'backend/.env')
    keys = [os.getenv(n) or env.get(n) for n in ('DOUBAOSEARCH_API_KEY','DEEPSEEK_API_KEY')]
    if not all(keys):
        raise SystemExit('Required key missing')
    report = {'search':{},'fetch':{},'extraction':{},'retries':0}
    stage = 'search'
    try:
        with httpx.Client(timeout=120,trust_env=False,follow_redirects=False) as client:
            body = {'Query':'University of Oxford MSc Advanced Computer Science entry requirements','SearchType':'web','DocCount':5}
            report[stage]['request'] = body
            t = time.perf_counter()
            response = client.post('https://open.feedcoopapi.com/search_api/global_search',json=body,headers={'Authorization':'Bearer '+keys[0]})
            report[stage].update(latency_seconds=round(time.perf_counter()-t,3),http_status=response.status_code,requests=1)
            response.raise_for_status()
            result = response.json()
            report[stage]['response'] = result
            docs = (result.get('Result') or {}).get('Documents') or []
            hits = [(i+1,d) for i,d in enumerate(docs) if allowed(d.get('Url','')) and urlparse(d['Url']).path.rstrip('/') == '/admissions/graduate/courses/msc-advanced-computer-science']
            report[stage]['exact_found'] = bool(hits)
            if not hits:
                raise ValueError('No exact official admissions URL in Global results; stopping')
            rank, doc = hits[0]
            url = doc['Url']
            report[stage].update(rank=rank,url=url)
            stage = 'fetch'
            t = time.perf_counter()
            hops = []
            for _ in range(6):
                if not allowed(url):
                    raise ValueError('Redirect URL outside official HTTPS allowlist')
                response = client.get(url,headers={'User-Agent':'Viaform-independent-retrieval-eval/1.0','Cache-Control':'no-cache'})
                hops.append({'url':url,'status':response.status_code})
                if response.status_code in (301,302,303,307,308):
                    url = urljoin(url,response.headers['Location'])
                    continue
                break
            else:
                raise ValueError('Redirect limit reached')
            report[stage].update(latency_seconds=round(time.perf_counter()-t,3),final_url=str(response.url),http_status=response.status_code,hops=hops,
                                 headers={k:response.headers.get(k) for k in ('date','last-modified','age','cache-control','etag')})
            response.raise_for_status()
            parser = PageText()
            parser.feed(response.text)
            text = '\n'.join(parser.parts)
            report[stage].update(body_text=text,body_chars=len(text),html_bytes=len(response.content),entry_heading='Entry requirements' in text,
                                 supporting_heading='Supporting documents' in text)
            print('LIVE_FETCH '+json.dumps({k:v for k,v in report[stage].items() if k not in ('body_text','headers','hops')}),flush=True)
            model = extraction_model()
            saved = json.loads((ROOT/'docs/evals/doubao_custom_oxford_nonthinking.json').read_text(encoding='utf-8'))['extraction']['request_payload']
            request = copy.deepcopy(saved)
            evidence = [{'Title':doc.get('Title'),'Url':str(response.url),'Content':text}]
            request['input'] = saved['input'].split('EVIDENCE:\n',1)[0]+'EVIDENCE:\n'+json.dumps(evidence,ensure_ascii=False)
            assert request['reasoning'] == {'effort':'none'} and request['tools'] == []
            assert request['text']['format']['schema'] == model.model_json_schema()
            stage = 'extraction'
            report[stage]['request_payload'] = request
            t = time.perf_counter()
            response = client.post('https://api.deepseek.com/responses',json=request,headers={'Authorization':'Bearer '+keys[1]})
            report[stage].update(latency_seconds=round(time.perf_counter()-t,3),http_status=response.status_code,requests=1)
            response.raise_for_status()
            result = response.json()
            output = result.get('output',[])
            messages = [''.join(p.get('text','') for p in x.get('content',[]) if p.get('type')=='output_text') for x in output if x.get('type')=='message']
            answer = messages[-1] if messages else ''
            report[stage].update(status=result.get('status'),usage=result.get('usage'),output_text=answer,response_id=result.get('id'))
            try:
                parsed = model.model_validate_json(answer)
                report[stage].update(schema_valid=True,result=parsed.model_dump(),requirement_count=len(parsed.requirements))
            except ValidationError as error:
                report[stage].update(schema_valid=False,validation_error=str(error))
    except Exception as error:
        report[stage]['error'] = type(error).__name__+': '+str(error)
    report['wall_clock_seconds'] = round(time.perf_counter()-start,3)
    content = json.dumps(report,ensure_ascii=False,indent=2)
    for key in keys:
        content = content.replace(key,'[REDACTED]')
    (ROOT/'docs/evals/global_live_oxford.json').write_text(content,encoding='utf-8')
    print(json.dumps({'wall_clock_seconds':report['wall_clock_seconds'],'extraction':{k:v for k,v in report['extraction'].items() if k not in ('request_payload','result','output_text')}},ensure_ascii=False))


if __name__ == '__main__':
    main()
