"""Serve the local wheel app. Run with python -m mozaproxy.web."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import secrets
import signal
from urllib.parse import unquote, urlsplit

from .app_state import AppState, validate_settings

MAX_BODY = 65536


class Handler(BaseHTTPRequestHandler):
    server_version = 'Mozaproxy'

    def log_message(self, *_):
        pass

    def _send(self, status, body, content_type='application/json; charset=utf-8', download=False):
        if not isinstance(body, bytes):
            body = json.dumps(body, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        if download:
            self.send_header('Content-Disposition', 'attachment; filename="mozaproxy-diagnostics.json"')
        self.end_headers()
        self.wfile.write(body)

    def _allowed(self):
        host = self.headers.get('Host', '')
        valid = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if self.server.server_port == 80:
            valid.update({'127.0.0.1', 'localhost'})
        if host not in valid:
            return False
        origin = self.headers.get('Origin')
        if origin is not None and origin != 'http://' + host:
            return False
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            return False
        return True

    def _body(self):
        if self.headers.get_content_type() != 'application/json':
            self._send(415, {'error': 'Content-Type must be application/json'})
            return None
        if self.headers.get('Transfer-Encoding'):
            raise ValueError('Transfer-Encoding is not supported')
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            raise ValueError('Invalid Content-Length') from None
        if not 0 < length <= MAX_BODY:
            raise ValueError('JSON request body must be between 1 and 65536 bytes')
        body = json.loads(self.rfile.read(length), parse_constant=lambda value: (_ for _ in ()).throw(ValueError('JSON numbers must be finite')))
        if not isinstance(body, dict):
            raise ValueError('JSON body must be an object')
        return body

    def _dispatch(self):
        if not self._allowed():
            self._send(403, {'error': 'Only same-origin localhost requests are accepted'})
            return
        path = unquote(urlsplit(self.path).path)
        app = self.server.app
        if self.command == 'GET':
            if path == '/api/session':
                self._send(200, {'token': self.server.token})
            elif path == '/api/state':
                self._send(200, app.snapshot())
            elif path == '/api/schema':
                self._send(200, app.schema_provider())
            elif path == '/api/diagnostics/export':
                self._send(200, app.export(), download=True)
            elif path.startswith('/api/'):
                self._send(404, {'error': 'Endpoint not found'})
            else:
                self._static(path)
            return
        token = self.headers.get('X-Mozaproxy-Token', '')
        if not secrets.compare_digest(token, self.server.token):
            self._send(403, {'error': 'A valid session token is required'})
            return
        body = self._body()
        if body is None:
            return
        if self.command == 'POST' and path == '/api/profiles':
            result = app.profiles.save(body)
        elif path.startswith('/api/profiles/'):
            parts = path.split('/')
            if self.command == 'DELETE' and len(parts) == 4:
                app.profiles.delete(parts[3])
            elif self.command == 'POST' and len(parts) == 5 and parts[4] == 'activate':
                app.profiles.activate(parts[3])
            else:
                raise KeyError('Endpoint not found')
            result = {'ok': True}
        elif self.command == 'POST' and path == '/api/hardware/connect':
            result = app.hardware.connect()
        elif self.command == 'POST' and path == '/api/hardware/disconnect':
            result = app.hardware.disconnect()
        elif self.command == 'POST' and path == '/api/hardware/apply':
            settings = validate_settings(body.get('settings'), app.schema_provider())
            result = app.hardware.apply(settings)
        elif self.command == 'POST' and path == '/api/relay/start':
            result = app.relay.start(body)
        elif self.command == 'POST' and path == '/api/relay/stop':
            result = app.relay.stop()
        else:
            raise KeyError('Endpoint not found')
        self._send(200, result)

    def _static(self, path):
        if '\x00' in path or '..' in Path(path).parts:
            raise KeyError('File not found')
        root = self.server.static_dir.resolve()
        file = (root / path.lstrip('/')).resolve()
        if path == '/':
            file = (root / 'index.html').resolve()
        if not file.is_relative_to(root) or not file.is_file():
            raise KeyError('File not found')
        mime = mimetypes.guess_type(str(file))[0] or 'application/octet-stream'
        self._send(200, file.read_bytes(), mime)

    def _handle(self):
        self.connection.settimeout(5)
        try:
            self._dispatch()
        except KeyError as exc:
            self._send(404, {'error': str(exc.args[0])})
        except (ValueError, TypeError, UnicodeError) as exc:
            self._send(400, {'error': str(exc)})
        except OSError as exc:
            self._send(503, {'error': str(exc)})

    do_GET = _handle
    do_POST = _handle
    do_DELETE = _handle


def create_server(app, host='127.0.0.1', port=8765, static_dir=None):
    if host != '127.0.0.1':
        raise ValueError('The app must bind to 127.0.0.1')
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.app = app
    server.token = secrets.token_urlsafe(32)
    server.static_dir = Path(static_dir) if static_dir else Path(__file__).parent / 'webui'
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data-dir', type=Path, help='Directory for saved profiles')
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error('Port must be between 0 and 65535')
    def stop(*_):
        raise KeyboardInterrupt

    previous_sigterm = signal.signal(signal.SIGTERM, stop)
    app = AppState(data_dir=args.data_dir)
    server = None
    try:
        server = create_server(app, port=args.port)
        print(f'Mozaproxy app: http://127.0.0.1:{server.server_port}', flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if server:
            server.server_close()
        try:
            app.close()
        finally:
            signal.signal(signal.SIGTERM, previous_sigterm)


if __name__ == '__main__':
    main()
