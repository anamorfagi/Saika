"""Local worker for live Genome research (also usable by a file:// studio)."""
import argparse
import json
import pathlib
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

from research import ResearchJob, ROOT

JOBS = {}
JOB_LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # Never log request bodies: they may contain a model API key.

    def allowed(self):
        origin = self.headers.get('Origin', '')
        return origin in ('', 'null') or urlsplit(origin).hostname in ('localhost', '127.0.0.1')

    def reply(self, data, code=200):
        raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        if self.allowed():
            self.send_header('Access-Control-Allow-Origin', self.headers.get('Origin', 'null'))
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers(); self.wfile.write(raw)

    def do_OPTIONS(self):
        self.reply({}, 200 if self.allowed() else 403)

    def do_GET(self):
        if not self.allowed(): return self.reply({'error': 'Недопустимый источник запроса'}, 403)
        path = urlsplit(self.path).path
        if path == '/health': return self.reply({'service': 'genome-research', 'version': 1})
        if path == '/jobs/latest':
            with JOB_LOCK:
                jobs = list(JOBS.values())
                job = jobs[-1] if jobs else None
            state = job.snapshot() if job else {'active': False}
            if job: state['active'] = not job.done
            return self.reply(state)
        match = re.fullmatch(r'/jobs/(research_[a-f0-9]{12})', path)
        if not match: return self.reply({'error': 'Нет маршрута'}, 404)
        try:
            after = max(0, int(parse_qs(urlsplit(self.path).query).get('after', ['0'])[0]))
            job = JOBS.get(match[1])
            if job:
                state = job.snapshot(after)
            else:
                file = ROOT / 'chars' / match[1] / 'state.json'
                if not file.exists(): return self.reply({'error': 'Исследование не найдено'}, 404)
                state = json.loads(file.read_text(encoding='utf-8'))
                state['events'] = state['events'][after:]
                if not state['done']:
                    state.update(state='interrupted', done=True)
                    state['events'].append({'stage': 'error', 'message': 'Работник был остановлен. Частичный результат сохранён; повторный поиск запускается кнопкой.'})
            for source in state.get('sources', []): source.pop('_text', None)
            return self.reply(state)
        except Exception as e:
            self.reply({'error': str(e)}, 400)

    def do_POST(self):
        if not self.allowed(): return self.reply({'error': 'Недопустимый источник запроса'}, 403)
        path = urlsplit(self.path).path
        try:
            n = int(self.headers.get('Content-Length', 0))
            if n > 100_000: return self.reply({'error': 'Слишком большой запрос'}, 413)
            data = json.loads(self.rfile.read(n) or '{}')
            if path == '/jobs':
                query = str(data.get('query', '')).strip()
                if not query or len(query) > 3000: raise ValueError('Впиши запрос длиной до 3000 символов')
                with JOB_LOCK:
                    if any(not j.done for j in JOBS.values()):
                        return self.reply({'error': 'Уже идёт исследование. Дождись результата или останови его.'}, 409)
                    # Переделка идёт в ту же карточку: retry указывает, какой прогон
                    # переделываем. Иначе каждая неудача плодила нового персонажа.
                    повтор = str(data.get('retry', ''))[:64]
                    if повтор and not re.fullmatch(r'research_[a-f0-9]{12}', повтор):
                        raise ValueError('Неверный идентификатор переделки')
                    job = ResearchJob(query, str(data.get('origin', ''))[:1000], data.get('cfg'),
                                      повтор=повтор)
                    JOBS[job.id] = job
                job.persist()
                initial = job.snapshot()
                threading.Thread(target=job.run, daemon=True).start()
                return self.reply(initial, 202)
            match = re.fullmatch(r'/jobs/(research_[a-f0-9]{12})/cancel', path)
            if match and match[1] in JOBS:
                JOBS[match[1]].cancelled.set()
                return self.reply({'ok': True})
            self.reply({'error': 'Нет маршрута'}, 404)
        except Exception as e:
            self.reply({'error': str(e)}, 400)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8770)
    args = parser.parse_args()
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
