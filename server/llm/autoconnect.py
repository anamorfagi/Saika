"""ПОДКЛЮЧИТЬ ВСЁ, ЧТО ЕСТЬ (2026-08-13).

Владелец: «все подключай. система Анаморф — это обучающая универсальная
платформа, мы всё что можем должны использовать. всё познаётся в сравнении,
блядь — главный принцип этой системы».

До этого модель попадала в парк только вручную: человек шёл в интерфейс,
жал «Сохранить и включить» под каждого провайдера, и ключ без этого жеста
лежал в secrets.json мёртвым грузом. Реальная картина на сегодня: четыре
живых ключа, а в лестнице мозгов участвовали не все — просто потому, что
руки не дошли нажать. Сравнивать при таком раскладе нечего.

Теперь наоборот: ЕСТЬ КЛЮЧ — ЕСТЬ МОЗГ. При старте система сама проходит
по каталогу бесплатных тиров (server/llm/free_tiers.py), берёт каждого
провайдера, у которого ключ есть, и заводит его модели в общий список. Ни
одного отдельного батника, ни одной галочки — ровно тот смысл, ради
которого вся эта установка и затевалась.

Кого ключа нет — не молчим: status() отдаёт интерфейсу честный список «вот
эти подключены, а вот эти можно подключить за минуту, ключ берётся тут»,
с пометками про VPN и карту.
"""
import logging

from server.config import CFG

log = logging.getLogger("saika.autoconnect")

# У Cloudflare в адресе сидит account_id — пока человек его не подставил,
# подключать нечего, будет 404 на каждый вызов.
_PLACEHOLDER = ("ВАШ_ID", "YOUR_ACCOUNT", "<", "{")


def _account_url(url: str) -> str:
    """Подставить account_id владельца в адрес, где он нужен.

    У Cloudflare адрес личный: .../accounts/<account_id>/ai/v1. Это НЕ
    секрет (секрет — токен), он просто виден в адресной строке кабинета,
    поэтому живёт в обычном конфиге llm.cloudflare_account, а не в
    secrets.json. Раньше провайдер с таким адресом просто пропускался —
    человеку пришлось бы править base_url руками, а это ровно тот
    «сделай сам», от которого мы уходим."""
    acc = str(CFG.get("llm.cloudflare_account", "") or "").strip()
    if acc and "/accounts/" in url:
        import re
        return re.sub(r"/accounts/[^/]+/", f"/accounts/{acc}/", url)
    return url


def _usable_url(url: str) -> bool:
    return bool(url) and not any(p in _account_url(url) for p in _PLACEHOLDER)


def _relabel_custom():
    """Переклеить ярлык «custom» на настоящего вендора — и ключ тоже.

    Интерфейс пишет провайдера «custom», когда адрес человек вписал руками.
    Ключ при этом уезжает в слот «своё», и каталог перестаёт узнавать
    вендора: лимиты, пометки про VPN и остальные его модели проходят мимо.
    Определяем вендора по хосту и приводим записи в порядок один раз —
    молча, потому что чинить тут нечего, это просто наведение имён."""
    from server.llm import manager
    changed = []
    saved = list(CFG.get("llm.cloud_saved", []) or [])
    for e in saved:
        if not isinstance(e, dict):
            continue
        real = manager.provider_for_url(e.get("base_url", ""))
        if real and e.get("provider") != real:
            changed.append((e.get("provider", ""), real))
            e["provider"] = real
    if changed:
        CFG.set("llm.cloud_saved", saved)
        c = dict(CFG.get("llm.cloud", {}) or {})
        real = manager.provider_for_url(c.get("base_url", ""))
        if real and c.get("provider") != real:
            CFG.set("llm.cloud.provider", real)
        # ключ переносим в слот настоящего вендора, старый не трогаем:
        # вдруг под тем же «custom» у человека лежит что-то ещё
        try:
            import json
            from server.config import resolve
            f = resolve("secrets.json")
            data = json.loads(f.read_text(encoding="utf-8"))
            keys = data.setdefault("llm", {}).setdefault("cloud_keys", {})
            touched = False
            for old_name, real_name in changed:
                if keys.get(old_name) and not keys.get(real_name):
                    keys[real_name] = keys[old_name]
                    touched = True
            if touched:
                f.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        except Exception as e2:
            log.warning("ключ не переехал в свой слот: %s", e2)
        log.info("Провайдеры переименованы по хосту: %s",
                 ", ".join(f"{a}->{b}" for a, b in changed))
    return changed


def connect_all() -> dict:
    """Завести в парк все модели провайдеров, у которых есть ключ.
    Возвращает {"added": [...], "already": [...], "no_key": [...]}."""
    from server.llm import free_tiers, manager
    _relabel_custom()
    added, already, no_key = [], [], []
    try:
        have = {(e.get("base_url", "").rstrip("/"), e.get("model", ""))
                for e in manager.cloud_saved()}
    except Exception:
        have = set()
    for entry in free_tiers.CATALOG:
        prov = entry.get("id", "")
        url = _account_url((entry.get("base_url") or "").rstrip("/"))
        try:
            key = manager.cloud_key_for(prov)
        except Exception:
            key = ""
        if not key:
            no_key.append(prov)
            continue
        if not _usable_url(url):
            log.info("%s: в адресе остался placeholder — пропускаю", prov)
            continue
        # СКОЛЬКО МОДЕЛЕЙ БРАТЬ. Все: смысл платформы — сравнение, а разные
        # модели одного провайдера отличаются сильнее, чем провайдеры между
        # собой. Лестница мозгов отсортирует их сама, лишние просто лягут
        # ниже и в автоподъём не попадут.
        for model in (entry.get("models") or []):
            if (url, model) in have:
                already.append(model)
                continue
            try:
                manager.remember_cloud(prov, url, model)
                have.add((url, model))
                added.append(model)
            except Exception as e:
                log.warning("не завела %s/%s: %s", prov, model, e)
    if added:
        log.info("Подключила модели без спроса (есть ключ): %s",
                 ", ".join(added))
    if no_key:
        log.info("Ключа нет, поэтому не подключены: %s", ", ".join(no_key))
    return {"added": added, "already": already, "no_key": no_key}


def status() -> list[dict]:
    """Полная картина по провайдерам — для интерфейса и для неё самой."""
    from server.llm import brains, free_tiers, manager
    out = []
    for entry in free_tiers.CATALOG:
        prov = entry.get("id", "")
        try:
            key = bool(manager.cloud_key_for(prov))
        except Exception:
            key = False
        out.append({
            "id": prov,
            "name": entry.get("name", prov),
            "connected": key,
            "paid": prov in brains.PAID_PROVIDERS,
            "ru": entry.get("ru", ""),          # ok / vpn / block
            "card": entry.get("card", False),   # нужна ли банковская карта
            "free": entry.get("free", ""),
            "models": entry.get("models", []),
            "lang": entry.get("lang", ""),
            "note": entry.get("note", ""),
            "key_url": entry.get("key_url", ""),
            "key_hint": entry.get("key_hint", ""),
            "url_needs_edit": not _usable_url(entry.get("base_url", "")),
        })
    out.sort(key=lambda p: (not p["connected"], p["ru"] != "ok", p["name"]))
    return out


def missing() -> list[dict]:
    """Кого можно подключить прямо сейчас, по убыванию удобства: без VPN,
    без карты, бесплатно. Для подсказки владельцу — не для самодеятельности:
    ключ всё равно получает человек, Сайка не регистрируется за него."""
    order = {"ok": 0, "vpn": 1, "block": 2}
    cand = [p for p in status()
            if not p["connected"] and not p["paid"] and p["ru"] != "block"]
    cand.sort(key=lambda p: (order.get(p["ru"], 3), p["card"]))
    return cand
