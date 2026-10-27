import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from monitor.docs import GoogleDoc, REFRESH_PREFIX, refresh_due, entry
from monitor.sheets import GoogleSheet
from monitor.run import process
from test_monitor import job
import test_sheets


NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)


def marker(when):
    return REFRESH_PREFIX + when.isoformat() + ']'


class RefreshTests(unittest.TestCase):
    def test_exact_24_hour_boundary(self):
        self.assertFalse(refresh_due(marker(NOW - timedelta(hours=23, minutes=59)), NOW))
        self.assertTrue(refresh_due(marker(NOW - timedelta(hours=24)), NOW))
        self.assertTrue(refresh_due('', NOW))
        with self.assertRaises(ValueError):
            refresh_due('unrecognized user text', NOW)

    def test_sheet_archives_before_clearing_only_identified_rows(self):
        sink = test_sheets.SheetTests().sink()
        sink.read = lambda: set()
        sink.row_numbers = {'a': 6, 'b': 9}
        with patch('monitor.sheets.request', return_value={}) as send:
            sink.refresh(NOW)
        requests = send.call_args.args[1]['requests']
        self.assertIn('duplicateSheet', requests[0])
        self.assertEqual([r['updateCells']['range']['startRowIndex'] for r in requests
                          if 'updateCells' in r], [5, 8])
        self.assertIn('createDeveloperMetadata', requests[-1])

    def test_sheet_reset_retry_with_marker_does_not_clear_new_batch(self):
        sink = test_sheets.SheetTests().sink()
        sink.read = lambda: set()
        sink.sheet_metadata = lambda: {'properties': {'sheetId': 9}, 'developerMetadata': [
            {'metadataId': 3, 'metadataKey': 'job_watch_refresh', 'metadataValue': marker(NOW)}]}
        with patch('monitor.sheets.request') as send:
            sink.refresh(NOW + timedelta(hours=1))
            send.assert_not_called()

    def test_empty_sheet_advances_reset_without_archive(self):
        sink = test_sheets.SheetTests().sink()
        sink.read = lambda: set()
        sink.row_numbers = {}
        with patch('monitor.sheets.request', return_value={}) as send:
            sink.refresh(NOW)
        self.assertEqual(len(send.call_args.args[1]['requests']), 1)

    def test_doc_clears_generated_entries_preserves_heading_and_unicode(self):
        value = process([job(company='Example 😀')], {'skills': ['python']}, {}, now=NOW.isoformat())[0]
        text = 'My job search\n' + entry(value) + '\nMy separate notes\n'
        doc = {'revisionId': 'rev', 'body': {'content': [
            {'startIndex': 1, 'paragraph': {'elements': [
                {'startIndex': 1, 'textRun': {'content': text}}]}}]}}
        sink = GoogleDoc.__new__(GoogleDoc)
        sink.url, sink.token = 'https://example.test', 'test'
        with patch('monitor.docs.request', side_effect=[doc, {}]) as send:
            sink.refresh(NOW)
        payload = send.call_args.args[1]
        self.assertEqual(payload['writeControl']['requiredRevisionId'], 'rev')
        encoded = text.encode('utf-16-le')
        for change in payload['requests']:
            if 'deleteContentRange' in change:
                bounds = change['deleteContentRange']['range']
                encoded = encoded[:2*(bounds['startIndex']-1)] + encoded[2*(bounds['endIndex']-1):]
        remaining = encoded.decode('utf-16-le')
        self.assertIn('My job search', remaining)
        self.assertIn('My separate notes', remaining)
        self.assertNotIn(value['key'], remaining)

    def test_doc_retry_after_reset_is_read_only(self):
        doc = {'revisionId': 'rev', 'body': {'content': [{'paragraph': {'elements': [
            {'startIndex': 1, 'textRun': {'content': marker(NOW) + '\n'}}]}}]}}
        sink = GoogleDoc.__new__(GoogleDoc)
        sink.url, sink.token = 'https://example.test', 'test'
        with patch('monitor.docs.request', return_value=doc) as send:
            sink.refresh(NOW)
            self.assertEqual(send.call_count, 1)

    def test_old_jobs_do_not_reappear_after_list_reset(self):
        class Sink:
            def append(self, jobs):
                return {j['key'] for j in jobs}
        state = {}
        self.assertEqual(len(process([job()], {'skills': ['python']}, state, Sink())), 1)
        self.assertEqual(process([job()], {'skills': ['python']}, state, Sink()), [])


if __name__ == '__main__':
    unittest.main()
