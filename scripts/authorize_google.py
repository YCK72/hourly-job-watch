"""One-time desktop OAuth. Credentials are saved locally, never printed."""
import argparse
import base64
import hashlib
import http.server
import json
import secrets
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('client_file', help='Downloaded Google Desktop OAuth client JSON')
    parser.add_argument('--output', default='secrets/google-oauth.json')
    args = parser.parse_args()
    client = json.loads(Path(args.client_file).read_text())['installed']
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    result = {}

    class Callback(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            if query.get('state') != [state] or 'code' not in query:
                self.send_error(400)
                return
            result['code'] = query['code'][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'Authorization received. You can close this tab.')

        def log_message(self, *args):
            pass

    with http.server.HTTPServer(('127.0.0.1', 0), Callback) as server:
        redirect = f'http://127.0.0.1:{server.server_port}/'
        query = urllib.parse.urlencode(dict(client_id=client['client_id'], redirect_uri=redirect,
            response_type='code', scope='https://www.googleapis.com/auth/documents', access_type='offline',
            prompt='consent', state=state, code_challenge=challenge, code_challenge_method='S256'))
        webbrowser.open('https://accounts.google.com/o/oauth2/v2/auth?' + query)
        server.timeout = 300
        while 'code' not in result:
            server.handle_request()
            if not result:
                raise TimeoutError('Authorization not completed; rerun when ready')
    body = urllib.parse.urlencode(dict(client_id=client['client_id'], client_secret=client['client_secret'],
        code=result['code'], redirect_uri=redirect, grant_type='authorization_code', code_verifier=verifier)).encode()
    with urllib.request.urlopen(urllib.request.Request('https://oauth2.googleapis.com/token', data=body), timeout=30) as response:
        tokens = json.load(response)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({key: value for key, value in dict(client_id=client['client_id'],
        client_secret=client['client_secret'], refresh_token=tokens['refresh_token']).items()}), encoding='utf-8')
    print('Credentials saved to the specified private file. Set GOOGLE_OAUTH_JSON from this file; do not commit it.')


if __name__ == '__main__':
    main()
