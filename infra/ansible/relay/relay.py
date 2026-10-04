"""S237 internal relay: original host ports -> restored services only.

Listens on every published host port recorded by prepare and forwards to the
matching service alias on the shared internal network. It has no route outside
internal bridges; unknown ports are simply not listened on.
"""
import json
import select
import socket
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

HEALTH_PORT = 9999
routes = json.load(open('/routes/routes.json'))


class Forward(socketserver.BaseRequestHandler):
    def handle(self):
        host, port = routes[str(self.server.server_address[1])]
        try:
            with socket.create_connection((host, port), timeout=10) as upstream:
                pair = [self.request, upstream]
                while True:
                    ready, _, _ = select.select(pair, [], [], 300)
                    if not ready:
                        return
                    for sock in ready:
                        data = sock.recv(65536)
                        if not data:
                            return
                        (upstream if sock is self.request else self.request).sendall(data)
        except OSError:
            return


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class Health(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps({'status': 'ok', 'routes': len(routes)}).encode()
        self.send_response(200 if self.path == '/health' else 404)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(body)


if str(HEALTH_PORT) in routes:
    raise SystemExit('health port collides with a route')
for port in routes:
    server = Server(('0.0.0.0', int(port)), Forward)
    threading.Thread(target=server.serve_forever, daemon=True).start()
threading.Thread(target=HTTPServer(('0.0.0.0', HEALTH_PORT), Health).serve_forever, daemon=True).start()
while True:
    time.sleep(3600)
