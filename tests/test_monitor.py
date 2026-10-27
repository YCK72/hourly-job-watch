import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from monitor.core import evaluate, sponsorship, canonical_url, identity, keywords
from monitor.sources import fetch
from monitor.run import process, save
from monitor.docs import GoogleDoc


def job(**changes):
    value = dict(id='123', source='greenhouse', board='test', company='Test',
                 title='Software Engineer, New Grad', url='https://example.com/jobs/123',
                 location='Seattle, WA', country='', description='Python and SQL. 0-2 years of experience.',
                 salary='Not stated', posted_at=None)
    return dict(value, **changes)


class MonitorTests(unittest.TestCase):
    def test_null_country_and_location(self):
        self.assertIsNotNone(evaluate(job(country=None), {'skills': ['python']}))
        self.assertIsNone(evaluate(job(country=None, location=None), {'skills': ['python']}))

    def test_threshold_inclusive(self):
        self.assertEqual(evaluate(job(), {'skills': ['python']})['fit_score'], 50)
        self.assertIsNone(evaluate(job(description='Python SQL Rust'), {'skills': ['python']}))

    def test_no_fake_score(self):
        self.assertIsNone(evaluate(job(description='Join our team'), {'skills': ['python']}))

    def test_exact_requirement_not_title_guess(self):
        text = 'Python. Minimum 0-2 years of professional experience required.'
        result = evaluate(job(description=text), {'skills': ['python']})
        self.assertEqual(result['experience_requirement'], ['Minimum 0-2 years of professional experience required.'])
        result = evaluate(job(description='Python.'), {'skills': ['python']})
        self.assertEqual(result['experience_requirement'], ['Not stated in fetched posting.'])

    def test_seniority_and_geography(self):
        for changes in ({'title': 'Senior Software Engineer'}, {'location': 'London, UK'},
                        {'location': 'Remote'}, {'title': 'Software Engineering Intern'},
                        {'title': 'Software Engineer', 'description': 'Python. 5+ years of experience required.'}):
            self.assertIsNone(evaluate(job(**changes), {'skills': ['python']}))

    def test_future_sponsorship_excluded(self):
        for text in ('We do not offer visa sponsorship.',
                     'Must work without sponsorship now or in the future.',
                     'We currently cannot sponsor now or in the future.',
                     'US citizenship is required.',
                     'We cannot sponsor work visas.', 'Visa sponsorship is not available.'):
            self.assertEqual(sponsorship(text)[0], 'excluded', text)
            self.assertIsNone(evaluate(job(description='Python. ' + text), {'skills': ['python']}))

    def test_sponsorship_unknown_conditional_positive(self):
        for text, expected in [('Must be authorized to work in the US.', 'unknown'),
                               ('Will you require sponsorship in the future?', 'unknown'),
                               ('We may offer sponsorship on a case-by-case basis.', 'conditional'),
                               ('We offer visa sponsorship.', 'stated available')]:
            self.assertTrue(sponsorship(text)[0].startswith(expected))

    def test_keywords_boundaries(self):
        self.assertNotIn('java', keywords('JavaScript'))
        self.assertIn('c++', keywords('C++ engineer'))
        self.assertIn('c#', keywords('C# engineer'))

    def test_tracking_links_same_identity(self):
        a = canonical_url('https://example.com/jobs/1/apply?utm_source=x&gh_src=x')
        self.assertEqual(a, canonical_url('https://example.com/jobs/1'))
        self.assertEqual(identity(job()), identity(job(title='Changed title', location='Austin, TX')))

    def test_persistent_once_only(self):
        class Sink:
            def append(self, rows):
                return {r['key'] for r in rows}
        state = {}
        self.assertEqual(len(process([job(), job()], {'skills': ['python']}, state, Sink(), 'first')), 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            save(path, state)
            restored = json.loads(path.read_text())
        self.assertEqual(process([job()], {'skills': ['python']}, restored, Sink(), 'second'), [])
        self.assertEqual(restored[identity(job())]['first_seen'], 'first')

    def test_failure_remains_retryable(self):
        class Sink:
            def append(self, rows):
                raise TimeoutError('ambiguous network result')
        state = {}
        with self.assertRaises(TimeoutError):
            process([job()], {'skills': ['python']}, state, Sink())
        self.assertFalse(state[identity(job())]['reported'])

    def test_document_reconciles_crash(self):
        sink = GoogleDoc.__new__(GoogleDoc)
        sink.url, sink.token = 'https://docs.googleapis.com/v1/documents/test', 'test'
        sink.read = lambda: ('revision', {identity(job())})
        with patch('monitor.docs.request') as request:
            self.assertEqual(sink.append([dict(job(), key=identity(job()))]), {identity(job())})
            request.assert_not_called()

    def test_revision_precondition(self):
        sink = GoogleDoc.__new__(GoogleDoc)
        sink.url, sink.token = 'https://docs.googleapis.com/v1/documents/test', 'test'
        sink.read = lambda: ('revision123', set())
        row = process([job()], {'skills': ['python']}, {})[0]
        with patch('monitor.docs.request') as request:
            sink.append([row])
            self.assertEqual(request.call_args.args[1]['writeControl'], {'requiredRevisionId': 'revision123'})

    def test_greenhouse_updated_is_not_posted(self):
        rows = fetch({'provider': 'greenhouse', 'board': 'test', 'company': 'Test'}, lambda _: {'jobs': [
            {'id': 1, 'title': 'Software Engineer', 'absolute_url': 'https://example.com/1',
             'location': {'name': 'Austin, TX'}, 'content': '<p>Python</p>', 'updated_at': '2026-01-01'}]})
        self.assertIsNone(rows[0]['posted_at'])
        self.assertEqual(rows[0]['description'], 'Python')

    def test_lever_pagination_and_requirements(self):
        calls = []
        def get(url):
            calls.append(url)
            row = {'id': 'x', 'text': 'Backend Engineer', 'hostedUrl': 'https://example.com/1',
                   'categories': {'location': 'Boston, MA'}, 'description': '<p>Python</p>',
                   'lists': [{'text': 'Requirements', 'content': '<li>1 year of experience</li>'}]}
            return [copy.deepcopy(row) for _ in range(100)] if 'skip=0' in url else []
        rows = fetch({'provider': 'lever', 'board': 'test', 'company': 'Test'}, get)
        self.assertEqual(len(calls), 2)
        self.assertIn('1 year of experience', rows[0]['description'])

    def test_ashby_fields(self):
        rows = fetch({'provider': 'ashby', 'board': 'test', 'company': 'Test'}, lambda _: {'jobs': [
            {'id': 'x', 'title': 'AI Engineer', 'jobUrl': 'https://example.com/1',
             'location': 'Remote', 'address': {'postalAddress': {'addressCountry': 'USA'}},
             'descriptionPlain': 'Python. 1 year of experience.', 'publishedAt': '2026-01-01',
             'compensation': {'scrapeableCompensationSalarySummary': '$100K–$120K'}}]})
        self.assertEqual(rows[0]['salary'], '$100K–$120K')
        self.assertIsNotNone(evaluate(rows[0], {'skills': ['python']}))

    def test_nonengineering_and_unspecified_level_excluded(self):
        for changes in ({'title': 'Strategic Finance, AI'},
                        {'title': 'Software Engineer', 'description': 'Python.'},
                        {'title': 'AI Engineer', 'description': 'Python. Five years of experience required.'},
                        {'title': 'AI Engineer', 'description': 'Python. 7+ years of experience (US federal preferred).'}):
            self.assertIsNone(evaluate(job(**changes), {'skills': ['python']}))

    def test_clearance_evidence_flag(self):
        result = evaluate(job(description='Python. Active US security clearance required.'), {'skills': ['python']})
        self.assertTrue(any('Active US security clearance required.' in f for f in result['flags']))


if __name__ == '__main__':
    unittest.main()
