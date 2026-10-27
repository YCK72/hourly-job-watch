import hashlib
import html
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ('p', 'li', 'br', 'div', 'h2', 'h3'):
            self.parts.append('\n')

    def handle_data(self, data):
        self.parts.append(data)


def plain(value):
    parser = PlainText()
    parser.feed(html.unescape(value or ''))
    return '\n'.join(' '.join(x.split()) for x in ''.join(parser.parts).splitlines() if x.strip())


SKILLS = {
    'python': ['python'], 'java': ['java'], 'javascript': ['javascript'],
    'typescript': ['typescript'], 'c++': ['c++'], 'c#': ['c#'], 'sql': ['sql'],
    'go': ['golang', 'go programming', 'in Go', 'Go and', 'Go,'], 'rust': ['rust'], 'scala': ['scala'],
    'ruby': ['ruby'], 'ansible': ['ansible'], 'puppet': ['puppet'],
    'r': ['r programming', 'r language'], 'bash': ['bash'], 'fastapi': ['fastapi'],
    'rest': ['rest api', 'restful'], 'kafka': ['kafka'], 'postgresql': ['postgresql', 'postgres'],
    'redis': ['redis'], 'mongodb': ['mongodb'], 'mysql': ['mysql'],
    'aws': ['aws', 'amazon web services'], 'azure': ['azure'], 'gcp': ['gcp', 'google cloud'],
    'docker': ['docker'], 'kubernetes': ['kubernetes', 'k8s'], 'terraform': ['terraform'],
    'git': ['git'], 'linux': ['linux'], 'ci/cd': ['ci/cd', 'continuous integration'],
    'pytorch': ['pytorch'], 'tensorflow': ['tensorflow'], 'scikit-learn': ['scikit-learn', 'sklearn'],
    'pandas': ['pandas'], 'numpy': ['numpy'], 'spark': ['spark'], 'airflow': ['airflow'],
    'dbt': ['dbt'], 'snowflake': ['snowflake'], 'databricks': ['databricks'],
    'etl': ['etl', 'extract transform load'], 'machine learning': ['machine learning', 'machine-learning'],
    'nlp': ['nlp', 'natural language processing'], 'llm': ['llm', 'llms', 'large language model'],
    'rag': ['rag', 'retrieval augmented', 'retrieval-augmented'], 'faiss': ['faiss'],
    'distributed systems': ['distributed systems'], 'microservices': ['microservices'],
    'react': ['react', 'reactjs'], 'node.js': ['node.js', 'nodejs'], 'spring': ['spring boot'],
    'xgboost': ['xgboost'], 'shap': ['shap'], 'reinforcement learning': ['reinforcement learning'],
    'prometheus': ['prometheus'], 'grafana': ['grafana'], 'selenium': ['selenium'],
}


def keywords(text):
    return {key for key, aliases in SKILLS.items() if any(
        re.search(r'(?<![\w+#])' + re.escape(alias) + r'(?![\w+#])', text, re.I)
        for alias in aliases)}


def canonical_url(url):
    p = urlsplit(url)
    if p.scheme != 'https' or not p.hostname:
        raise ValueError('Expected HTTPS job link')
    query = [(k, v) for k, v in parse_qsl(p.query) if not (
        k.lower().startswith('utm_') or k.lower() in ('source', 'ref', 'referral', 'gh_src'))]
    return urlunsplit(('https', p.netloc.lower(), p.path.rstrip('/').removesuffix('/apply'),
                       urlencode(sorted(query)), ''))


def identity(job):
    # ATS IDs are preserved across title/location edits and tracking URLs.
    key = f"{job['source']}:{job['board'].lower()}:{job['id']}"
    return hashlib.sha256(key.encode()).hexdigest()


def sentences(text):
    return [x.strip() for x in re.split(r'\n+|(?<=[.!?])\s+(?=[A-Z])', text) if x.strip()]


def sponsorship(text):
    evidence = [s for s in sentences(text) if re.search(
        r'sponsor|\bvisa\b|work authori[sz]|\bOPT\b|\bCPT\b|citizen|permanent residen', s, re.I)]
    negative = r'(?:no|not|cannot|can\x27t|unable|without|unavailable|ineligible|do not|does not|will not).{0,65}sponsor|sponsor.{0,65}(?:not available|not provided|unavailable)|(?:must be|only).{0,35}(?:citizen|permanent resident)|(?:US|U\.S\.|United States) citizenship (?:is )?required'
    # Questions are not employer policy. Contradictory/conditional wording requires review.
    denials = [s for s in evidence if '?' not in s and re.search(negative, s, re.I)]
    conditional = [s for s in evidence if re.search(r'case.by.case|may (?:be|provide|offer)|depending|eligible roles|at this time|currently|only.{0,20}(?:certain|some)', s, re.I)]
    positives = [s for s in evidence if '?' not in s and not re.search(negative, s, re.I) and re.search(
        r'(?:offer|provide|available|support|eligible for).{0,35}(?:visa )?sponsor|sponsorship (?:is )?(?:available|provided|offered)', s, re.I)]
    if not positives and any(re.search(r'future|at any time', s, re.I) for s in denials):
        return 'excluded', denials
    if denials and not positives and not conditional:
        return 'excluded', denials
    if denials or conditional:
        return 'conditional — verify future sponsorship', evidence
    if positives:
        return 'stated available — verify eligibility', evidence
    return 'unknown — verify future sponsorship', evidence or ['Not stated in fetched posting.']


STATES = 'AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC'.split()
US_CITIES = r'New York|San Francisco|Seattle|Austin|Boston|Chicago|Los Angeles|San Jose|San Diego|Denver|Atlanta|Palo Alto|Mountain View|Sunnyvale|Bellevue|Redmond|Menlo Park|Washington,? DC'


def us_location(job):
    country = (job.get('country') or '').upper()
    if country in ('US', 'USA', 'UNITED STATES', 'UNITED STATES OF AMERICA'):
        return True
    loc = job.get('location') or ''
    return bool(re.search(r'\b(?:United States|USA|U\.S\.|US)\b', loc) or
                re.search(r',\s*(?:' + '|'.join(STATES) + r')\b', loc) or
                re.search(r'\b(?:' + US_CITIES + r')\b', loc, re.I))


def evaluate(job, profile):
    title, text = job['title'], job['description']
    if not us_location(job):
        return None
    if not re.search(r'engineer|developer', title, re.I) or not re.search(r'software|backend|back.end|full.stack|front.end|machine learning|\bAI\b|\bML\b|data engineer|artificial intelligence', title, re.I):
        return None
    if re.search(r'\bsenior\b|\bsr\.?\b|\bstaff\b|principal|\blead\b|manager|director|intern(?:ship)?\b|\bIII\b|\bIV\b', title, re.I):
        return None
    def numeric(s):
        for n, word in enumerate(('zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten')):
            s = re.sub(r'\b' + word + r'(?=\s+(?:years?|yrs?)\b)', str(n), s, flags=re.I)
        return s
    exp = [s for s in sentences(text) if re.search(
        r'\b\d+\s*(?:\+|[-–]\s*\d+)?\s*(?:years?|yrs?)\b|no (?:prior )?experience|experience (?:is )?not required', numeric(s), re.I)
        and re.search(r'experience|background|working|developing|building', s, re.I)]
    # Keep exact wording; preferred years do not become a hard minimum.
    minimums = []
    for s in exp:
        requirement = re.sub(r'\([^)]*\)', '', s)
        if re.search(r'preferred|nice.to.have|bonus', requirement, re.I):
            continue
        minimums.extend(int(n) for n in re.findall(r'\b(\d+)\s*(?:\+|[-–]\s*\d+)?\s*(?:years?|yrs?)\b', numeric(requirement), re.I))
    explicit_entry = bool(re.search(r'new.grad|entry.level|junior|university grad|early.career|engineer I\b|engineer 1\b', title, re.I))
    entry_body = bool(re.search(r'(?:new|recent|university) graduates?|entry.level (?:role|position)|no (?:prior |professional )?experience (?:is )?required', text, re.I))
    if minimums and max(minimums) > 2 and not explicit_entry:
        return None
    if not (explicit_entry or entry_body or minimums):
        return None
    status, evidence = sponsorship(text)
    if status == 'excluded':
        return None
    required = keywords(text)
    matched = sorted(required & set(profile['skills']))
    if not required:
        return None  # Cannot manufacture a fit score from title alone.
    score = round(100 * len(matched) / len(required), 1)
    if score < 50:
        return None
    flags = []
    if not explicit_entry:
        flags.append('Entry-level eligibility inferred from experience/graduate wording; verify')
    if explicit_entry and minimums and max(minimums) > 2:
        flags.append('Entry-level title conflicts with experience text; review')
    if not status.startswith('stated available'):
        flags.append('Future sponsorship requires verification')
    for sentence in sentences(text):
        if re.search(r'security clearance|polygraph|full scope poly', sentence, re.I):
            flags.append('Clearance requirement — verify eligibility: ' + sentence)
    return dict(job, key=identity(job), experience_requirement=exp or ['Not stated in fetched posting.'],
                matched_keywords=matched, unmatched_keywords=sorted(required - set(profile['skills'])),
                fit_score=score, fit_basis=f'{len(matched)}/{len(required)} recognized posting skills matched',
                sponsorship_status=status, sponsorship_evidence=evidence, flags=flags,
                application_status='Human review required; no application submitted')
