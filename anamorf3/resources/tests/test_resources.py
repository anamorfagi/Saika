"""Тесты resources без настоящей модели: поддельный OpenAI-сервер.

Каждый тест ловит конкретную старую беду:
  * обрывки tool_calls -> один целый вызов, один раз;
  * отмена посреди потока реально рвёт соединение (сервер видит уход клиента);
  * ошибка — последним куском, а не исключением; local не уходит в облако.
Запуск: python -m unittest anamorf3.resources.tests.test_resources -v
"""
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from anamorf3.contracts import CancelToken, ChatRequest
from anamorf3.resources import make_port
from anamorf3.resources.stream import chat_stream

STATE = {"client_left": False, "auth": None, "body": None}


def sse(obj):
    return ("data: " + json.dumps(obj) + "\n\n").encode()


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        STATE["auth"], STATE["body"] = self.headers.get("Authorization"), body
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        last = body["messages"][-1]["content"]
        try:
            if last == "tool":
                for part in ['{"pa', 'th": "a.t', 'xt"}']:
                    d = {"tool_calls": [{"index": 0, "id": "c1" if part == '{"pa' else None,
                                         "type": "function",
                                         "function": {"name": "fs_read" if part == '{"pa' else None,
                                                      "arguments": part}}]}
                    self.wfile.write(sse({"model": "fake-m", "choices": [{"delta": d}]}))
                self.wfile.write(sse({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}))
                self.wfile.write(sse({"choices": [], "usage": {"completion_tokens": 7}}))
                self.wfile.write(b"data: [DONE]\n\n")
            elif last == "slow":
                for i in range(200):
                    self.wfile.write(sse({"model": "fake-m",
                                          "choices": [{"delta": {"content": f"{i} "}}]}))
                    self.wfile.flush()
                    time.sleep(0.05)
                self.wfile.write(b"data: [DONE]\n\n")
            else:
                for w in ["При", "вет"]:
                    self.wfile.write(sse({"model": "fake-m", "choices": [{"delta": {"content": w}}]}))
                self.wfile.write(sse({"choices": [{"delta": {}, "finish_reason": "stop"}],
                                      "timings": {"prompt_ms": 12.5}}))
                self.wfile.write(b"data: [DONE]\n\n")
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            STATE["client_left"] = True


class ResourcesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}/v1"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def msgs(self, t):
        return {"model": "x", "messages": [{"role": "user", "content": t}]}

    def test_text_and_numbers(self):
        out = list(chat_stream(self.url, self.msgs("hi"), CancelToken()))
        self.assertEqual("".join(c.text for c in out), "Привет")
        end = out[-1]
        self.assertTrue(end.done)
        self.assertEqual(end.usage["finish_reason"], "stop")
        self.assertEqual(end.model, "fake-m")
        self.assertIsNotNone(end.usage["ttft_ms"])
        self.assertEqual(end.usage["timings"]["prompt_ms"], 12.5)

    def test_tool_call_assembled_once(self):
        out = list(chat_stream(self.url, self.msgs("tool"), CancelToken()))
        calls = [c for c in out if c.tool_calls]
        self.assertEqual(len(calls), 1)
        tc = calls[0].tool_calls
        self.assertEqual(len(tc), 1)
        self.assertEqual(tc[0]["id"], "c1")
        self.assertEqual(tc[0]["function"]["name"], "fs_read")
        self.assertEqual(json.loads(tc[0]["function"]["arguments"]), {"path": "a.txt"})
        self.assertEqual(out[-1].usage["finish_reason"], "tool_calls")
        self.assertEqual(out[-1].usage["completion_tokens"], 7)

    def test_cancel_really_cuts(self):
        STATE["client_left"] = False
        tok = CancelToken()
        got, t0 = [], time.monotonic()
        for ch in chat_stream(self.url, self.msgs("slow"), tok):
            got.append(ch)
            if len(got) == 5:
                tok.cancel("перебили")
        dt = time.monotonic() - t0
        self.assertEqual(got[-1].usage["finish_reason"], "cancelled")
        self.assertLess(dt, 2.0, "отмена не прервала поток (сервер шлёт 10 с)")
        time.sleep(0.4)
        self.assertTrue(STATE["client_left"], "сервер не заметил ухода клиента")

    def test_error_is_last_chunk_not_exception(self):
        out = list(chat_stream("http://127.0.0.1:9/v1", self.msgs("hi"), CancelToken(), timeout_s=2))
        self.assertTrue(out[-1].done)
        self.assertEqual(out[-1].usage["finish_reason"], "error")

    def test_cloud_without_key_is_honest(self):
        p = make_port("cloud", override={"cloud": {"key_ref": "nope.none", "base_url": self.url}})
        out = list(p.chat(ChatRequest(messages=[{"role": "user", "content": "hi"}], mode="cloud"),
                          CancelToken()))
        self.assertEqual(out[-1].usage["finish_reason"], "error")
        self.assertIn("нет ключа", out[-1].usage["error"])
        self.assertFalse(p.status()["key_present"])

    def test_local_never_falls_to_cloud(self):
        p = make_port("local", override={"local": {"model": "models/gguf/НЕТ_ТАКОГО.gguf",
                                                   "port": 8799}})
        out = list(p.chat(ChatRequest(messages=[{"role": "user", "content": "hi"}], mode="local"),
                          CancelToken()))
        self.assertEqual(out[-1].usage["finish_reason"], "error")
        self.assertIn("нет файла модели", out[-1].usage["error"])

    def test_auto_is_refused(self):
        with self.assertRaises(ValueError):
            make_port("auto")


if __name__ == "__main__":
    unittest.main()
