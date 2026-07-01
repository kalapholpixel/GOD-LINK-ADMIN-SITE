from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from hmac import compare_digest
from threading import Lock
from time import sleep, time
from urllib.parse import urlsplit
import os
import json


def _parse_origin_list(env_name):
    value = os.getenv(env_name, '').strip()
    if not value:
        return set()
    return {origin.strip().rstrip('/') for origin in value.split(',') if origin.strip()}


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


class SaveHandler(SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    subscribers = []
    subscribers_lock = Lock()
    data_version = 0
    read_origins = _parse_origin_list('ALLOWED_READ_ORIGINS')
    save_origins = _parse_origin_list('ALLOWED_SAVE_ORIGINS')
    save_api_key = os.getenv('SAVE_API_KEY', '').strip()
    sse_retry_ms = int(os.getenv('SSE_RETRY_MS', '3000'))
    cors_deny_by_default = _env_bool('CORS_DENY_BY_DEFAULT', False)

    def __init__(self, *args, directory=None, **kwargs):
        super().__init__(*args, directory=directory or os.path.dirname(os.path.abspath(__file__)), **kwargs)

    def _request_origin(self):
        origin = self.headers.get('Origin')
        return origin.rstrip('/') if origin else None

    def _origin_allowed(self, allowed_origins):
        cls = type(self)
        origin = self._request_origin()
        if origin is None:
            return True
        if not allowed_origins and not cls.cors_deny_by_default:
            return True
        return origin in allowed_origins

    def _send_cors_headers(self, allowed_origins, methods='GET, POST, OPTIONS'):
        origin = self._request_origin()
        if origin is None:
            return

        if not allowed_origins:
            if not type(self).cors_deny_by_default:
                self.send_header('Access-Control-Allow-Origin', '*')
        elif origin in allowed_origins:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')

        self.send_header('Access-Control-Allow-Methods', methods)
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Admin-Key')

    def _write_json_response(self, status_code, payload, extra_headers=None, allowed_origins=None, methods='GET, POST, OPTIONS'):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self._send_cors_headers(allowed_origins if allowed_origins is not None else type(self).read_origins, methods=methods)
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _save_is_authorized(self):
        cls = type(self)
        if not cls.save_api_key:
            return True
        provided = self.headers.get('X-Admin-Key', '')
        return compare_digest(provided, cls.save_api_key)

    def _broadcast_update(self, version):
        cls = type(self)
        event = (
            f'id: {version}\n'
            'event: content-updated\n'
            f'data: {json.dumps({"version": version, "updatedAt": int(time())})}\n\n'
        ).encode('utf-8')
        dead_subscribers = []
        with cls.subscribers_lock:
            for stream in cls.subscribers:
                try:
                    stream.write(event)
                    stream.flush()
                except Exception:
                    dead_subscribers.append(stream)
            if dead_subscribers:
                cls.subscribers = [stream for stream in cls.subscribers if stream not in dead_subscribers]

    def do_OPTIONS(self):
        cls = type(self)
        path = urlsplit(self.path).path
        if path == '/save':
            allowed = cls.save_origins
            methods = 'POST, OPTIONS'
        elif path == '/api/auth/verify':
            allowed = cls.save_origins
            methods = 'POST, OPTIONS'
        elif path in ('/api/data', '/api/events'):
            allowed = cls.read_origins
            methods = 'GET, OPTIONS'
        else:
            self.send_response(404)
            self.end_headers()
            return

        if not self._origin_allowed(allowed):
            self._write_json_response(403, {'error': 'Origin not allowed'}, allowed_origins=allowed, methods=methods)
            return

        self.send_response(204)
        self._send_cors_headers(allowed, methods=methods)
        self.send_header('Access-Control-Max-Age', '86400')
        self.end_headers()

    def do_GET(self):
        cls = type(self)
        path = urlsplit(self.path).path

        if path == '/api/data':
            if not self._origin_allowed(cls.read_origins):
                self._write_json_response(403, {'error': 'Origin not allowed'}, allowed_origins=cls.read_origins, methods='GET, OPTIONS')
                return

            data_path = os.path.join(self.directory, 'data', 'data.json')
            try:
                with open(data_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except FileNotFoundError:
                data = {}
            except json.JSONDecodeError:
                self._write_json_response(500, {'error': 'data/data.json is invalid JSON'}, allowed_origins=cls.read_origins, methods='GET, OPTIONS')
                return

            self._write_json_response(
                200,
                data,
                {
                    'Cache-Control': 'no-store, no-cache, must-revalidate',
                    'Pragma': 'no-cache',
                    'Expires': '0',
                },
                allowed_origins=cls.read_origins,
                methods='GET, OPTIONS',
            )
            return

        if path == '/api/events':
            if not self._origin_allowed(cls.read_origins):
                self._write_json_response(403, {'error': 'Origin not allowed'}, allowed_origins=cls.read_origins, methods='GET, OPTIONS')
                return

            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
            self.send_header('Connection', 'keep-alive')
            self.send_header('X-Accel-Buffering', 'no')
            self._send_cors_headers(cls.read_origins, methods='GET, OPTIONS')
            self.end_headers()

            with cls.subscribers_lock:
                cls.subscribers.append(self.wfile)
                version = cls.data_version

            try:
                self.wfile.write(f'retry: {cls.sse_retry_ms}\n\n'.encode('utf-8'))
                self.wfile.write(
                    (
                        f'id: {version}\n'
                        'event: connected\n'
                        f'data: {json.dumps({"version": version, "updatedAt": int(time())})}\n\n'
                    ).encode('utf-8')
                )
                self.wfile.flush()

                heartbeat = b': heartbeat\n\n'
                while True:
                    self.wfile.write(heartbeat)
                    self.wfile.flush()
                    sleep(15)
            except Exception:
                pass
            finally:
                with cls.subscribers_lock:
                    cls.subscribers = [stream for stream in cls.subscribers if stream is not self.wfile]
            return

        return super().do_GET()

    def do_POST(self):
        cls = type(self)
        path = urlsplit(self.path).path

        if path == '/api/auth/verify':
            if not self._origin_allowed(cls.save_origins):
                self._write_json_response(403, {'error': 'Origin not allowed'}, allowed_origins=cls.save_origins, methods='POST, OPTIONS')
                return

            if not cls.save_api_key:
                self._write_json_response(200, {'ok': True, 'authRequired': False}, allowed_origins=cls.save_origins, methods='POST, OPTIONS')
                return

            if not self._save_is_authorized():
                self._write_json_response(401, {'error': 'Missing or invalid X-Admin-Key', 'authRequired': True}, allowed_origins=cls.save_origins, methods='POST, OPTIONS')
                return

            self._write_json_response(200, {'ok': True, 'authRequired': True}, allowed_origins=cls.save_origins, methods='POST, OPTIONS')
            return

        if path != '/save':
            self._write_json_response(404, {'error': 'Not found'}, allowed_origins=cls.save_origins, methods='POST, OPTIONS')
            return

        if not self._origin_allowed(cls.save_origins):
            self._write_json_response(403, {'error': 'Origin not allowed'}, allowed_origins=cls.save_origins, methods='POST, OPTIONS')
            return

        if not self._save_is_authorized():
            self._write_json_response(401, {'error': 'Missing or invalid X-Admin-Key'}, allowed_origins=cls.save_origins, methods='POST, OPTIONS')
            return

        length = int(self.headers.get('content-length', 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except Exception:
            self._write_json_response(400, {'error': 'Invalid JSON'}, allowed_origins=cls.save_origins, methods='POST, OPTIONS')
            return

        data_path = os.path.join(self.directory, 'data', 'data.json')
        os.makedirs(os.path.dirname(data_path), exist_ok=True)
        tmp_path = data_path + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, data_path)

        with cls.subscribers_lock:
            cls.data_version += 1
            version = cls.data_version

        self._broadcast_update(version)

        self._write_json_response(
            200,
            {'ok': True, 'version': version, 'updatedAt': int(time())},
            allowed_origins=cls.save_origins,
            methods='POST, OPTIONS',
        )


if __name__ == '__main__':
    port = int(os.getenv('PORT', '3000'))
    base_dir = os.path.dirname(os.path.abspath(__file__))
    server = ThreadingHTTPServer(('0.0.0.0', port), partial(SaveHandler, directory=base_dir))
    print(f'Serving on http://localhost:{port}')
    server.serve_forever()
