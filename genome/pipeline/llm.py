# -*- coding: utf-8 -*-
"""
[БЛОК API] Один клиент на всех провайдеров. Каталог — providers.json (тот же файл читает вкладка «API» в студии).

Откуда ключ (по порядку): аргумент --key → переменная LLM_KEY → secrets.json Сайки
(llm.cloud_keys.<provider>, для openrouter — llm.cloud_api_key). Путь к secrets.json: --secrets или
C:\\AI\\Saika\\secrets.json / ../secrets.json.

Использование из кода:
    from llm import Client
    c = Client("gigachat", model="GigaChat-2-Pro")     # или Client("custom", base="http://…/v1", key="…")
    text = c.chat("system…", "user…", temperature=0.2, max_tokens=2000)
Из консоли: python llm.py --provider mistral --model mistral-small-latest --ask "Привет"
"""
import os, sys, json, time, ssl, uuid, base64, pathlib, argparse, socket, urllib.request, urllib.error

HERE = pathlib.Path(__file__).parent
CATALOG = {p["id"]: p for p in json.loads((HERE / "providers.json").read_text(encoding="utf-8"))["providers"]}

def _secrets(path=None):
    for p in [path, os.environ.get("SAIKA_SECRETS"), r"C:\AI\Saika\secrets.json", HERE.parent / "secrets.json", HERE / "secrets.json"]:
        if p and pathlib.Path(p).exists():
            try: return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
            except Exception: pass
    return {}

def _ключи_студии():
    """Ключи, вписанные во вкладке «API»: genome/api_keys.json.

    18.09 исследование падало с 401, хотя в студии стоял свежий рабочий ключ:
    клиент смотрел только в secrets.json, а кнопка «вставить ключ» пишет в
    api_keys.json. Два разных хранилища — теперь читаются оба.
    """
    for p in (HERE.parent / "api_keys.json", HERE / "api_keys.json"):
        try:
            if p.exists():
                d = json.loads(p.read_text(encoding="utf-8"))
                return d if isinstance(d, dict) else {}
        except Exception:
            pass
    return {}


def find_key(provider, secrets_path=None):
    if os.environ.get("LLM_KEY"): return os.environ["LLM_KEY"]
    свои = _ключи_студии()
    for ветка in (свои, свои.get("keys") or {}):
        зн = ветка.get(provider) if isinstance(ветка, dict) else None
        if isinstance(зн, dict): зн = зн.get("key") or зн.get("value")
        if isinstance(зн, str) and len(зн.strip()) > 12: return зн.strip()
    s = _secrets(secrets_path).get("llm", {})
    if provider == "openrouter" and s.get("cloud_api_key"): return s["cloud_api_key"]
    return (s.get("cloud_keys") or {}).get(provider, "")

class Client:
    def __init__(self, provider="custom", model=None, base=None, key=None, secrets_path=None, timeout=120):
        self.p = dict(CATALOG.get(provider, CATALOG["custom"])); self.pid = provider
        self.base = (base or self.p["base"]).rstrip("/")
        self.model = model or (self.p["models"][0] if self.p["models"] else "")
        self.key = key or find_key(provider, secrets_path)
        self.timeout = timeout
        self._tok = None; self._tok_exp = 0
        self.usage = {"calls": 0, "prompt": 0, "completion": 0, "sec": 0.0}   # чтобы видеть цену прогона числами

    # --- GigaChat: Authorization key → access token на 30 минут ---------------------------------
    def _gigachat_token(self):
        if self._tok and time.time() < self._tok_exp - 60: return self._tok
        req = urllib.request.Request("https://ngw.devices.sberbank.ru:9443/api/v2/oauth", data=b"scope=GIGACHAT_API_PERS",
              headers={"Authorization": "Basic " + self.key, "RqUID": str(uuid.uuid4()), "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE   # сертификат УЦ Минцифры
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r: d = json.loads(r.read())
        self._tok = d["access_token"]; self._tok_exp = d.get("expires_at", 0) / 1000 or time.time() + 1700
        return self._tok

    def _headers(self):
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        a = self.p.get("auth", "bearer")
        if a == "gigachat": h["Authorization"] = "Bearer " + self._gigachat_token()
        elif a == "bearer" and self.key: h["Authorization"] = ("Api-Key " if self.pid == "yandex" else "Bearer ") + self.key
        elif a == "raw" and self.key: h["Authorization"] = self.key            # GPTunneL: ключ без слова Bearer
        elif a == "x-api-key": h["x-api-key"] = self.key; h["anthropic-version"] = "2023-06-01"
        if self.pid == "openrouter": h["HTTP-Referer"] = "https://genome.studio"; h["X-Title"] = "Genome Studio"
        return h

    def chat(self, system, user, temperature=0.2, max_tokens=2500, json_mode=False):
        t0 = time.time(); self.usage["calls"] += 1
        if self.p.get("auth") == "x-api-key":     # Anthropic Messages API
            body = {"model": self.model, "max_tokens": max_tokens, "temperature": temperature, "system": system, "messages": [{"role": "user", "content": user}]}
            url = self.base + "/messages"
        else:
            body = {"model": self.model, "temperature": temperature, "max_tokens": max_tokens,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
            if json_mode and self.pid not in ("gigachat", "yandex"): body["response_format"] = {"type": "json_object"}
            if "gemini-2.5" in str(self.model): body["reasoning_effort"] = "none"   # см. учебный блок в _послать
            url = self.base + "/chat/completions"
        ctx = None
        if self.pid == "gigachat": ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=self._headers())
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as r: d = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503) and attempt < 3: time.sleep(3 * (attempt + 1)); continue
                raise RuntimeError(f"{self.pid} HTTP {e.code}: {e.read()[:300]!r}")
            except (TimeoutError, socket.timeout, urllib.error.URLError, ConnectionError) as e:
                # Долгий ответ и оборванное соединение — не повод бросать всю работу.
                if attempt < 3: time.sleep(4 * (attempt + 1)); continue
                raise RuntimeError(f"{self.pid}: соединение не дождалось ответа ({str(e)[:120]})")
        self.usage["sec"] += time.time() - t0
        u = d.get("usage") or {}
        self.usage["prompt"] += u.get("prompt_tokens", u.get("input_tokens", 0)); self.usage["completion"] += u.get("completion_tokens", u.get("output_tokens", 0))
        if "content" in d and isinstance(d["content"], list): return "".join(x.get("text", "") for x in d["content"])   # anthropic
        return d["choices"][0]["message"]["content"]

    # --- вызов инструментов: модель сама решает, что ей нужно ------------------------------------
    def chat_tools(self, messages, tools, temperature=0.2, max_tokens=2000):
        """Один ход разговора с инструментами. Возвращает {content, tool_calls}.

        Это то, чего не хватало для «работает как Клод»: обычный chat отдаёт только текст,
        а здесь модель может ответить просьбой вызвать функцию, и цикл продолжается."""
        t0 = time.time(); self.usage["calls"] += 1
        if self.p.get("auth") == "x-api-key":
            raise RuntimeError("для Anthropic инструменты вызываются иначе — используй OpenAI-совместимый стык")
        body = {"model": self.model, "temperature": temperature, "max_tokens": max_tokens,
                "messages": messages, "tools": tools, "tool_choice": "auto"}
        ctx = None
        if self.pid == "gigachat":
            ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        d = self._послать(body, ctx)
        self.usage["sec"] += time.time() - t0
        u = d.get("usage") or {}
        self.usage["prompt"] += u.get("prompt_tokens", 0); self.usage["completion"] += u.get("completion_tokens", 0)
        m = (d.get("choices") or [{}])[0].get("message") or {}
        return {"content": m.get("content") or "", "tool_calls": m.get("tool_calls") or []}


    def _послать(self, body, ctx, попыток=4):
        """Один HTTP-запрос с повторами и подменой имени лимита токенов.

        Часть моделей (новые OpenAI) отвергает max_tokens и требует
        max_completion_tokens. Раньше это выглядело как «модель не работает»,
        хотя дело было в одном имени поля.
        """
        подменяли = False
        # ---- учебный блок: скрытые рассуждения gemini-2.5 ----
        # gemini-2.5 думает молча и тратит на это тот же лимит max_tokens. 04.10 распознавание
        # персонажа пришло обрезанным посередине JSON («модель не вернула JSON-объект»): лимит
        # съели невидимые рассуждения. Нам они не нужны — рассуждение задаёт сам промпт.
        if "gemini-2.5" in str(body.get("model", "")) and "reasoning_effort" not in body:
            body["reasoning_effort"] = "none"
        while True:
            req = urllib.request.Request(self.base + "/chat/completions",
                                         data=json.dumps(body).encode("utf-8"), headers=self._headers())
            for attempt in range(попыток):
                try:
                    with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as r:
                        return json.loads(r.read())
                except urllib.error.HTTPError as e:
                    тело = e.read()
                    если_лимит = (e.code == 400 and not подменяли
                                  and b"max_tokens" in тело and b"max_completion_tokens" in тело)
                    if если_лимит:
                        body["max_completion_tokens"] = body.pop("max_tokens", 1500)
                        подменяли = True
                        break
                    if e.code in (429, 500, 502, 503) and attempt < попыток - 1:
                        time.sleep(3 * (attempt + 1)); continue
                    raise RuntimeError(f"{self.pid} HTTP {e.code}: {тело[:300]!r}")
                except (TimeoutError, socket.timeout, urllib.error.URLError, ConnectionError) as e:
                    if attempt < попыток - 1:
                        time.sleep(4 * (attempt + 1)); continue
                    raise RuntimeError(f"{self.pid}: соединение не дождалось ответа ({str(e)[:120]})")
            else:
                raise RuntimeError(f"{self.pid}: запрос не прошёл")

    def chat_parts(self, messages, temperature=0.2, max_tokens=1200):
        """Обычный запрос без инструментов, но с составным содержимым сообщения.

        Нужен для картинок: chat() принимает только строки, а chat_tools() всегда шлёт
        список инструментов — часть стыков отвергает пустой tools. Здесь ни того, ни
        другого: просто messages как есть, включая части вида image_url.
        """
        t0 = time.time(); self.usage["calls"] += 1
        body = {"model": self.model, "temperature": temperature,
                "max_tokens": max_tokens, "messages": messages}
        if "gemini-2.5" in str(self.model): body["reasoning_effort"] = "none"   # см. учебный блок в _послать
        req = urllib.request.Request(self.base + "/chat/completions",
                                     data=json.dumps(body).encode("utf-8"), headers=self._headers())
        ctx = None
        if self.pid == "gigachat":
            ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as r:
                    d = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503) and attempt < 2:
                    time.sleep(3 * (attempt + 1)); continue
                raise RuntimeError(f"{self.pid} HTTP {e.code}: {e.read()[:300]!r}")
            except (TimeoutError, socket.timeout, urllib.error.URLError, ConnectionError) as e:
                if attempt < 2:
                    time.sleep(4 * (attempt + 1)); continue
                raise RuntimeError(f"{self.pid}: соединение не дождалось ответа ({str(e)[:120]})")
        self.usage["sec"] += time.time() - t0
        u = d.get("usage") or {}
        self.usage["prompt"] += u.get("prompt_tokens", 0); self.usage["completion"] += u.get("completion_tokens", 0)
        return ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""

    def ping(self):
        """Быстрая проверка: ключ, модель, задержка. Возвращает (ok, сообщение)."""
        try:
            t0 = time.time(); r = self.chat("Отвечай одним словом.", "Скажи: работает", max_tokens=5)
            return True, f"{self.pid}/{self.model}: «{r.strip()[:30]}» за {time.time()-t0:.1f} с"
        except Exception as e:
            return False, f"{self.pid}/{self.model}: {e}"

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--provider", default="gigachat"); ap.add_argument("--model"); ap.add_argument("--base"); ap.add_argument("--key"); ap.add_argument("--secrets")
    ap.add_argument("--ask"); ap.add_argument("--list", action="store_true"); a = ap.parse_args()
    if a.list:
        for p in CATALOG.values(): print(f"{p['id']:12} {'бесплатно' if p['free'] else 'платно':10} РФ:{p['ru']:6} {p['name']}  → {', '.join(p['models'][:3])}")
        sys.exit()
    c = Client(a.provider, a.model, a.base, a.key, a.secrets)
    if a.ask: print(c.chat("Ты помощник.", a.ask)); print(c.usage)
    else: print(*c.ping())
