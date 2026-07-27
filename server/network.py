"""Обнаружение устройств в локальной сети — «глаза» Сайки в сети.

Определяет, какие устройства сейчас в её сети: IP, MAC, имя, примерный
производитель (по MAC-префиксу OUI). Работает без прав администратора и без
внешних пакетов — через системный `arp -a` (таблица уже виденных соседей),
опционально «будит» сеть быстрым ping-サweep, чтобы таблица наполнилась.

Инструмент net_devices (server/llm/tools.py) — Сайка сама зовёт по просьбе
«кто у меня в сети», «какие устройства подключены».
"""
import concurrent.futures
import ipaddress
import logging
import re
import socket
import subprocess

log = logging.getLogger("saika.net")

# грубый справочник вендоров по префиксу MAC (первые 3 байта, OUI).
# не полный — самые частые бытовые; неизвестное остаётся пустым.
OUI = {
    "b8:27:eb": "Raspberry Pi", "dc:a6:32": "Raspberry Pi",
    "00:1a:11": "Google", "f4:f5:e8": "Google (Nest/Chromecast)",
    "18:b4:30": "Nest", "44:07:0b": "Google",
    "ac:63:be": "Amazon (Echo)", "68:37:e9": "Amazon", "fc:65:de": "Amazon",
    "d8:31:34": "Xiaomi", "28:6c:07": "Xiaomi", "64:09:80": "Xiaomi",
    "50:8f:4c": "Xiaomi", "78:11:dc": "Xiaomi",
    "5c:cf:7f": "Espressif (IoT/ESP)", "24:0a:c4": "Espressif (ESP32)",
    "a4:cf:12": "Espressif", "cc:50:e3": "Espressif",
    "00:17:88": "Philips Hue", "ec:b5:fa": "Philips Hue",
    "3c:5a:b4": "Google", "00:1d:d8": "Microsoft (Xbox)",
    "7c:ed:8d": "Microsoft (Surface)", "50:1a:c5": "Microsoft",
    "ac:de:48": "Apple", "f0:18:98": "Apple", "a4:83:e7": "Apple",
    "3c:07:54": "Apple", "88:66:5a": "Apple", "dc:2b:2a": "Apple",
    "00:50:56": "VMware", "08:00:27": "VirtualBox",
    "52:54:00": "QEMU/KVM",
    "e4:5f:01": "Raspberry Pi", "d8:3a:dd": "Raspberry Pi",
    "00:0c:29": "VMware", "00:1c:42": "Parallels",
    "bc:d0:74": "Samsung", "f8:04:2e": "Samsung", "8c:77:12": "Samsung",
    "5c:49:7d": "Samsung", "2c:ba:ba": "Samsung (TV)",
    "70:2a:d5": "Samsung", "d0:66:7b": "Samsung (TV)",
    "18:1e:b0": "Huawei", "48:3c:0c": "Huawei",
    "34:29:8f": "TP-Link (роутер)", "50:c7:bf": "TP-Link",
    "e8:de:27": "TP-Link", "a4:2b:b0": "TP-Link (роутер)",
    "b0:be:76": "TP-Link", "c0:06:c3": "TP-Link",
    "00:1e:8c": "ASUS", "2c:56:dc": "ASUS", "04:d4:c4": "ASUS",
}


def _local_subnet():
    """Своя подсеть (192.168.x.0/24) по локальному IP."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip, ipaddress.ip_network(ip + "/24", strict=False)
    except Exception:
        return None, None


def _ping(ip):
    try:
        subprocess.run(["ping", "-n", "1", "-w", "300", str(ip)],
                       capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass


def _wake_network():
    """Быстрый ping-sweep — чтобы arp-таблица наполнилась активными соседями."""
    ip, net = _local_subnet()
    if not net:
        return
    hosts = list(net.hosts())[:254]
    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
        pool.map(_ping, hosts)


def _arp_table():
    """Парсим `arp -a` -> [{ip, mac}]."""
    try:
        out = subprocess.run(["arp", "-a"], capture_output=True, text=True,
                             creationflags=getattr(subprocess,
                                                   "CREATE_NO_WINDOW", 0)).stdout
    except Exception as e:
        log.warning("arp не выполнился: %s", e)
        return []
    rows = []
    for line in out.splitlines():
        m = re.search(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F]{2}(?:[:-][0-9a-fA-F]{2}){5})",
                      line)
        if m:
            ip = m.group(1)
            mac = m.group(2).lower().replace("-", ":")
            if mac in ("ff:ff:ff:ff:ff:ff",) or ip.endswith(".255"):
                continue
            rows.append({"ip": ip, "mac": mac})
    return rows


def _hostname(ip):
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return ""


def _vendor(mac):
    return OUI.get(mac[:8], "")


def scan(wake=True) -> list:
    """Список устройств сети: [{ip, mac, name, vendor}]."""
    if wake:
        try:
            _wake_network()
        except Exception:
            pass
    devices = _arp_table()
    # обогащаем именами параллельно (reverse DNS)
    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
        names = list(pool.map(lambda d: _hostname(d["ip"]), devices))
    for d, name in zip(devices, names):
        d["name"] = name
        d["vendor"] = _vendor(d["mac"])
    # уникализируем по mac
    seen, uniq = set(), []
    for d in devices:
        if d["mac"] in seen:
            continue
        seen.add(d["mac"])
        uniq.append(d)
    return uniq


def scan_text(wake=True) -> str:
    """Человеческая сводка для Сайки."""
    devs = scan(wake=wake)
    if not devs:
        return ("В arp-таблице пусто (или нет доступа к сети). Устройства "
                "не обнаружены.")
    ip, net = _local_subnet()
    lines = [f"В сети {net if net else ''} обнаружено {len(devs)} устройств:"]
    for i, d in enumerate(devs, 1):
        who = d.get("name") or d.get("vendor") or "неизвестное устройство"
        extra = []
        if d.get("vendor") and d["vendor"] not in who:
            extra.append(d["vendor"])
        tag = f" ({', '.join(extra)})" if extra else ""
        lines.append(f"{i}. {d['ip']} — {who}{tag} [{d['mac']}]")
    return "\n".join(lines)
