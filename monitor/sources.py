import concurrent.futures
import json
import re
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from .core import plain, canonical_url


def get_json(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'HourlyJobWatch/1.0 (public job-board reader)'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (TimeoutError, urllib.error.URLError):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)


def fetch(source, get=get_json):
    provider, board = source['provider'], source['board']
    if not re.fullmatch(r'[A-Za-z0-9_-]+', board):
        raise ValueError('Invalid board')
    if provider == 'greenhouse':
        raw = get(f'https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true')['jobs']
    elif provider == 'ashby':
        raw = get(f'https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true')['jobs']
    elif provider == 'lever':
        raw = []
        for skip in range(0, 10000, 100):
            batch = get(f'https://api.lever.co/v0/postings/{board}?mode=json&limit=100&skip={skip}')
            raw.extend(batch)
            if len(batch) < 100:
                break
        else:
            raise RuntimeError('Lever pagination limit reached; refusing incomplete source')
    else:
        raise ValueError('Unsupported source')
    jobs = []
    for j in raw:
        if provider == 'greenhouse':
            title, url, location = j['title'], j['absolute_url'], j['location']['name']
            description = plain(j.get('content', ''))
            country, posted = '', j.get('first_published')
            salary = None
        elif provider == 'ashby':
            if not j.get('isListed', True) or j.get('employmentType') == 'Intern':
                continue
            title, url, location = j['title'], j['jobUrl'], j.get('location', '')
            description = j.get('descriptionPlain') or plain(j.get('descriptionHtml', ''))
            country = (j.get('address') or {}).get('postalAddress', {}).get('addressCountry', '')
            posted = j.get('publishedAt')
            salary = (j.get('compensation') or {}).get('scrapeableCompensationSalarySummary')
        else:
            title, url, location = j['text'], j['hostedUrl'], j.get('categories', {}).get('location', '')
            description = plain(j.get('description', '') + '\n' + '\n'.join(
                x.get('text', '') + '\n' + x.get('content', '') for x in j.get('lists', [])) + '\n' + j.get('additional', ''))
            country = j.get('country', '')
            posted = datetime.fromtimestamp(j['createdAt'] / 1000, timezone.utc).isoformat() if j.get('createdAt') else None
            salary = json.dumps(j['salaryRange']) if j.get('salaryRange') else None
        salary_lines = [x for x in description.splitlines() if re.search(r'\$\s*[\d,]+|USD\s*[\d,]+', x)]
        jobs.append(dict(id=str(j.get('id') or canonical_url(url)), source=provider, board=board,
                         company=source['company'], title=title, url=canonical_url(url),
                         location=location, country=country, description=description,
                         salary=salary or '\n'.join(salary_lines) or 'Not stated in fetched posting.',
                         posted_at=posted, source_updated_at=j.get('updated_at')))
    return jobs


def collect(sources):
    jobs, errors = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch, s): s for s in sources}
        for future in concurrent.futures.as_completed(futures):
            source = futures[future]
            try:
                jobs.extend(future.result())
            except Exception as exc:
                errors.append({'source': source['board'], 'error': type(exc).__name__})
    return jobs, errors
