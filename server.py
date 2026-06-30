from http.server import SimpleHTTPRequestHandler, HTTPServer
import os
import json

class SaveHandler(SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path != '/save':
            return super().do_POST()
        length = int(self.headers.get('content-length', 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except Exception as e:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'Invalid JSON')
            return
        os.makedirs('data', exist_ok=True)
        with open('data/data.json', 'w') as f:
            json.dump(data, f, indent=2)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')

if __name__ == '__main__':
    port = 3000
    server = HTTPServer(('0.0.0.0', port), SaveHandler)
    print(f'Serving on http://localhost:{port}')
    server.serve_forever()