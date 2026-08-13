"""验证期间临时监听 80 端口提供校验文件。

ZeroSSL 的 HTTP 文件验证只会请求 80 端口且不接受 3xx 重定向，
所以业务站点即使跑在 10000 之类的端口，签发时仍需短暂占用 80。
本模块把这段占用限制在验证窗口内，用完立即释放。
"""

import contextlib
import http.server
import socket
import threading
import urllib.error
import urllib.request

USER_AGENT = "zerossl-ip-cert/1.0"


def _make_handler(routes):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            body = routes.get(self.path.split("?", 1)[0])
            if body is None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            raw = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, fmt, *args):
            print("    [verify-http] %s - %s" % (self.address_string(), fmt % args), flush=True)

    return Handler


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    address_family = socket.AF_INET


@contextlib.contextmanager
def serve(port, routes):
    """在 with 块内监听指定端口，退出时确保关闭。"""
    try:
        httpd = _Server(("0.0.0.0", port), _make_handler(routes))
    except OSError as exc:
        raise RuntimeError(
            "无法绑定 %d 端口: %s。若宿主已有服务占用 80，请停掉它或改用 VERIFY_PORT "
            "配合外部 80 端口转发" % (port, exc)) from exc
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def self_check(url, expected):
    """从外部 URL 自检一次，提前发现防火墙未放通等问题。"""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status != 200:
                return False, "HTTP %s" % resp.status
            got = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return False, "HTTP %s" % exc.code
    except Exception as exc:
        return False, str(exc)
    if got.strip() != expected.strip():
        return False, "内容不一致"
    return True, "ok"
