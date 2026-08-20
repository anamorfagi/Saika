"""Доступ к Сайке с телефона: домашняя сеть по QR или Tailscale.

ЗАЧЕМ. Владелец хочет разговаривать с ней с дивана, а не от клавиатуры.
Интерфейс у нас уже адаптивный, отдельный мобильный клиент не нужен — не
хватало ровно одного: сервер слушает 127.0.0.1, то есть только сам
компьютер. Телефон до него не достучится физически.

ПОЧЕМУ НЕ ПРОСТО «СЛУШАТЬ 0.0.0.0». Потому что у Сайки теперь руки в
системе: запуск программ, окна, файлы в рабочей папке. Открыть её на всю
Wi-Fi без пароля — это дать любому в сети (гостю, соседу через слабый
пароль роутера, чужому ноутбуку) запускать программы на этой машине.
Поэтому: как только сервер выходит наружу, включается токен. С самого
компьютера (127.0.0.1) он не спрашивается никогда — локальная работа не
должна усложняться из-за телефона.

ДВА ПУТИ, между которыми выбирает человек:
  дома по QR   — быстро, без установки, но работает только в своей Wi-Fi
  Tailscale    — работает откуда угодно, но надо поставить приложение
                 на оба устройства и войти в один аккаунт

Tailscale выбран не случайно: он бесплатный для личного использования,
поднимает шифрованный туннель между УСТРОЙСТВАМИ, не открывает ни одного
порта наружу в интернет и не требует ни белого IP, ни проброса портов на
роутере. Всё остальное (ngrok и прочие туннели) публикует адрес в
публичном интернете — для агента с руками в системе это плохой размен.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import secrets
import socket
import subprocess

from anamorf.config import CFG, ROOT, DATA_ROOT

log = logging.getLogger("saika.phone")

TOKEN_KEY = "server.token"
HOST_KEY = "server.host"
LOCAL_HOST = "127.0.0.1"
OPEN_HOST = "0.0.0.0"


def token(create=True) -> str:
    t = str(CFG.get(TOKEN_KEY, "") or "")
    if not t and create:
        # 8 знаков: этого хватает против случайного тыка в локальной сети, а
        # длиннее человек не наберёт руками, если QR не сработал
        t = secrets.token_urlsafe(6)[:8]
        CFG.set(TOKEN_KEY, t)
    return t


def new_token() -> str:
    CFG.set(TOKEN_KEY, "")
    return token()


def is_open() -> bool:
    return str(CFG.get(HOST_KEY, LOCAL_HOST)) not in (LOCAL_HOST, "localhost")


# Диапазоны, которые ВЫГЛЯДЯТ как локальная сеть, но ею не являются:
# это виртуальные адаптеры, которые ставят вместе с играми и удалёнкой.
# Телефон в них не входит, и QR по такому адресу не откроется никогда —
# поэтому подписываем их честно, а не показываем наравне с домашней Wi-Fi.
_VIRTUAL = (
    ("26.", "Radmin VPN"),
    ("25.", "Hamachi"),
    ("192.168.56.", "VirtualBox"),
    ("192.168.99.", "Docker Machine"),
    ("172.17.", "Docker"),
    ("172.18.", "Docker"),
    ("198.18.", "служебный диапазон"),
)


def _iface_kind(ip: str) -> str:
    """'' — настоящая домашняя сеть, иначе название виртуального адаптера."""
    for prefix, name in _VIRTUAL:
        if ip.startswith(prefix):
            return name
    return ""


def lan_ips() -> list:
    """Адреса этого компьютера в локальных сетях. Берём по одному на
    интерфейс и выкидываем всё, что не похоже на домашнюю сеть."""
    out = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None,
                                       socket.AF_INET):
            ip = info[4][0]
            try:
                a = ipaddress.ip_address(ip)
            except ValueError:
                continue
            if a.is_loopback or a.is_link_local:
                continue
            if ip not in out:
                out.append(ip)
    except Exception as e:
        log.debug("имя хоста не разрешилось: %s", e)
    if not out:
        # запасной способ: спрашиваем у системы, через какой адрес она
        # пошла бы наружу. Пакет никуда не уходит — UDP-сокет не соединяется
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            out.append(s.getsockname()[0])
            s.close()
        except Exception:
            pass
    # 100.x — это Tailscale, он показывается отдельной строкой ниже
    return [ip for ip in out if not ip.startswith("100.")]


def tailscale() -> dict:
    """Стоит ли Tailscale и какой у этой машины адрес в нём."""
    exe = None
    for p in (r"C:\Program Files\Tailscale\tailscale.exe",
              r"C:\Program Files (x86)\Tailscale\tailscale.exe",
              "/usr/bin/tailscale", "/usr/local/bin/tailscale"):
        if os.path.exists(p):
            exe = p
            break
    if not exe:
        return {"installed": False, "ip": "", "hint": "не установлен"}
    try:
        r = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True,
                           timeout=6,
                           creationflags=getattr(subprocess,
                                                 "CREATE_NO_WINDOW", 0))
        ip = (r.stdout or "").strip().splitlines()
        ip = ip[0].strip() if ip else ""
    except Exception as e:
        log.debug("tailscale ip не ответил: %s", e)
        ip = ""
    return {"installed": True, "ip": ip,
            "hint": "готов" if ip else "установлен, но не выполнен вход"}


def urls() -> list:
    """Ссылки, по которым Сайка доступна с телефона — уже с токеном."""
    port = int(CFG.get("server.port", 8765))
    t = token()
    out = []
    ips = lan_ips()
    # настоящую домашнюю сеть — первой: именно её и надо сканировать
    ips.sort(key=lambda ip: (bool(_iface_kind(ip)), ip))
    sch = scheme()
    for ip in ips:
        virt = _iface_kind(ip)
        out.append({"kind": "lan", "url": f"{sch}://{ip}:{port}/?t={t}",
                    "virtual": virt,
                    "label": (f"{virt} · {ip}" if virt
                              else f"домашняя сеть · {ip}")})
    ts = tailscale()
    if ts.get("ip"):
        out.append({"kind": "tailscale",
                    "url": f"{sch}://{ts['ip']}:{port}/?t={t}",
                    "label": f"Tailscale · {ts['ip']}"})
    return out


# На каком адресе сервер РЕАЛЬНО слушает прямо сейчас. Порт занимается
# один раз при старте, поэтому тумблер в интерфейсе меняет только конфиг —
# и без этой отметки человек включает доступ, сканирует QR и не понимает,
# почему ничего не происходит (живой случай 2026-07-26).
BOUND_HOST = LOCAL_HOST


def bound_open() -> bool:
    return str(BOUND_HOST) not in (LOCAL_HOST, "localhost")


def firewall_cmd() -> str:
    """Команда, открывающая порт во входящих. Сами её не выполняем: для
    этого нужны права администратора, а тихо просить их у человека, у
    которого мы только что завели удалённый доступ, — плохой тон."""
    port = int(CFG.get("server.port", 8765))
    return (f'netsh advfirewall firewall add rule name="Saika {port}" '
            f'dir=in action=allow protocol=TCP localport={port}')


def state() -> dict:
    return {"open": is_open(), "host": CFG.get(HOST_KEY, LOCAL_HOST),
            "bound": BOUND_HOST, "bound_open": bound_open(),
            "restart_needed": is_open() != bound_open(),
            "firewall_cmd": firewall_cmd(),
            "https": bool(CFG.get("server.https", False)),
            "https_live": https_on(), "cert": cert_ready(),
            "crypto": _crypto_ok(),
            "port": int(CFG.get("server.port", 8765)),
            "token": token(), "urls": urls(),
            "tailscale": tailscale(), "qr": bool(_qr_lib())}


def set_open(on: bool) -> dict:
    """Открыть или закрыть доступ снаружи. Требует перезапуска сервера:
    порт занимается один раз при старте, на лету его не переслушать."""
    CFG.set(HOST_KEY, OPEN_HOST if on else LOCAL_HOST)
    if on:
        token()          # чтобы код уже был, когда человек откроет QR
    return state()


# ───────────────── HTTPS: без него не работает микрофон ─────────────────
# Живой случай 2026-07-26: телефон подключился, чат работает, а микрофон
# включить нельзя и списки устройств пустые.
#
# Это не наша поломка. Браузеры отдают navigator.mediaDevices (микрофон,
# камера, список устройств) ТОЛЬКО в защищённом контексте: https или
# localhost. Обычный http на адрес 192.168.x.x защищённым не считается, и
# объект просто отсутствует — поэтому меню слуха и выглядит пустым.
#
# Лечится единственным способом: поднять https. Сертификат делаем сами и
# кладём в него все адреса машины сразу (домашний IP, Tailscale, localhost),
# чтобы он подходил при любом способе захода. Браузер один раз ругнётся на
# самоподписанный — это нормально и неизбежно: подтверждённый сертификат
# бывает только у публичного домена, а у домашнего IP его взять негде.
CERT_DIR = None


def _cert_paths():
    d = DATA_ROOT / "data" / "cert"
    return d / "saika.crt", d / "saika.key"


def cert_ready() -> bool:
    c, k = _cert_paths()
    return c.exists() and k.exists()


def _crypto_ok() -> bool:
    try:
        import cryptography  # noqa: F401
        return True
    except Exception:
        return False


def make_cert(force=False) -> str:
    """Сделать самоподписанный сертификат на все адреса этой машины."""
    crt, key = _cert_paths()
    if cert_ready() and not force:
        return "Сертификат уже есть."
    if not _crypto_ok():
        return ("Нет библиотеки cryptography — без неё сертификат не "
                "сделать. Она ставится сама при следующем запуске "
                "start.bat, либо: .venv\\Scripts\\pip install cryptography")
    import datetime
    import ipaddress as _ip
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    names = [x509.DNSName("localhost")]
    addrs = ["127.0.0.1"] + lan_ips()
    ts = tailscale().get("ip")
    if ts:
        addrs.append(ts)
    for a in dict.fromkeys(addrs):
        try:
            names.append(x509.IPAddress(_ip.ip_address(a)))
        except ValueError:
            pass

    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Saika local"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Saika"),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(subject).issuer_name(subject)
            .public_key(k.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName(names), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None),
                           critical=True)
            .sign(k, hashes.SHA256()))
    crt.parent.mkdir(parents=True, exist_ok=True)
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key.write_bytes(k.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()))
    log.info("Сделала самоподписанный сертификат на %d адресов", len(names))
    return (f"Готово, сертификат на {len(names)} адресов. Включи https и "
            "перезапусти сервер.")


def https_on() -> bool:
    return bool(CFG.get("server.https", False)) and cert_ready()


def scheme() -> str:
    return "https" if https_on() else "http"


# ───────────────────────────── QR ─────────────────────────────
def _qr_lib():
    try:
        import qrcode  # noqa: F401
        return True
    except Exception:
        return False


def qr_svg(url: str) -> str:
    """QR как SVG-строка. Рисуем сами по матрице, а не через image-фабрику
    библиотеки: так не нужен ни Pillow, ни временный файл, и картинка
    остаётся чёткой на любом экране."""
    try:
        import qrcode
    except Exception:
        return ""
    q = qrcode.QRCode(border=2, box_size=1,
                      error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(url)
    q.make(fit=True)
    m = q.get_matrix()
    n = len(m)
    rects = []
    for y, row in enumerate(m):
        x = 0
        while x < n:
            if not row[x]:
                x += 1
                continue
            run = x
            while run < n and row[run]:
                run += 1
            rects.append(f'<rect x="{x}" y="{y}" width="{run - x}" '
                         f'height="1"/>')
            x = run
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" '
            f'shape-rendering="crispEdges" width="240" height="240">'
            f'<rect width="{n}" height="{n}" fill="#fff"/>'
            f'<g fill="#000">{"".join(rects)}</g></svg>')
