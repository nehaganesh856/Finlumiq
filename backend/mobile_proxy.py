"""Local same-origin reverse proxy for Finlumiq mobile testing.

Frontend: http://127.0.0.1:8000
Flask API: http://127.0.0.1:5000
Proxy:     http://127.0.0.1:8080

Expose ONLY the proxy port (8080) through your HTTPS tunnel.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.client import HTTPConnection, HTTPException
from urllib.parse import urlsplit
import os
import sys

FRONTEND_HOST = os.environ.get("Finlumiq_FRONTEND_HOST", "127.0.0.1")
FRONTEND_PORT = int(os.environ.get("Finlumiq_FRONTEND_PORT", "8000"))
BACKEND_HOST = os.environ.get("Finlumiq_BACKEND_HOST", "127.0.0.1")
BACKEND_PORT = int(os.environ.get("Finlumiq_BACKEND_PORT", "5000"))
PROXY_HOST = os.environ.get("Finlumiq_PROXY_HOST", "127.0.0.1")
PROXY_PORT = int(os.environ.get("Finlumiq_PROXY_PORT", "8080"))

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host"
}


class FinlumiqProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self): self._forward()
    def do_HEAD(self): self._forward()
    def do_POST(self): self._forward()
    def do_PUT(self): self._forward()
    def do_PATCH(self): self._forward()
    def do_DELETE(self): self._forward()
    def do_OPTIONS(self): self._forward()

    def _forward(self):
        parsed = urlsplit(self.path)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        # API requests go to Flask; every other request serves the frontend.
        is_api = parsed.path == "/api" or parsed.path.startswith("/api/")
        upstream_host = BACKEND_HOST if is_api else FRONTEND_HOST
        upstream_port = BACKEND_PORT if is_api else FRONTEND_PORT

        body = None
        length = self.headers.get("Content-Length")
        if length:
            try:
                body = self.rfile.read(int(length))
            except (ValueError, OSError):
                self.send_error(400, "Invalid request body")
                return

        headers = {}
        for key, value in self.headers.items():
            lower = key.lower()
            if lower in HOP_BY_HOP or lower in {"origin", "referer", "accept-encoding"}:
                continue
            headers[key] = value
        headers["Host"] = f"{upstream_host}:{upstream_port}"
        headers["Accept-Encoding"] = "identity"
        # Keep authentication cookies; the browser sees one HTTPS origin.

        conn = HTTPConnection(upstream_host, upstream_port, timeout=45)
        try:
            conn.request(self.command, path, body=body, headers=headers)
            response = conn.getresponse()
            payload = response.read()
            self.send_response(response.status, response.reason)

            sent_content_length = False
            for key, value in response.getheaders():
                lower = key.lower()
                if lower in HOP_BY_HOP or lower == "content-encoding":
                    continue
                if lower == "content-length":
                    sent_content_length = True
                # Preserve multiple Set-Cookie response headers.
                self.send_header(key, value)
            if not sent_content_length and self.command != "HEAD":
                self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD" and payload:
                self.wfile.write(payload)
            self.close_connection = True
        except (OSError, HTTPException) as exc:
            self.send_error(502, f"Upstream server unavailable: {exc}")
        finally:
            conn.close()

    def log_message(self, fmt, *args):
        sys.stdout.write("[Finlumiq proxy] " + (fmt % args) + "\n")


def main():
    server = ThreadingHTTPServer((PROXY_HOST, PROXY_PORT), FinlumiqProxyHandler)
    print("Finlumiq mobile proxy is running")
    print(f"  Frontend: http://{FRONTEND_HOST}:{FRONTEND_PORT}")
    print(f"  Flask API: http://{BACKEND_HOST}:{BACKEND_PORT}")
    print(f"  Proxy URL: http://{PROXY_HOST}:{PROXY_PORT}")
    print("Expose proxy port 8080 through Cloudflare Tunnel. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Finlumiq proxy...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
