"""Direct, free Google Docs API. No Composio subscription at runtime."""
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone


REFRESH_PREFIX = '[job-watch-refresh:'


def refresh_due(marker, now):
    if not marker:
        return True
    if not marker.startswith(REFRESH_PREFIX) or not marker.endswith(']'):
        raise ValueError('Invalid list refresh marker')
    previous = datetime.fromisoformat(marker[len(REFRESH_PREFIX):-1])
    if previous.tzinfo is None:
        raise ValueError('Refresh timestamp must include timezone')
    return now - previous >= timedelta(hours=24)


def request(url, payload=None, token=None, form=False):
    headers = {}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = None
    if payload is not None:
        data = (urllib.parse.urlencode(payload) if form else json.dumps(payload)).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=30) as response:
        return json.load(response)


def strings(value):
    if isinstance(value, dict):
        for k, v in value.items():
            if k == 'textRun':
                yield v.get('content', '')
            else:
                yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


def entry(job):
    lines = [f"\n{job['company']} — {job['title']}", f"Direct link: {job['url']}",
             f"Location: {job['location']}", f"Salary (employer text): {job['salary']}",
             'Experience requirement (employer text): ' + ' | '.join(job['experience_requirement']),
             'Matched keywords: ' + ', '.join(job['matched_keywords']),
             'Unmatched recognized keywords: ' + ', '.join(job['unmatched_keywords']),
             f"Fit: {job['fit_score']}% — {job['fit_basis']} (keyword coverage, not hiring probability)",
             'Visa sponsorship: ' + job['sponsorship_status'],
             'Evidence (employer text): ' + ' | '.join(job['sponsorship_evidence']),
             f"Evidence source: {job['url']} — checked {job['checked_at']}",
             'Posted: ' + (job['posted_at'] or 'Not supplied by source'),
             'First seen: ' + job['first_seen'],
             'Flags: ' + ('; '.join(job['flags']) or 'None'),
             job['application_status'], f"[job-watch:{job['key']}]\n"]
    return '\n'.join(lines)


class GoogleDoc:
    def __init__(self):
        self.document_id = os.environ['GOOGLE_DOC_ID']
        if not re.fullmatch(r'[\w-]+', self.document_id):
            raise ValueError('Invalid document ID')
        credentials = json.loads(os.environ['GOOGLE_OAUTH_JSON'])
        self.token = request('https://oauth2.googleapis.com/token', {
            'client_id': credentials['client_id'], 'client_secret': credentials['client_secret'],
            'refresh_token': credentials['refresh_token'], 'grant_type': 'refresh_token'}, form=True)['access_token']
        self.url = 'https://docs.googleapis.com/v1/documents/' + self.document_id

    def read(self):
        doc = request(self.url + '?includeTabsContent=true', token=self.token)
        text = ''.join(strings(doc))
        return doc['revisionId'], set(re.findall(r'\[job-watch:([a-f0-9]{64})\]', text))

    def refresh(self, now=None):
        now = now or datetime.now(timezone.utc)
        doc = request(self.url, token=self.token)
        if 'body' not in doc:
            raise ValueError('Default document body unavailable; refusing to reset')
        # Work only on the default tab's ordinary paragraphs, retaining headings
        # and other user content. Google Docs indices count UTF-16 code units.
        text, positions = '', []
        for element in doc.get('body', {}).get('content', []):
            for part in element.get('paragraph', {}).get('elements', []):
                value = part.get('textRun', {}).get('content', '')
                index = part.get('startIndex', element.get('startIndex', 1))
                for char in value:
                    text += char
                    positions.append(index)
                    index += len(char.encode('utf-16-le')) // 2
        markers = list(re.finditer(r'\[job-watch-refresh:[^\]\n]+\]', text))
        if len(markers) > 1:
            raise ValueError('Multiple list refresh markers')
        if not refresh_due(markers[0].group() if markers else '', now):
            return
        entries = list(re.finditer(
            r'(?m)^[^\n]+ — [^\n]+\nDirect link: https://[^\n]+\nLocation: '
            r'[\s\S]*?\[job-watch:[a-f0-9]{64}\]', text))
        if len(entries) != len(re.findall(r'\[job-watch:[a-f0-9]{64}\]', ''.join(strings(doc)))):
            raise ValueError('Cannot safely identify all generated job entries')
        requests = []
        for match in sorted(entries + markers, key=lambda m: m.start(), reverse=True):
            requests.append({'deleteContentRange': {'range': {
                'startIndex': positions[match.start()],
                'endIndex': positions[match.end() - 1] + 1}}})
        requests.append({'insertText': {'location': {'index': 1},
                         'text': REFRESH_PREFIX + now.isoformat() + ']\n'}})
        request(self.url + ':batchUpdate', {'writeControl': {'requiredRevisionId': doc['revisionId']},
                                           'requests': requests}, token=self.token)

    def append(self, jobs):
        # Read the durable document ledger before each batch. A crashed run can recover
        # even if Git state was not saved. Revision preconditions prevent racing writers.
        revision, seen = self.read()
        pending = [j for j in jobs if j['key'] not in seen]
        if pending:
            request(self.url + ':batchUpdate', {
                'writeControl': {'requiredRevisionId': revision},
                'requests': [{'insertText': {'location': {'index': 1},
                                            'text': ''.join(entry(j) for j in pending)}}]}, token=self.token)
        # Do not retry uncertain POSTs. Next run reconciles markers before writing.
        return {j['key'] for j in jobs}
