"""Daily Google Sheets batches with archived notes and literal employer text."""
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import quote
from .docs import request, refresh_due, REFRESH_PREFIX

HEADERS = ['Company', 'Role', 'Fit', 'Visa sponsorship', 'Location', 'Posted date',
           'First seen (UTC)', 'Direct link', 'Experience requirement — exact text',
           'Salary — employer text', 'Matched keywords', 'Unmatched keywords',
           'Sponsorship evidence', 'Review flags', 'Checked (UTC)', 'Application status',
           'My notes', 'Job ID', 'Fit calculation', 'Evidence source']


def date_serial(value):
    if not value:
        return ''
    date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    return (date.astimezone(timezone.utc) - datetime(1899, 12, 30, tzinfo=timezone.utc)).total_seconds() / 86400


def row(job):
    return [job['company'], job['title'], job['fit_score'] / 100,
            job['sponsorship_status'], job['location'], date_serial(job.get('posted_at')),
            date_serial(job['first_seen']), job['url'], '\n'.join(job['experience_requirement']),
            job['salary'], ', '.join(job['matched_keywords']), ', '.join(job['unmatched_keywords']),
            '\n'.join(job['sponsorship_evidence']), '\n'.join(job['flags']),
            date_serial(job['checked_at']), job['application_status'], '', job['key'],
            job['fit_basis'], job['url']]


class GoogleSheet:
    def __init__(self):
        self.spreadsheet_id = os.environ['GOOGLE_SHEET_ID']
        if not re.fullmatch(r'[\w-]+', self.spreadsheet_id):
            raise ValueError('Invalid spreadsheet ID')
        self.delivery_key = 'sheets:' + hashlib.sha256(self.spreadsheet_id.encode()).hexdigest()
        credentials = json.loads(os.environ['GOOGLE_OAUTH_JSON'])
        self.token = request('https://oauth2.googleapis.com/token', {
            'client_id': credentials['client_id'], 'client_secret': credentials['client_secret'],
            'refresh_token': credentials['refresh_token'], 'grant_type': 'refresh_token'}, form=True)['access_token']
        self.url = 'https://sheets.googleapis.com/v4/spreadsheets/' + self.spreadsheet_id

    def read(self):
        data = request(self.url + '/values/' + quote("'Jobs'!A5:T", safe='') +
                       '?valueRenderOption=UNFORMATTED_VALUE', token=self.token)
        values = data.get('values', [])
        if not values or values[0] != HEADERS:
            raise ValueError('Jobs header row changed; refusing to append into unknown columns')
        seen = set()
        self.row_numbers = {}
        for index, value in enumerate(values[1:], start=6):
            if len(value) > 17 and re.fullmatch(r'[a-f0-9]{64}', str(value[17])):
                key = str(value[17])
                if key in seen:
                    raise ValueError('Duplicate job IDs found in sheet; review before continuing')
                seen.add(key)
                self.row_numbers[key] = index
            elif any(value):
                raise ValueError('Existing job row has no valid Job ID; restore ID before delivery')
        return seen

    def sheet_metadata(self):
        metadata = request(self.url + '?fields=sheets(properties,developerMetadata)', token=self.token)
        return next(s for s in metadata['sheets'] if s['properties']['title'] == 'Jobs')

    def refresh(self, now=None):
        now = now or datetime.now(timezone.utc)
        self.read()
        sheet = self.sheet_metadata()
        sheet_id = sheet['properties']['sheetId']
        markers = [m for m in sheet.get('developerMetadata', [])
                   if m['metadataKey'] == 'job_watch_refresh']
        if len(markers) > 1:
            raise ValueError('Multiple list refresh markers')
        if not refresh_due(markers[0]['metadataValue'] if markers else '', now):
            return
        marker = REFRESH_PREFIX + now.isoformat() + ']'
        requests = []
        if self.row_numbers:
            # Preserve the complete outgoing batch, including notes and statuses.
            # Archive and clear are one atomic Sheets request.
            requests.append({'duplicateSheet': {'sourceSheetId': sheet_id,
                'newSheetName': now.strftime('Archive %Y-%m-%d %H%M%S')}})
            for index in self.row_numbers.values():
                requests.append({'updateCells': {'range': {'sheetId': sheet_id,
                    'startRowIndex': index - 1, 'endRowIndex': index,
                    'startColumnIndex': 0, 'endColumnIndex': 20}, 'fields': 'userEnteredValue'}})
        if markers:
            requests.append({'updateDeveloperMetadata': {
                'dataFilters': [{'developerMetadataLookup': {'metadataId': markers[0]['metadataId']}}],
                'developerMetadata': {'metadataValue': marker}, 'fields': 'metadataValue'}})
        else:
            requests.append({'createDeveloperMetadata': {'developerMetadata': {
                'metadataKey': 'job_watch_refresh', 'metadataValue': marker,
                'location': {'sheetId': sheet_id}, 'visibility': 'DOCUMENT'}}})
        request(self.url + ':batchUpdate', {'requests': requests}, token=self.token)

    def format_rows(self, first, last):
        metadata = request(self.url + '?fields=sheets(properties(sheetId,title),basicFilter)', token=self.token)
        sheet = next(s for s in metadata['sheets'] if s['properties']['title'] == 'Jobs')
        sheet_id = sheet['properties']['sheetId']
        basic_filter = dict(sheet.get('basicFilter', {}))
        basic_filter['range'] = {'sheetId': sheet_id, 'startRowIndex': 4, 'startColumnIndex': 0, 'endColumnIndex': 20}
        bounds = {'sheetId': sheet_id, 'startRowIndex': first - 1, 'endRowIndex': last}
        requests = [
            {'setBasicFilter': {'filter': basic_filter}},
            {'repeatCell': {'range': dict(bounds, startColumnIndex=0, endColumnIndex=20),
                            'cell': {'userEnteredFormat': {'wrapStrategy': 'WRAP', 'verticalAlignment': 'TOP',
                                      'textFormat': {'fontFamily': 'Arial', 'fontSize': 11}}},
                            'fields': 'userEnteredFormat.wrapStrategy,userEnteredFormat.verticalAlignment,userEnteredFormat.textFormat'}},
        ]
        for column, kind, pattern in [(2, 'PERCENT', '0.0%'), (5, 'DATE', 'mm/dd/yy'),
                                       (6, 'DATE_TIME', 'mm/dd/yy hh:mm'), (14, 'DATE_TIME', 'mm/dd/yy hh:mm')]:
            requests.append({'repeatCell': {'range': dict(bounds, startColumnIndex=column, endColumnIndex=column + 1),
                            'cell': {'userEnteredFormat': {'numberFormat': {'type': kind, 'pattern': pattern}}},
                            'fields': 'userEnteredFormat.numberFormat'}})
        requests.append({'autoResizeDimensions': {'dimensions': {'sheetId': sheet_id, 'dimension': 'ROWS',
                                                                 'startIndex': first - 1, 'endIndex': last}}})
        request(self.url + ':batchUpdate', {'requests': requests}, token=self.token)

    def append(self, jobs):
        seen = self.read()
        pending = []
        for job in jobs:
            if job['key'] not in seen:
                pending.append(job)
                seen.add(job['key'])
        if pending:
            # The workflow's concurrency group serializes writers. Ambiguous POSTs are
            # not retried. The next run reads the Job ID column before another append.
            sheet_id = self.sheet_metadata()['properties']['sheetId']
            values = [{'values': [{'userEnteredValue': {
                'numberValue' if isinstance(value, (int, float)) else 'stringValue': value}}
                for value in row(j)]} for j in pending]
            request(self.url + ':batchUpdate', {'requests': [
                {'insertDimension': {'range': {'sheetId': sheet_id, 'dimension': 'ROWS',
                                                'startIndex': 5, 'endIndex': 5 + len(pending)},
                                     'inheritFromBefore': False}},
                {'updateCells': {'start': {'sheetId': sheet_id, 'rowIndex': 5, 'columnIndex': 0},
                                 'rows': values, 'fields': 'userEnteredValue'}}]}, token=self.token)
            self.format_rows(6, 5 + len(pending))
        elif jobs and getattr(self, 'row_numbers', None):
            # Finish formatting if a previous append succeeded but formatting failed.
            positions = [self.row_numbers[j['key']] for j in jobs]
            self.format_rows(min(positions), max(positions))
        return {j['key'] for j in jobs}
