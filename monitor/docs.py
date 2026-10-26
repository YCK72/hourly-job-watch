"""Direct, free Google Docs API. No Composio subscription at runtime."""
import json
import os
import re
import urllib.parse
import urllib.request


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

    def append(self, jobs):
        # Read the durable document ledger before each batch. A crashed run can recover
        # even if Git state was not saved. Revision preconditions prevent racing writers.
        revision, seen = self.read()
        pending = [j for j in jobs if j['key'] not in seen]
        if pending:
            request(self.url + ':batchUpdate', {
                'writeControl': {'requiredRevisionId': revision},
                'requests': [{'insertText': {'endOfSegmentLocation': {},
                                            'text': ''.join(entry(j) for j in pending)}}]}, token=self.token)
        # Do not retry uncertain POSTs. Next run reconciles markers before writing.
        return {j['key'] for j in jobs}
