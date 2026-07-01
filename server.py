from functools import partial
from http.server import SimpleHTTPRequestHandler, HTTPServer
import os
import json


class SaveHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        super().__init__(*args, directory=directory or os.path.dirname(os.path.abspath(__file__)), **kwargs)

    def do_POST(self):
        if self.path != '/save':
            return super().do_POST()

        length = int(self.headers.get('content-length', 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except Exception:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'Invalid JSON')
            return

        data_path = os.path.join(self.directory, 'data', 'data.json')
        os.makedirs(os.path.dirname(data_path), exist_ok=True)
        with open(data_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')


if __name__ == '__main__':
    port = 3000
    base_dir = os.path.dirname(os.path.abspath(__file__))
    server = HTTPServer(('0.0.0.0', port), partial(SaveHandler, directory=base_dir))
    print(f'Serving on http://localhost:{port}')
    server.serve_forever()
