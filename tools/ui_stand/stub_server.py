"""Подставной сервер для стенда интерфейса (2026-08-17).

Отдаёт НАСТОЯЩИЕ ui/avatar.html и visual/*.vrm, а вместо живой Сайки —
заглушки на её роуты. Нужен, чтобы гонять интерфейс в браузере, не поднимая
сервер целиком: модели, GPU и звук для проверки поведения окна не нужны.

Запускается сам из test_view.py, отдельно нужен редко:
    python -m tools.ui_stand.stub_server 8899
"""
import http.server
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STUBS = {
    "/api/avatar/current": {"kind": "3d", "settings": {}},
    "/api/avatar/desk": {},
    "/avatar/anims": [],
    "/api/status": {"ok": True},
}


def _model():
    """Первый .vrm в visual/ — чтобы стенд не был прибит к имени файла."""
    d = os.path.join(ROOT, "visual")
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if f.lower().endswith(".vrm"):
            return "/visual/" + f
    return None


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, *a):
        pass                      # без этого лог забивает вывод стенда

    def _send(self, body, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in STUBS:
            return self._send(json.dumps(STUBS[path]).encode(), "application/json")
        if path == "/api/audio_level":
            return self._send(b"0", "text/plain")
        if path == "/avatar/model.vrm":
            m = _model()
            if not m:
                self.send_error(404, "в visual/ нет ни одного .vrm")
                return
            self.path = m
        elif path in ("/", "/avatar"):
            self.path = "/ui/avatar.html"
        elif path.startswith("/vendor/"):
            self.path = "/ui" + path
        return super().do_GET()

    def do_POST(self):
        self._send(b'{"ok":true}', "application/json")


def serve(port=8899):
    return http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    import sys
    p = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    print(f"стенд на http://127.0.0.1:{p}/avatar?desk=1")
    serve(p).serve_forever()
