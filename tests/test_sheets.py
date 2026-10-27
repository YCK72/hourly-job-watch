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
        sink.sheet_metadata=lambda:{'properties':{'title':'Jobs','sheetId':9}}
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
            requests=send.call_args.args[1]['requests']
            self.assertEqual(requests[0]['insertDimension']['range']['startIndex'],5)
            rows=requests[1]['updateCells']['rows']
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['values'][0]['userEnteredValue'],{'stringValue':value['company']})
            self.assertEqual(rows[0]['values'][2]['userEnteredValue'],{'numberValue':0.5})
            self.assertEqual(len(rows[0]['values']),len(HEADERS))

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

    def test_appending_preserves_user_filter(self):
        sink=self.sink()
        criteria={'2':{'condition':{'type':'NUMBER_GREATER','values':[{'userEnteredValue':'0.8'}]}}}
        metadata={'sheets':[{'properties':{'title':'Jobs','sheetId':9},'basicFilter':{'criteria':criteria}}]}
        with patch('monitor.sheets.request',side_effect=[metadata,{}]) as send:
            GoogleSheet.format_rows(sink,57,58)
            payload=send.call_args.args[1]
            self.assertEqual(payload['requests'][0]['setBasicFilter']['filter']['criteria'],criteria)
            self.assertFalse(any('values' in request for request in payload['requests']))


if __name__=='__main__':
    unittest.main()
