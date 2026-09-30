# @trace FR-23, FR-24, FR-25, FR-26, FR-28, FR-29, FR-30, NFR-4, NFR-11
"""Тести живого виклику і фікстури (capability `live-capture`, слайс `add-input`): unittest зі stdlib.

Запуск: python3 -m unittest discover -s tests -p '*_test.py'

Принцип II конституції: склад полів і значення енамів виводяться лише з живої відповіді цього прогону. Тому живий
виклик — рівно один GET без ключів і лише на http чи https, відповідь лягає фікстурою `runs/<slug>/fixture.json`,
а недоступна відповідь (мережа, схема, ліміт часу, статус не 200, порожнє тіло, не-JSON, тіло без ключів
об'єкта) дає `LiveUnavailable` з URL і причиною і власної фікстури не лишає. Кожен кейс — сценарій зі спеки
`openspec/changes/add-input/specs/live-capture/spec.md` або рядок її вимоги.

Сторонній світ підміняється лише на межі, яку називає design.md. Біржу заступає справжній
`http.server.ThreadingHTTPServer` на 127.0.0.1 з ефемерним портом: за шляхом він віддає статус, тіло, затримку,
повільне тіло, мовчання чи перенаправлення і записує кожен отриманий запит. У шов `open_url` іде лише шпигун,
що делегує в `live.no_redirect_open` і рахує виклики; відповіді біржі в Python-об'єктах не підробляються.
Події `open` і `socket.connect` бачить хук `sys.addaudithook` у дочірньому `python3`, бо хук не знімається.
Один тест робить справжній виклик `https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT` — лише з
METHOD_SYNC_LIVE=1 (`npm run test:integration`). Без неї він видимо пропускається з причиною, бо юніт-набір і CI не
мусять залежати від стану біржі (tasks.md 6.9), а з нею недосяжна біржа — провал із поясненням, а не пропуск.

Ліміт часу (NFR-4) доводиться механізмом на короткому `timeout` — десяті частки секунди, щоб `npm run test:run`
тривав секунди. Числа зі спеки — окремо: `TimeLimitNumbers` звіряє сталу і типові значення параметрів із 15 с,
а `LiteralTimeLimits` проганяє буквальні 15 с і 10 с лише з METHOD_SYNC_LITERAL_NFR4=1 (≈25 с).

FR-30 тут доведено частково: один запит на метод, рядок запиту з `build_url`, свіжий `captured_at` поверх старої
фікстури. Сирий запит раннера на ту саму адресу доводить `add-field-verification`, заборону документації в брифі —
`add-sync-loop-and-report`. FR-27 (агента не кликали, бібліотека незмінна) і все, що видно лише на процесі CLI
(код `3`, рядок методу, stderr без трасування, прогін після невдалого методу), — `add-run-cli` і e2e-харнес.

Регресійні тести рецензії (`openspec/changes/add-input/review-round-1.md`, рішення — tasks.md, розділ 6) позначено
коментарем `# Regression: review add-input R1-NN`.
"""
import dataclasses
import datetime
import http.client
import http.server
import inspect
import json
import os
import pathlib
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import method_sync.live as live  # noqa: E402
import method_sync.registry as registry  # noqa: E402

PREMIUM, FUNDING, SCHEDULE = "/fapi/v1/premiumIndex", "/fapi/v1/fundingRate", "/fapi/v1/tradingSchedule"
EXCHANGE = "https://fapi.binance.com"
UNRESOLVABLE = "fapi.binance.invalid"
REFUSED = ("127.0.0.1", 9)
UNAVAILABLE = "жива відповідь недоступна"
NO_KEYS = "немає жодного ключа"
FIXTURE_FIELDS = ["args", "body", "captured_at", "http_status", "path"]
LONG_PATH = "/fapi/v1/" + "a" * 300  # slug довший за NAME_MAX файлової системи (255 на APFS)
LONG_SLUG = "fapi-v1-" + "a" * 300

# NFR-4 механізмом: ліміт діє на весь виклик. Числа спеки — у TimeLimitNumbers і LiteralTimeLimits.
SHORT = 0.3                          # ліміт для тихого сервера, повільного тіла і запізнілої відповіді
GRACE = 0.5                          # допуск понад ліміт на планувальник; неправильний механізм — 2,5 с і більше
IN_LIMIT = 0.75                      # ліміт для відповіді в його межах
IN_LIMIT_DELAY = IN_LIMIT * 10 / 15  # «відповідь через 10 с» при ліміті 15 с — у тій самій пропорції

# Тіла, які віддає локальний сервер: байти на дроті, а не Python-об'єкти.
PREMIUM_RAW = (b'{"symbol":"BTCUSDT","markPrice":"85421.60000000","indexPrice":"85440.12500000",'
               b'"estimatedSettlePrice":"85398.20000000","lastFundingRate":"0.00010000","interestRate":"0.00010000",'
               b'"nextFundingTime":1790179200000,"time":1790169387000}')
FUNDING_RAW = (
    b'[{"symbol":"BTCUSDT","fundingTime":1790121600000,"fundingRate":"0.00010000","markPrice":"85120.40000000",'
    b'"rateType":"NORMAL"},'
    b'{"symbol":"BTCUSDT","fundingTime":1790150400000,"fundingRate":"-0.00002514","markPrice":"85390.10000000",'
    b'"rateType":"NORMAL"},'
    b'{"symbol":"BTCUSDT","fundingTime":1790179200000,"fundingRate":"0.00005000","markPrice":"","rateType":"NORMAL",'
    b'"note":"\xd0\xb7\xd0\xbd\xd1\x8f\xd1\x82\xd0\xbe","extra":{"nested":[1,2.5,null,true]}}]'
)
SCHEDULE_RAW = b'{"updateTime":1790150400000,"marketSchedules":{"EQUITY":{"sessions":[]}}}'
SMALL_RAW = b'{"symbol": "BTCUSDT"}'
DRIP_RAW = b'{"symbol":"BTCUSDT","markPrice":"85421.60000000"}'  # 50 байтів по 0,05 с — 2,5 с на все тіло
INVALID_SYMBOL_RAW = b'{"code":-1121,"msg":"Invalid symbol."}'
HTML_RAW = (b"<!DOCTYPE html><html><head><title>502 Bad Gateway</title></head>"
            b"<body><h1>502 Bad Gateway</h1></body></html>")
NOT_UTF8_RAW = b'{"symbol": "\xff"}'
OLD_FIXTURE = json.dumps({
    "path": PREMIUM, "args": {"symbol": "BTCUSDT"}, "captured_at": "2026-09-29T21:00:00.000000+00:00",
    "http_status": 200, "body": {"symbol": "BTCUSDT", "markPrice": "85000.00000000"},
}, indent=2).encode("utf-8")

# Регресії рецензії, раунд 1 (review-round-1.md; рішення — tasks.md, розділ 6).
# Непарний сурогат U+D800: JSON-escape і ті самі три байти ED A0 80 сирими. `json.loads` приймає обидва (байти декодує з
# `surrogatepass`), а в UTF-8 фікстури такий рядок не кодується.
SURROGATE_ESCAPE_RAW = b'{"symbol": "BTC\\ud800USDT"}'
SURROGATE_BYTES_RAW = b'{"symbol": "BTC\xed\xa0\x80USDT"}'
SURROGATE_BODIES = (("JSON-escape \\ud800", SURROGATE_ESCAPE_RAW), ("сирі байти ED A0 80", SURROGATE_BYTES_RAW))
# Тіло, яке сервер крапає по байту за 0,05 с понад дві хвилини: вердикт ліміту настає задовго до кінця.
ENDLESS_DRIP_RAW = b'{"symbol":"BTCUSDT","markPrice":"' + b"8" * 2400 + b'"}'
AFTER_VERDICT = 1.0  # стільки після вердикту ліміту можуть жити робочий потік і з'єднання (tasks.md 6.3)
FSIZE_LIMIT = 64     # ліміт розміру файлу дочірнього процесу: менший і за стару фікстуру, і за нову
# Текст сервера, який CLI надрукував би в термінал як є: заголовок вікна (OSC 0), очищення екрана, колір, BEL, NUL,
# DEL, CR/LF і C1-символ CSI (U+009B, у UTF-8 — C2 9B), а далі 64 КБ тексту з ESC на кожні 16 символів — тож обрізання
# до 200 символів раніше за заміну escape-послідовностями (1 символ → 4) вийшло б за межу.
HOSTILE_BODY_RAW = (b'\x1b]0;PWNED\x07\x1b[2J\r\n{"code":-1121,"msg":"\x1b[31mInvalid symbol.\x1b[0m"}\r\n'
                    b'\x00\x7f\xc2\x9b31m ' + b"\x1b[0mxxxxxxxxxxxx" * 4096)
# Статус-рядок не за HTTP: `http.client` читає його до 64 КБ як ISO-8859-1 і кладе в `BadStatusLine` разом із CR/LF.
HOSTILE_STATUS_LINE = b"\x1b]0;PWNED\x07\x1b[2J\x9b31m not-http " + b"\x1b[0mZZZZZZZZZZZZ" * 3750 + b"\r\n"
SERVER_TEXT_CHARS = 200  # скільки тексту сервера може нести причина (design.md D9, tasks.md 6.8)
EXCERPT_FRAME = 12       # власні слова інструмента навколо уривка: роздільник і «…»
RAW_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")            # керівні символи C0, DEL і C1
ESCAPED_ESC = re.compile(r"\\(?:x1b|u001b)", re.IGNORECASE)  # ESC як escape-послідовність, а не сирий символ


# ----------------------------------------------------------------------------------------------------------
# Межа: локальний сервер, шпигун у шві open_url, дочірній процес із хуком аудиту
# ----------------------------------------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Reply:
    """Що локальний сервер віддає на шлях."""

    status: int = 200
    body: bytes = b""
    headers: tuple = (("Content-Type", "application/json"),)
    delay: float = 0.0          # пауза перед статусом
    drip: float | None = None   # інтервал між байтами тіла: кожен байт вчасно, а все тіло — довго
    silent: bool = False        # прочитати запит і мовчати до кінця тесту
    raw: bytes | None = None    # уся відповідь дослівно, без статус-рядка й заголовків http.server


@dataclasses.dataclass(frozen=True)
class Seen:
    """Запит, який отримав сервер."""

    method: str
    target: str   # request-target з рядка запиту: шлях і рядок запиту, як їх надіслав клієнт
    headers: tuple  # імена заголовків малими літерами


class LocalServer:
    """Справжній HTTP-сервер на 127.0.0.1 з ефемерним портом: межа, на якій тест заступає біржу."""

    def __init__(self, routes, default=None):
        self.routes, self.default = dict(routes), default
        self.seen, self.handlers, self.lock, self.stopping = [], [], threading.Lock(), threading.Event()
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def serve(self):
                with owner.lock:
                    owner.handlers.append(threading.current_thread())
                    owner.seen.append(Seen(self.command, self.path, tuple(name.lower() for name in self.headers)))
                reply = owner.routes.get(urllib.parse.urlsplit(self.path).path, owner.default)
                if reply is None:
                    reply = Reply(404, b'{"code":404,"msg":"no such route on the test server"}')
                if reply.silent:
                    owner.stopping.wait()
                    return
                if reply.delay and owner.stopping.wait(reply.delay):
                    return
                if reply.raw is not None:
                    self.wfile.write(reply.raw)
                    return
                self.send_response(reply.status)
                for name, value in reply.headers:
                    self.send_header(name, value)
                if reply.status not in (204, 304):
                    self.send_header("Content-Length", str(len(reply.body)))
                self.end_headers()
                if reply.drip is None:
                    self.wfile.write(reply.body)
                    return
                for index in range(len(reply.body)):
                    self.wfile.write(reply.body[index:index + 1])
                    self.wfile.flush()
                    if owner.stopping.wait(reply.drip):
                        return

            do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = serve

            def log_message(self, *args):
                pass

        class Server(http.server.ThreadingHTTPServer):
            daemon_threads = True
            block_on_close = False

            def handle_error(self, request, client_address):
                pass  # клієнт пішов першим (ліміт, вердикт) — для сервера це не подія

        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.loop = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.loop.start()

    def requests(self):
        with self.lock:
            return list(self.seen)

    def threads(self):
        """Потоки самого сервера — цикл прийому й обробники запитів, — щоб не сплутати їх із потоками клієнта."""
        with self.lock:
            return [self.loop, *self.handlers]

    def quiet(self, until):
        """Чи завершились до моменту `until` усі обробники запитів. Крапання тіла до кінця тесту уривається лише
        тоді, коли клієнт закрив з'єднання: наступний запис у сокет падає."""
        with self.lock:
            handlers = list(self.handlers)
        for thread in handlers:
            thread.join(max(until - time.monotonic(), 0))
        return not any(thread.is_alive() for thread in handlers)

    def targets(self):
        return [seen.target for seen in self.requests()]

    def close(self):
        self.stopping.set()
        self.server.shutdown()
        self.server.server_close()


class Spy:
    """Шпигун у шві `open_url`: делегує в `live.no_redirect_open` і лише записує, з якою адресою його кликали."""

    def __init__(self):
        self.calls, self.lock = [], threading.Lock()

    def __call__(self, url, timeout):
        with self.lock:
            self.calls.append(getattr(url, "full_url", url))
        return live.no_redirect_open(url, timeout)


# Преамбула дочірнього процесу: хук аудиту пише відкриття файлів, чий шлях містить TOKEN (argv[1]), і всі
# з'єднання сокетів, з позначкою фази. Хук ніколи не кидає: виняток із хука зірвав би саму операцію.
AUDIT = r'''
import json, os, sys
TOKEN = sys.argv[1]
phase = ["import"]
events = []

def _hook(event, args):
    try:
        if event == "open" and args and not isinstance(args[0], int):
            opened = os.fsdecode(os.fspath(args[0]))
            if TOKEN in opened:
                events.append([phase[0], "open", opened])
        elif event == "socket.connect":
            address = args[1]
            events.append([phase[0], "socket.connect", list(address) if isinstance(address, tuple) else repr(address)])
    except Exception:
        pass

sys.addaudithook(_hook)
import method_sync.live as live
'''

# Три адреси зі сценарію «Адреса з іншою схемою відхиляється», а потім канарки: той самий файл і те саме
# з'єднання напряму, щоб довести, що хук їх бачить (інакше порожній список подій нічого б не доводив).
SCHEMES_CHILD = r'''
import socket
target = sys.argv[2]
results = []
phase[0] = "fetch"
for base in ("file://" + target, "ftp://127.0.0.1:9", "fapi.binance.com"):
    try:
        live.fetch(base, "/fapi/v1/tradingSchedule", {})
        results.append({"base": base, "outcome": "returned", "message": ""})
    except live.LiveUnavailable as error:
        results.append({"base": base, "outcome": "LiveUnavailable", "message": str(error)})
    except Exception as error:
        results.append({"base": base, "outcome": type(error).__name__, "message": str(error)})
phase[0] = "canary"
with open(os.path.join(target, "fapi", "v1", "tradingSchedule"), "rb") as handle:
    handle.read()
try:
    socket.create_connection(("127.0.0.1", 9), timeout=3).close()
except OSError:
    pass
print(json.dumps({"results": results, "events": events}))
'''

# Один capture на локальний сервер і одна спроба на порт, який ніхто не слухає: скільки з'єднань відкрив процес.
CONNECTIONS_CHILD = r'''
server_url, runs = sys.argv[2], sys.argv[3]
phase[0] = "capture"
live.capture(server_url, "/fapi/v1/premiumIndex", {"symbol": "BTCUSDT"}, runs)
phase[0] = "refused"
try:
    live.fetch("http://127.0.0.1:9", "/fapi/v1/premiumIndex", {"symbol": "BTCUSDT"})
    refused = "returned"
except live.LiveUnavailable:
    refused = "LiveUnavailable"
except Exception as error:
    refused = type(error).__name__
print(json.dumps({"events": events, "refused": refused}))
'''

# Запис фікстури, який ОС обриває посеред файлу: ліміт розміру файлу процесу (RLIMIT_FSIZE) менший за фікстуру. Python
# ігнорує SIGXFSZ, тож запис понад ліміт — OSError з EFBIG, а не смерть процесу; на канал stdout ліміт не діє. Канарка —
# запис на байт понад ліміт в інший файл: доводить, що ліміт у цій ОС справді діє (інакше перевірка була б порожньою).
FSIZE_CHILD = r'''
import errno, resource
server_url, runs, limit, canary = sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
resource.setrlimit(resource.RLIMIT_FSIZE, (limit, resource.getrlimit(resource.RLIMIT_FSIZE)[1]))
try:
    with open(canary, "wb") as handle:
        handle.write(b"c" * (limit + 1))
    cut = "written"
except OSError as error:
    cut = errno.errorcode.get(error.errno, str(error.errno))
try:
    fixture = live.capture(server_url, "/fapi/v1/premiumIndex", {"symbol": "BTCUSDT"}, runs)
    seen = {"outcome": "returned", "message": str(fixture)}
except Exception as error:
    seen = {"outcome": type(error).__name__, "message": str(error)}
print(json.dumps(dict(seen, canary=cut)))
'''


def run_child(test, script, *argv, **env):
    """Дочірній `python3` з хуком аудиту, cwd — тимчасовий каталог тесту; віддає JSON з останнього рядка stdout.
    Іменовані аргументи — додаткові змінні оточення дочірнього процесу."""
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"), **env)
    done = subprocess.run([sys.executable, "-c", AUDIT + script, *argv], cwd=test.tmp, env=env,
                          capture_output=True, text=True, timeout=60)
    test.assertEqual(done.returncode, 0, f"дочірній процес упав:\n{done.stderr}")
    return json.loads(done.stdout.strip().splitlines()[-1])


# ----------------------------------------------------------------------------------------------------------
# Передумови й оракули
# ----------------------------------------------------------------------------------------------------------

def refused_error():
    """Передумова: на 127.0.0.1:9 ніхто не слухає. Віддає помилку з'єднання — оракул тексту причини."""
    try:
        socket.create_connection(REFUSED, timeout=3).close()
    except ConnectionRefusedError as error:
        return error
    except OSError as error:
        raise AssertionError(f"передумова не виконана: з'єднання з 127.0.0.1:9 не відмовлено, а {error!r}") from error
    raise AssertionError("передумова не виконана: на 127.0.0.1:9 хтось слухає — недосяжної адреси не вийде")


def unresolvable_error():
    """Передумова: домен `.invalid` не резолвиться. Віддає помилку резолвера — оракул тексту причини."""
    try:
        socket.getaddrinfo(UNRESOLVABLE, 443)
    except socket.gaierror as error:
        return error
    raise AssertionError(f"передумова не виконана: {UNRESOLVABLE} резолвиться, хоча домен .invalid зарезервовано")


def json_error(raw):
    """Оракул: текст помилки розбору цих байтів як JSON."""
    try:
        json.loads(raw)
    except ValueError as error:
        return str(error)
    raise AssertionError(f"{raw!r} розбирається як JSON — кейс побудовано хибно")


def limit_pattern(seconds):
    """Причина «перевищено ліміт N с» із тим N, яке передано як timeout; кома чи крапка — байдуже."""
    whole, _, fraction = f"{seconds:g}".partition(".")
    number = whole + (rf"[.,]{fraction}0*" if fraction else r"(?:[.,]0+)?")
    return re.compile(rf"перевищено ліміт\D{{0,20}}(?<!\d){number}(?!\d)\s*с")


def status_pattern(status):
    """Статус числом, а не шматком іншого числа (порт сервера, розмір тіла)."""
    return re.compile(rf"(?<!\d){status}(?!\d)")


def read_json(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def strict_json(text):
    """Розбір за RFC 8259: `NaN`, `Infinity` і `-Infinity` — не JSON, тож на них розбір падає, а не дає float."""
    def refuse(token):
        raise ValueError(f"{token} — не JSON (RFC 8259)")
    return json.loads(text, parse_constant=refuse)


def files_outside(root, runs):
    """Файли під `root` поза піддеревом `runs`, відносно `root`; символьні посилання на каталоги не обходяться."""
    found = []
    for directory, _, names in os.walk(root):
        here = pathlib.Path(directory)
        if here == runs or runs in here.parents:
            continue
        found += [(here / name).relative_to(root).as_posix() for name in names]
    return sorted(found)


def git_init(path):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    subprocess.run(["git", "init", "--quiet", str(path)], check=True, capture_output=True, env=env)
    return path


class LiveCase(unittest.TestCase):
    """Спільне: тимчасовий `runs/`, локальний сервер на межі, вердикт `capture()` і вигляд фікстури."""

    def setUp(self):
        self.tmp = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.runs = self.tmp / "runs"
        self.started = datetime.datetime.now(datetime.UTC)

    def serve(self, routes=None, default=None):
        server = LocalServer(routes or {}, default)
        self.addCleanup(server.close)
        return server

    def written(self):
        """Усі файли під `runs/` тесту, відносно нього."""
        if not self.runs.exists():
            return []
        return sorted(item.relative_to(self.runs).as_posix() for item in self.runs.rglob("*") if item.is_file())

    def unavailable(self, base_url, path, args, **kwargs):
        """`capture()` визнає відповідь недоступною саме `LiveUnavailable`; віддає виняток."""
        try:
            live.capture(base_url, path, args, self.runs, **kwargs)
        except live.LiveUnavailable as error:
            return error
        except Exception as error:  # інший клас CLI показав би трасуванням (NFR-11)
            self.fail(f"capture() кинув {type(error).__name__}, а не LiveUnavailable: {error}")
        self.fail(f"capture() прийняв відповідь, яку спека називає недоступною: {base_url}{path}")

    def assertUnavailable(self, error, url, *reason, nothing_written=True):
        """Повідомлення каже «жива відповідь недоступна», містить URL, як його склав інструмент, і причину."""
        self.assertEqual(error.url, url)
        self.assertIsInstance(error.reason, str)
        self.assertTrue(error.reason.strip(), "причину не названо")
        message = str(error)
        self.assertIn(UNAVAILABLE, message)
        self.assertIn(url, message)
        self.assertIn(error.reason, message)
        for part in reason:
            if isinstance(part, re.Pattern):
                self.assertRegex(error.reason, part)
            else:
                self.assertIn(part, error.reason)
        if nothing_written:
            self.assertEqual(self.written(), [], "недоступна відповідь лишила файли в runs/")

    def assertFixture(self, fixture, path, args, raw):
        """FR-24: рівно п'ять полів; `body` — розбір сирого тіла; `captured_at` — ISO-8601 зі зсувом UTC цього тесту."""
        data = read_json(fixture)
        self.assertIsInstance(data, dict)
        self.assertEqual(sorted(data), FIXTURE_FIELDS)
        self.assertEqual(data["path"], path)
        self.assertEqual(data["args"], args)
        self.assertIs(type(data["http_status"]), int)
        self.assertEqual(data["http_status"], 200)
        self.assertEqual(data["body"], json.loads(raw))
        captured = datetime.datetime.fromisoformat(data["captured_at"])
        self.assertIsNotNone(captured.tzinfo, "captured_at без зсуву")
        self.assertEqual(captured.utcoffset(), datetime.timedelta(0), "captured_at не в UTC")
        self.assertGreaterEqual(captured, self.started, "captured_at раніший за початок тесту")
        self.assertLessEqual(captured, datetime.datetime.now(datetime.UTC))
        return data

    def settle(self, before, limit=3.0):
        """Дочекатися потоків, що з'явились після знімка: після вердикту потік живе до свого тайм-аута (D8)."""
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            alive = [thread for thread in threading.enumerate()
                     if thread not in before and thread is not threading.current_thread() and thread.is_alive()]
            if not alive:
                return
            alive[0].join(0.05)

    def record_thread_errors(self):
        """Винятки, що вилетіли з потоків: CLI надрукував би їх трасуванням у stderr."""
        errors, original = [], threading.excepthook
        threading.excepthook = lambda args: errors.append(f"{args.exc_type.__name__}: {args.exc_value}")
        self.addCleanup(setattr, threading, "excepthook", original)
        return errors

    def outcome(self, base_url, path, args, runs=None, **kwargs):
        """Що зробив `capture()`: шлях фікстури або виняток будь-якого класу — для перевірок диска, які від класу
        винятку не залежать (клас перевіряє окремий тест)."""
        try:
            return live.capture(base_url, path, args, self.runs if runs is None else runs, **kwargs)
        except Exception as error:
            return error

    def write_refused(self, base_url, path, args, runs):
        """`capture()` відмовився записати фікстуру саме `FixtureWriteError`; віддає виняток."""
        try:
            written = live.capture(base_url, path, args, runs)
        except live.FixtureWriteError as error:
            return error
        except Exception as error:  # інший клас CLI показав би трасуванням (NFR-11)
            self.fail(f"capture() кинув {type(error).__name__}, а не FixtureWriteError: {error}")
        self.fail(f"capture() записав фікстуру {written} (після розкриття шляху — {os.path.realpath(written)})")

    def threads_left(self, before, server, until):
        """Потоки клієнта — нові після знімка `before` і не серверні, — що ще живі в момент `until`."""
        while True:
            alive = [thread for thread in threading.enumerate()
                     if thread not in before and thread not in server.threads()
                     and thread is not threading.current_thread() and thread.is_alive()]
            remaining = until - time.monotonic()
            if not alive or remaining <= 0:
                return alive
            alive[0].join(min(remaining, 0.05))

    def assertStrictJson(self, path):
        """Файл — JSON за RFC 8259; віддає розібраний вміст."""
        text = pathlib.Path(path).read_text(encoding="utf-8")
        try:
            return strict_json(text)
        except ValueError as error:
            self.fail(f"{path} — не JSON за RFC 8259: {error}")

    def assertServerTextSafe(self, reason, bare):
        """Текст сервера в причині: жодного сирого керівного символу (C0, DEL, C1), ESC — escape-послідовністю, і не
        більше ніж 200 символів понад причину `bare`, де тексту сервера немає (плюс роздільник і «…»)."""
        raw = sorted(set(RAW_CONTROL.findall(reason)))
        self.assertEqual(raw, [], f"у причині сирі керівні символи: {reason[:160]!r}")
        self.assertRegex(reason, ESCAPED_ESC, "ESC не замінено escape-послідовністю")
        extra = len(reason) - len(bare)
        self.assertLessEqual(extra, SERVER_TEXT_CHARS + EXCERPT_FRAME,
                             f"текст сервера додав до причини {extra} символів, а межа — {SERVER_TEXT_CHARS}")


# ----------------------------------------------------------------------------------------------------------
# Сценарії
# ----------------------------------------------------------------------------------------------------------

class Preconditions(unittest.TestCase):
    """Передумови оточення (tasks.md 2.12) ідуть першими: не виконано — тест падає з поясненням, а не пропускається."""

    def test_nobody_listens_on_loopback_port_9(self):
        self.assertIsInstance(refused_error(), ConnectionRefusedError)

    def test_invalid_domain_does_not_resolve(self):
        self.assertIsInstance(unresolvable_error(), socket.gaierror)

    def test_long_slug_exceeds_the_file_name_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            limit = os.pathconf(tmp, "PC_NAME_MAX")
        self.assertLess(limit, len(LONG_SLUG), f"NAME_MAX = {limit}: каталог {len(LONG_SLUG)} символів створиться")


class BuildsUrl(unittest.TestCase):
    """Вимога «Живий виклик методу» (FR-23): `base_url` без кінцевої `/` плюс `path`, для непорожніх `args` —
    `?` і пари в порядку реєстру, закодовані `urllib.parse.urlencode`."""

    def test_args_in_registry_order(self):
        self.assertEqual(live.build_url(EXCHANGE, FUNDING, {"symbol": "BTCUSDT", "limit": 3}),
                         "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=3")

    def test_no_args_no_question_mark(self):
        self.assertEqual(live.build_url(EXCHANGE, SCHEDULE, {}), "https://fapi.binance.com/fapi/v1/tradingSchedule")

    def test_trailing_slash_of_base_url_dropped(self):
        self.assertEqual(live.build_url(EXCHANGE + "/", SCHEDULE, {}), "https://fapi.binance.com/fapi/v1/tradingSchedule")

    def test_values_encoded_by_urlencode(self):
        args = {"symbol": "BTC USDT", "note": "a&b=c", "day": datetime.date(2026, 9, 30)}
        url = live.build_url(EXCHANGE, FUNDING, args)
        self.assertEqual(url, f"{EXCHANGE}{FUNDING}?{urllib.parse.urlencode(args)}")
        self.assertEqual(url, f"{EXCHANGE}{FUNDING}?symbol=BTC+USDT&note=a%26b%3Dc&day=2026-09-30")


class LiveCall(LiveCase):
    """Вимоги «Живий виклик методу» і «Живий виклик лише за адресою http чи https» (FR-23)."""

    def test_one_get_on_the_built_url_without_keys_or_signature(self):
        """Сценарій «Адреса з аргументами в порядку реєстру, без ключів» на локальному сервері."""
        server = self.serve({FUNDING: Reply(body=FUNDING_RAW)})
        spy = Spy()
        live.capture(server.url, FUNDING, {"symbol": "BTCUSDT", "limit": 3}, self.runs, open_url=spy)
        requests = server.requests()
        self.assertEqual([(seen.method, seen.target) for seen in requests],
                         [("GET", "/fapi/v1/fundingRate?symbol=BTCUSDT&limit=3")])
        self.assertNotIn("x-mbx-apikey", requests[0].headers)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(requests[0].target).query)
        for key in ("timestamp", "recvWindow", "signature"):
            self.assertNotIn(key, query)
        self.assertEqual(spy.calls, [f"{server.url}/fapi/v1/fundingRate?symbol=BTCUSDT&limit=3"])
        for function in (live.fetch, live.capture):
            self.assertNotIn("credentials", inspect.signature(function).parameters,
                             "credentials не мають шляху до живого виклику (FR-3)")

    def test_method_without_args(self):
        """Сценарій «Метод без аргументів»: запис без поля `args` і з `args = {}` із реєстру — адреса без `?`,
        `args` у фікстурі — `{}`."""
        server = self.serve({SCHEDULE: Reply(body=SCHEDULE_RAW)})
        lib = git_init(self.tmp / "lib")
        for number, (label, args_line) in enumerate((("без поля args", ""), ("args = {}", "args = {}\n")), 1):
            with self.subTest(label):
                source = self.tmp / f"registry-{number}.toml"
                source.write_text(
                    f"lib = {json.dumps(str(lib))}\nverify_cmd = \"mvn -q -DskipTests test-compile\"\n\n"
                    f"[live]\nbase_url = {json.dumps(server.url)}\n\n[[method]]\npath = \"{SCHEDULE}\"\n"
                    "model = \"com.example.binanceFutures.response.TradingScheduleResponse\"\n"
                    f"client_method = \"getTradingSchedule\"\n{args_line}", encoding="utf-8")
                loaded = registry.load(str(source))
                method = loaded.methods[0]
                self.assertEqual(method.args, {})
                runs = self.tmp / f"runs-{number}"
                fixture = live.capture(loaded.base_url, method.path, method.args, runs)
                self.assertEqual(server.targets(), ["/fapi/v1/tradingSchedule"] * number)
                self.assertEqual(read_json(fixture)["args"], {})

    def test_other_scheme_rejected_before_anything_is_opened(self):
        """Сценарій «Адреса з іншою схемою відхиляється»: `LiveUnavailable` з URL, фікстури немає, шов `open_url`
        не кликали. `data:` — ще одна схема, яку `urllib` обслужив би без мережі."""
        target = self.tmp / "T"
        (target / "fapi" / "v1").mkdir(parents=True)
        (target / "fapi" / "v1" / "tradingSchedule").write_text('{"updateTime": 1}', encoding="utf-8")
        for base in (f"file://{target}", "ftp://127.0.0.1:9", "fapi.binance.com", "data:application/json,"):
            with self.subTest(base=base):
                spy = Spy()
                self.assertUnavailable(self.unavailable(base, SCHEDULE, {}, open_url=spy), base + SCHEDULE)
                self.assertEqual(spy.calls, [], "open_url кликали, хоча схему мали відхилити до відкриття")

    def test_rejected_scheme_opens_no_file_and_no_socket(self):
        """Та сама вимога через хук аудиту в дочірньому процесі: під час трьох спроб немає ні відкриття
        `<T>/fapi/v1/tradingSchedule`, ні жодного з'єднання, зокрема з 127.0.0.1:9."""
        target = self.tmp / "T"
        (target / "fapi" / "v1").mkdir(parents=True)
        schedule_file = target / "fapi" / "v1" / "tradingSchedule"
        schedule_file.write_text('{"updateTime": 1}', encoding="utf-8")
        seen = run_child(self, SCHEMES_CHILD, self.tmp.name, str(target))
        self.assertEqual([result["base"] for result in seen["results"]],
                         [f"file://{target}", "ftp://127.0.0.1:9", "fapi.binance.com"])
        for result in seen["results"]:
            with self.subTest(base=result["base"]):
                self.assertEqual(result["outcome"], "LiveUnavailable", result["message"])
                self.assertIn(UNAVAILABLE, result["message"])
                self.assertIn(result["base"] + SCHEDULE, result["message"])
        self.assertEqual([event for event in seen["events"] if event[0] == "fetch"], [],
                         "спроба з відхиленою схемою щось відкрила")
        canary = [event[1:] for event in seen["events"] if event[0] == "canary"]
        self.assertIn(["open", str(schedule_file)], canary, "хук не бачить відкриття файлу — перевірка була б порожньою")
        self.assertIn(["socket.connect", ["127.0.0.1", 9]], canary, "хук не бачить з'єднань — перевірка була б порожньою")


class TimeLimit(LiveCase):
    """Вимога «Ліміт часу живого виклику» (NFR-4) на короткому `timeout`: ліміт діє від початку спроби до кінця
    читання тіла, а перевищення — недоступна відповідь з URL і «перевищено ліміт»."""

    def test_silent_server_stops_the_call_at_the_limit(self):
        """Сценарій «Сервер приймає з'єднання і мовчить»."""
        server = self.serve({PREMIUM: Reply(silent=True)})
        started = time.monotonic()
        error = self.unavailable(server.url, PREMIUM, {"symbol": "BTCUSDT"}, timeout=SHORT)
        elapsed = time.monotonic() - started
        self.assertLessEqual(elapsed, SHORT + GRACE, f"виклик тривав {elapsed:.2f} с при ліміті {SHORT} с")
        self.assertUnavailable(error, f"{server.url}{PREMIUM}?symbol=BTCUSDT", limit_pattern(SHORT))
        self.assertEqual(len(server.requests()), 1)

    def test_slow_body_counts_against_the_whole_call(self):
        """Тіло тече по байту за 0,05 с (2,5 с на все): кожна операція сокета вкладається в ліміт, весь виклик — ні.
        Ліміт на одну операцію сокета, як у v1, дочитав би тіло."""
        server = self.serve({PREMIUM: Reply(body=DRIP_RAW, drip=0.05)})
        started = time.monotonic()
        error = self.unavailable(server.url, PREMIUM, {"symbol": "BTCUSDT"}, timeout=SHORT)
        elapsed = time.monotonic() - started
        self.assertLessEqual(elapsed, SHORT + GRACE, f"виклик тривав {elapsed:.2f} с при ліміті {SHORT} с")
        self.assertUnavailable(error, f"{server.url}{PREMIUM}?symbol=BTCUSDT", limit_pattern(SHORT))
        self.assertEqual(len(server.requests()), 1)

    def test_answer_within_the_limit_is_captured(self):
        """Сценарій «Відповідь у межах ліміту»: 10 с при 15 с — тут та сама пропорція на коротшому ліміті."""
        server = self.serve({PREMIUM: Reply(body=SMALL_RAW, delay=IN_LIMIT_DELAY)})
        started = time.monotonic()
        fixture = live.capture(server.url, PREMIUM, {"symbol": "BTCUSDT"}, self.runs, timeout=IN_LIMIT)
        self.assertGreaterEqual(time.monotonic() - started, IN_LIMIT_DELAY, "сервер не тримав відповідь")
        self.assertFixture(fixture, PREMIUM, {"symbol": "BTCUSDT"}, SMALL_RAW)

    def test_answer_after_the_verdict_leaves_nothing_behind(self):
        """Придатна відповідь приходить після вердикту: потік, що дожив до неї, не пише фікстури, не повторює запит
        і не падає трасуванням (design.md D8; FR-28)."""
        errors = self.record_thread_errors()
        server = self.serve({PREMIUM: Reply(body=PREMIUM_RAW, delay=SHORT + 0.15)})
        before = set(threading.enumerate())
        error = self.unavailable(server.url, PREMIUM, {"symbol": "BTCUSDT"}, timeout=SHORT)
        self.assertUnavailable(error, f"{server.url}{PREMIUM}?symbol=BTCUSDT", limit_pattern(SHORT))
        self.settle(before)
        self.assertEqual(self.written(), [], "запізніла відповідь потрапила в runs/")
        self.assertEqual(len(server.requests()), 1, "після вердикту був ще запит")
        self.assertEqual(errors, [], "потік після вердикту впав")

    # Regression: review add-input R1-03, R1-08, R1-14 — після вердикту ліміту робочий потік і сокет жили, доки сервер крапав тіло
    def test_worker_and_connection_end_soon_after_the_verdict(self):
        """Сервер надіслав заголовки і крапає тіло по байту за 0,05 с понад дві хвилини: кожна операція сокета
        вкладається в його тайм-аут, тож сам по собі потік не відпаде. Після `LiveUnavailable` робочий потік не
        дочитує тіло, а з'єднання закрито — сервер перестає крапати; обидва не пізніше ніж за 1 с (design.md D8)."""
        errors = self.record_thread_errors()
        server = self.serve({PREMIUM: Reply(body=ENDLESS_DRIP_RAW, drip=0.05)})
        before = set(threading.enumerate())
        error = self.unavailable(server.url, PREMIUM, {"symbol": "BTCUSDT"}, timeout=SHORT)
        verdict = time.monotonic()
        self.assertUnavailable(error, f"{server.url}{PREMIUM}?symbol=BTCUSDT", limit_pattern(SHORT))
        left = self.threads_left(before, server, until=verdict + AFTER_VERDICT)
        self.assertEqual([thread.name for thread in left], [],
                         f"через {AFTER_VERDICT:g} с після вердикту живий потік клієнта, що дочитує тіло")
        self.assertTrue(server.quiet(until=verdict + AFTER_VERDICT),
                        f"через {AFTER_VERDICT:g} с після вердикту з'єднання відкрите: сервер і далі віддає тіло")
        self.assertEqual(len(server.requests()), 1)
        self.assertEqual(errors, [], "потік після вердикту впав")


class TimeLimitNumbers(unittest.TestCase):
    """Числа NFR-4 там, де їх тримає код: ліміт живого виклику 15 с — стала і типове значення `timeout`.
    «Відповідь через 10 с» — затримка сервера в сценарії, а не стала коду: TimeLimit тримає ту саму пропорцію."""

    def test_default_limit_is_15_seconds(self):
        self.assertEqual(live.TIMEOUT_SECONDS, 15)
        for function in (live.fetch, live.capture):
            with self.subTest(function.__name__):
                self.assertEqual(inspect.signature(function).parameters["timeout"].default, 15)


@unittest.skipUnless(os.environ.get("METHOD_SYNC_LITERAL_NFR4") == "1",
                     "буквальні 15 с і 10 с зі сценаріїв NFR-4 (≈25 с) — лише з METHOD_SYNC_LITERAL_NFR4=1; "
                     "типовий прогін доводить механізм у TimeLimit, а числа — у TimeLimitNumbers")
class LiteralTimeLimits(LiveCase):
    """Сценарії NFR-4 з буквальними числами і типовим `timeout`."""

    def test_silent_server_given_up_within_16_seconds(self):
        server = self.serve({PREMIUM: Reply(silent=True)})
        started = time.monotonic()
        error = self.unavailable(server.url, PREMIUM, {"symbol": "BTCUSDT"})
        elapsed = time.monotonic() - started
        self.assertLessEqual(elapsed, 16, f"виклик тривав {elapsed:.2f} с")
        self.assertUnavailable(error, f"{server.url}{PREMIUM}?symbol=BTCUSDT", limit_pattern(15))

    def test_answer_after_10_seconds_is_captured(self):
        server = self.serve({PREMIUM: Reply(body=SMALL_RAW, delay=10)})
        fixture = live.capture(server.url, PREMIUM, {"symbol": "BTCUSDT"}, self.runs)
        self.assertFixture(fixture, PREMIUM, {"symbol": "BTCUSDT"}, SMALL_RAW)


class Fixture(LiveCase):
    """Вимога «Фікстура живої відповіді» (FR-24)."""

    def test_fixture_fields_in_the_method_directory(self):
        """Сценарій «Поля фікстури в каталозі інструмента»: масив об'єктів, п'ять полів, у runs/ більше нічого."""
        server = self.serve({FUNDING: Reply(body=FUNDING_RAW)})
        args = {"symbol": "BTCUSDT", "limit": 3}
        fixture = live.capture(server.url, FUNDING, args, self.runs)
        self.assertIsInstance(fixture, pathlib.Path)
        self.assertTrue(os.path.samefile(fixture, self.runs / "fapi-v1-fundingRate" / "fixture.json"))
        data = self.assertFixture(fixture, FUNDING, args, FUNDING_RAW)
        self.assertEqual(list(data["args"]), ["symbol", "limit"])
        self.assertEqual(self.written(), ["fapi-v1-fundingRate/fixture.json"])

    def test_fetch_returns_status_and_parsed_body(self):
        server = self.serve({PREMIUM: Reply(body=PREMIUM_RAW)})
        status, body = live.fetch(server.url, PREMIUM, {"symbol": "BTCUSDT"})
        self.assertEqual((status, body), (200, json.loads(PREMIUM_RAW)))
        self.assertEqual(server.targets(), ["/fapi/v1/premiumIndex?symbol=BTCUSDT"])

    def test_runs_dir_is_the_tools_own_whatever_the_cwd(self):
        """`runs/` інструмента не залежить від робочого каталогу: дочірній процес із cwd у тимчасовому каталозі."""
        env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
        done = subprocess.run([sys.executable, "-c", "import method_sync.live as live; print(live.RUNS_DIR)"],
                              cwd=self.tmp, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(pathlib.Path(done.stdout.strip()), REPO / "runs")
        self.assertEqual(live.RUNS_DIR, REPO / "runs")
        self.assertEqual(inspect.signature(live.capture).parameters["runs_dir"].default, live.RUNS_DIR)

    def test_args_json_cannot_represent_are_stored_as_strings(self):
        """Сценарій «Значення args, якого JSON не представляє»: дата з реєстру стає рядком."""
        server = self.serve({PREMIUM: Reply(body=PREMIUM_RAW)})
        fixture = live.capture(server.url, PREMIUM, {"symbol": "BTCUSDT", "day": datetime.date(2026, 9, 30)}, self.runs)
        self.assertEqual(read_json(fixture)["args"], {"symbol": "BTCUSDT", "day": "2026-09-30"})
        self.assertEqual(server.targets(), ["/fapi/v1/premiumIndex?symbol=BTCUSDT&day=2026-09-30"])

    def test_unwritable_fixture_is_a_write_error_and_the_next_method_still_captures(self):
        """Сценарій «Фікстуру не вдалося записати»: `FixtureWriteError` зі шляхом каталогу, а наступний метод пише
        свою фікстуру. Код `1` і рядок методу на процесі CLI — `add-run-cli`."""
        server = self.serve(default=Reply(body=PREMIUM_RAW))
        directory = self.runs / LONG_SLUG
        try:
            live.capture(server.url, LONG_PATH, {}, self.runs)
        except live.FixtureWriteError as error:
            failure = error
        except Exception as error:
            self.fail(f"capture() кинув {type(error).__name__}, а не FixtureWriteError: {error}")
        else:
            self.fail("фікстуру з іменем каталогу, довшим за NAME_MAX, нібито записано")
        self.assertIn(str(directory), str(failure))
        self.assertIn(pathlib.Path(failure.path), (directory, directory / "fixture.json"))
        fixture = live.capture(server.url, PREMIUM, {"symbol": "BTCUSDT"}, self.runs)
        self.assertFixture(fixture, PREMIUM, {"symbol": "BTCUSDT"}, PREMIUM_RAW)
        self.assertEqual(server.targets(), [LONG_PATH, "/fapi/v1/premiumIndex?symbol=BTCUSDT"])
        self.assertEqual(self.written(), ["fapi-v1-premiumIndex/fixture.json"])

    # Regression: review add-input R1-01 — гілка запису FixtureWriteError не мала тесту, а обірваний запис лишав обрізану фікстуру
    def test_failed_write_names_the_fixture_and_leaves_the_old_one_whole(self):
        """Сценарій «Фікстуру не вдалося записати» для гілки запису: каталог методу є, а файл не пишеться (FR-24).
        `fixture.json` — каталог; і запис, який ОС обриває посеред файлу (ліміт розміру файлу процесу в дочірньому
        `python3`), поверх фікстури попереднього прогону. Щоразу `FixtureWriteError`, що називає шлях фікстури, а в
        каталозі методу немає ні тимчасових файлів, ні обрізаної фікстури: запис атомарний (design.md D10)."""
        server = self.serve({PREMIUM: Reply(body=PREMIUM_RAW)})
        root = self.tmp.resolve()  # без символьних посилань: шлях до й після розкриття однаковий
        with self.subTest("fixture.json — каталог"):
            method = root / "runs-directory" / "fapi-v1-premiumIndex"
            fixture = method / "fixture.json"
            fixture.mkdir(parents=True)
            error = self.write_refused(server.url, PREMIUM, {"symbol": "BTCUSDT"}, method.parent)
            self.assertIn(str(fixture), str(error))
            self.assertEqual(os.listdir(method), ["fixture.json"], "після збою в каталозі методу лишились інші файли")
            self.assertEqual(os.listdir(fixture), [], "у каталог fixture.json щось записано")
        with self.subTest("запис обірвано посеред файлу поверх старої фікстури"):
            method = root / "runs-cut-off" / "fapi-v1-premiumIndex"
            fixture = method / "fixture.json"
            method.mkdir(parents=True)
            fixture.write_bytes(OLD_FIXTURE)
            seen = run_child(self, FSIZE_CHILD, "no-file-events", server.url, str(method.parent), str(FSIZE_LIMIT),
                             str(root / "canary.bin"), PYTHONDONTWRITEBYTECODE="1")
            self.assertEqual(seen["canary"], "EFBIG", "передумова: ліміт розміру файлу мав обірвати запис канарки")
            kept = fixture.read_bytes()
            self.assertEqual(kept, OLD_FIXTURE, f"після обірваного запису фікстура має {len(kept)} байтів замість "
                                                f"{len(OLD_FIXTURE)} попереднього прогону; capture() дав {seen}")
            self.assertEqual(seen["outcome"], "FixtureWriteError", seen["message"])
            self.assertIn(str(fixture), seen["message"])
            self.assertEqual(os.listdir(method), ["fixture.json"], "після збою в каталозі методу лишились інші файли")

    # Regression: review add-input R1-11, R1-16 — slug «..» і символьне посилання runs/<slug> виводили запис фікстури за межі runs/
    def test_fixture_is_never_written_outside_runs_dir(self):
        """Фікстура лежить у `runs/` інструмента (FR-24, принцип VII), а шлях звіряється після розкриття `..` і
        символьних посилань — половина сценарію FR-91 для фікстури; код `1` і рядок методу на процесі CLI — `add-run-cli`.
        `path = "/.."` дає slug `..`; `runs/fapi-v1-fundingRate` — символьне посилання на `docs/` поза `runs/`.
        Щоразу `FixtureWriteError`, що називає розкритий шлях фікстури, а поза `runs/` не з'являється жодного файлу."""
        server = self.serve(default=Reply(body=FUNDING_RAW))
        root = self.tmp.resolve()
        tool, docs = root / "tool", root / "docs"
        runs = tool / "runs"
        runs.mkdir(parents=True)
        docs.mkdir()
        (runs / "fapi-v1-fundingRate").symlink_to(docs, target_is_directory=True)
        cases = (('path = "/.." — slug ".."', "/..", tool / "fixture.json"),
                 ("runs/fapi-v1-fundingRate — посилання на docs/", FUNDING, docs / "fixture.json"))
        for label, path, target in cases:
            with self.subTest(label):
                error = self.write_refused(server.url, path, {}, runs)
                self.assertIn(str(target), str(error), "повідомлення не називає розкритий шлях фікстури")
                self.assertEqual(files_outside(root, runs), [], "поза runs/ з'явились файли")
                self.assertEqual(os.listdir(docs), [], "у каталог, на який веде посилання, щось записано")

    # Regression: review add-input R1-11 — запис фікстури йшов крізь символьне посилання fixture.json і переписував файл поза runs/
    def test_symlinked_fixture_file_is_not_followed_outside_runs_dir(self):
        """Той самий принцип VII для самого файлу: `runs/<slug>/fixture.json` — символьне посилання на файл поза
        `runs/`. Той файл лишається байт у байт. Відмова — лише `FixtureWriteError`; якщо ж фікстуру записано, то
        звичайним файлом у `runs/<slug>/`, а не крізь посилання."""
        server = self.serve({PREMIUM: Reply(body=PREMIUM_RAW)})
        root = self.tmp.resolve()
        runs = root / "tool" / "runs"
        outside = root / "docs" / "notes.json"
        outside.parent.mkdir()
        outside.write_bytes(OLD_FIXTURE)
        link = runs / "fapi-v1-premiumIndex" / "fixture.json"
        link.parent.mkdir(parents=True)
        link.symlink_to(outside)
        outcome = self.outcome(server.url, PREMIUM, {"symbol": "BTCUSDT"}, runs)
        self.assertEqual(outside.read_bytes(), OLD_FIXTURE, f"файл поза runs/ переписано; capture() дав {outcome!r}")
        if isinstance(outcome, Exception):
            self.assertIsInstance(outcome, live.FixtureWriteError)
        else:
            self.assertFalse(link.is_symlink(), "фікстуру записано крізь посилання")
            self.assertFixture(link, PREMIUM, {"symbol": "BTCUSDT"}, PREMIUM_RAW)

    # Regression: review add-input R1-04 — nan/inf з args лягали у фікстуру голими NaN/Infinity, і фікстура не була JSON
    def test_nan_and_infinity_in_args_are_stored_as_strings(self):
        """FR-24: значення `args`, якого JSON не представляє, — рядком. TOML дає `nan`, `inf` і `-inf` як float, а
        JSON за RFC 8259 їх не знає: у фікстурі — той самий рядок, що пішов у рядок запиту (`urlencode` бере `str`),
        а вся фікстура розбирається строгим розбирачем, зокрема з `nan` усередині масиву."""
        server = self.serve({PREMIUM: Reply(body=PREMIUM_RAW)})
        for key, value in (("x", float("nan")), ("y", float("inf")), ("z", float("-inf"))):
            with self.subTest(f"{key} = {value}"):
                fixture = live.capture(server.url, PREMIUM, {"symbol": "BTCUSDT", key: value}, self.runs)
                data = self.assertStrictJson(fixture)
                self.assertEqual(data["args"], {"symbol": "BTCUSDT", key: str(value)})
                self.assertEqual(server.targets()[-1], f"/fapi/v1/premiumIndex?symbol=BTCUSDT&{key}={value}")
        with self.subTest("nan усередині масиву"):
            fixture = live.capture(server.url, PREMIUM, {"symbol": "BTCUSDT", "ids": [float("nan"), 1.5]}, self.runs)
            self.assertEqual(list(self.assertStrictJson(fixture)["args"]), ["symbol", "ids"])

    # Regression: review add-input R1-04 — число за межами float (1e999) ставало inf і лягало у фікстуру голим Infinity
    def test_number_beyond_float_range_never_leaves_a_non_json_fixture(self):
        """Варіант R1-04 без токенів: `1e999` — число за RFC 8259, але `float` його не вміщає і дає `inf`. Хай як
        `capture()` з ним обійдеться, назовні — лише виняток слайсу, а фікстура, якщо її записано, — JSON за RFC 8259.
        Яким має бути саме значення, tasks.md 6.4 не каже, тож тест його не фіксує."""
        server = self.serve({PREMIUM: Reply(body=b'{"symbol":"BTCUSDT","markPrice":1e999}')})
        outcome = self.outcome(server.url, PREMIUM, {"symbol": "BTCUSDT"})
        if isinstance(outcome, Exception):
            self.assertIsInstance(outcome, (live.LiveUnavailable, live.FixtureWriteError), repr(outcome))
        else:
            self.assertStrictJson(outcome)


class Slug(LiveCase):
    """Вимога «Slug каталогу методу» (FR-25): крайні `/` відкидаються, решта стають `-`, інше — як є."""

    def test_fixture_directory_named_after_the_path(self):
        """Сценарій «Звичайний шлях і шлях із кінцевою похилою рискою»."""
        server = self.serve({PREMIUM: Reply(body=PREMIUM_RAW), SCHEDULE + "/": Reply(body=SCHEDULE_RAW)})
        premium = live.capture(server.url, PREMIUM, {}, self.runs)
        schedule = live.capture(server.url, SCHEDULE + "/", {}, self.runs)
        self.assertTrue(os.path.samefile(premium, self.runs / "fapi-v1-premiumIndex" / "fixture.json"))
        self.assertTrue(os.path.samefile(schedule, self.runs / "fapi-v1-tradingSchedule" / "fixture.json"))
        self.assertEqual(sorted(item.name for item in self.runs.iterdir()), ["fapi-v1-premiumIndex", "fapi-v1-tradingSchedule"])
        self.assertEqual(server.targets(), ["/fapi/v1/premiumIndex", "/fapi/v1/tradingSchedule/"])

    def test_slug_rule(self):
        cases = {
            "/fapi/v1/premiumIndex": "fapi-v1-premiumIndex",
            "/fapi/v1/tradingSchedule/": "fapi-v1-tradingSchedule",
            "fapi/v1/ticker/24hr": "fapi-v1-ticker-24hr",
            "/fapi/v1/premium Index": "fapi-v1-premium Index",
            "/fapi/v1/Ärger_x.y": "fapi-v1-Ärger_x.y",
        }
        for path, slug in cases.items():
            with self.subTest(path=path):
                self.assertEqual(registry.slug_for(path), slug)
                self.assertEqual(registry.Method(path=path, model="m", client_method="c").slug, slug)


class UnavailableResponse(LiveCase):
    """Вимога «Недоступна жива відповідь зупиняє метод» (FR-26, NFR-11): `LiveUnavailable` з URL і причиною,
    рівно один запит до сервера, якого досягла спроба, і жодного — до того, якого вона не досягла."""

    def test_unresolvable_host(self):
        expected = unresolvable_error()
        error = self.unavailable(f"https://{UNRESOLVABLE}", PREMIUM, {"symbol": "BTCUSDT"})
        self.assertUnavailable(error, f"https://{UNRESOLVABLE}/fapi/v1/premiumIndex?symbol=BTCUSDT", expected.strerror)

    def test_connection_refused(self):
        expected = refused_error()
        error = self.unavailable("http://127.0.0.1:9", PREMIUM, {"symbol": "BTCUSDT"})
        self.assertUnavailable(error, "http://127.0.0.1:9/fapi/v1/premiumIndex?symbol=BTCUSDT", expected.strerror)

    def test_space_in_path_rejected_by_the_http_client(self):
        server = self.serve(default=Reply(body=PREMIUM_RAW))  # досягни спроба сервера — відповідь була б придатною
        path = "/fapi/v1/premium Index"
        with self.assertRaises(http.client.InvalidURL) as client:
            urllib.request.urlopen(server.url + path, timeout=1)  # оракул: так мережевий клієнт відповідає на цю адресу
        error = self.unavailable(server.url, path, {})
        self.assertUnavailable(error, server.url + path, str(client.exception))
        self.assertEqual(server.requests(), [], "адресу з пробілом надіслали")

    def test_other_addresses_the_client_rejects(self):
        """Решта адрес, які відхиляє клієнт чи розбір URL (design.md D9): нечисловий порт, зламаний IPv6, мітка
        IDNA довша за 63 символи. Реєстр адрес не перевіряє, тож погана адреса — теж недоступна відповідь."""
        for base in ("http://127.0.0.1:abc", "http://[::1", "http://" + "a" * 64 + ".com"):
            with self.subTest(base=base):
                self.assertUnavailable(self.unavailable(base, PREMIUM, {}), base + PREMIUM)

    def test_status_empty_and_non_json_bodies(self):
        """Сценарій «Кожен випадок недоступної відповіді»: 400 з поясненням біржі, 204, порожнє тіло, пробіли, HTML;
        і тіло не в UTF-8 (design.md, «Що v1 робив інакше»)."""
        cases = (
            ("400 з тілом біржі", Reply(400, INVALID_SYMBOL_RAW), "NOSUCHSYMBOL",
             (status_pattern(400), "Invalid symbol.")),  # «Invalid symbol.» — частина тіла в причині, design.md D9
            ("204 без тіла", Reply(204), "BTCUSDT", (status_pattern(204),)),
            ("200 і тіло нульової довжини", Reply(200, b""), "BTCUSDT", ("порожн",)),
            ("200 і тіло з самих пробілів", Reply(200, b" \r\n\t "), "BTCUSDT", ("порожн",)),
            ("200 і HTML-сторінка", Reply(200, HTML_RAW, (("Content-Type", "text/html; charset=utf-8"),)), "BTCUSDT",
             ("JSON", json_error(HTML_RAW))),
            ("200 і тіло не в UTF-8", Reply(200, NOT_UTF8_RAW), "BTCUSDT", ("JSON", json_error(NOT_UTF8_RAW))),
        )
        for label, reply, symbol, reason in cases:
            with self.subTest(label):
                server = self.serve({PREMIUM: reply})
                error = self.unavailable(server.url, PREMIUM, {"symbol": symbol})
                self.assertUnavailable(error, f"{server.url}{PREMIUM}?symbol={symbol}", *reason)
                self.assertEqual(len(server.requests()), 1)

    def test_redirect_is_not_followed(self):
        """Сценарій «Перенаправлення не виконується» (301) і решта 3xx із тексту вимоги, типовим відкривачем."""
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                server = self.serve({PREMIUM: Reply(status, headers=(("Location", "/elsewhere/ok"),)),
                                     "/elsewhere/ok": Reply(body=PREMIUM_RAW)})
                error = self.unavailable(server.url, PREMIUM, {"symbol": "BTCUSDT"})
                self.assertUnavailable(error, f"{server.url}{PREMIUM}?symbol=BTCUSDT", status_pattern(status))
                self.assertEqual(server.targets(), ["/fapi/v1/premiumIndex?symbol=BTCUSDT"])

    # Regression: review add-input R1-01, R1-10 — непарний сурогат у тілі 200 вилітав із capture() голим UnicodeEncodeError
    def test_body_with_a_lone_surrogate_is_unavailable(self):
        """Тіло 200 з непарним сурогатом U+D800 — JSON-escape чи сирі байти ED A0 80: розбір JSON його приймає, а
        фікстура, що зберігає тіло як є в UTF-8 (FR-24), його не закодує. Це недоступна відповідь з URL (FR-26), а
        не четвертий клас винятку (design.md, Goals), і фікстури немає."""
        for label, raw in SURROGATE_BODIES:
            with self.subTest(label):
                server = self.serve({PREMIUM: Reply(body=raw)})
                error = self.unavailable(server.url, PREMIUM, {"symbol": "BTCUSDT"})
                self.assertUnavailable(error, f"{server.url}{PREMIUM}?symbol=BTCUSDT")
                self.assertEqual(len(server.requests()), 1)

    # Regression: review add-input R1-04 — тіло з NaN/Infinity/-Infinity вважалось JSON і лягало у фікстуру голими токенами
    def test_nan_and_infinity_bodies_are_not_json(self):
        """RFC 8259 не знає `NaN`, `Infinity` і `-Infinity`, хоча `json.loads` за замовчуванням їх приймає. Тіло з
        ними — «тіло не розбирається як JSON» (FR-26), фікстури немає."""
        for token in (b"NaN", b"Infinity", b"-Infinity"):
            with self.subTest(token.decode()):
                server = self.serve({PREMIUM: Reply(body=b'{"symbol":"BTCUSDT","markPrice":' + token + b"}")})
                error = self.unavailable(server.url, PREMIUM, {"symbol": "BTCUSDT"})
                self.assertUnavailable(error, f"{server.url}{PREMIUM}?symbol=BTCUSDT", "тіло не розбирається як JSON")
                self.assertEqual(len(server.requests()), 1)

    # Regression: review add-input R1-09 — ESC, BEL, CR/LF і 64 КБ тексту з тіла 400 доходили до причини сирими
    def test_server_text_from_the_body_is_escaped_and_bounded(self):
        """NFR-11, design.md D11: CLI друкує `str(error)` як є, а частину причини пише сервер. Тіло 400 з
        ESC-послідовностями (заголовок вікна, очищення екрана, колір), BEL, NUL, DEL, CR/LF, C1-символом CSI і 64 КБ
        тексту з ESC: у причині немає сирих керівних символів, ESC замінено escape-послідовністю, пояснення біржі
        (`Invalid symbol.`) лишилось, а тіло додало до причини не більше ніж 200 символів."""
        server = self.serve({PREMIUM: Reply(400, HOSTILE_BODY_RAW), FUNDING: Reply(400, b"")})
        bare = self.unavailable(server.url, FUNDING, {}).reason
        error = self.unavailable(server.url, PREMIUM, {"symbol": "NOSUCHSYMBOL"})
        self.assertUnavailable(error, f"{server.url}{PREMIUM}?symbol=NOSUCHSYMBOL", status_pattern(400), "Invalid symbol.")
        self.assertServerTextSafe(error.reason, bare)

    # Regression: review add-input R1-09 — сирий статус-рядок сервера (ESC, CR/LF, 60 000 символів) ставав причиною дослівно
    def test_server_text_from_the_status_line_is_escaped_and_bounded(self):
        """Та сама вимога для статус-рядка: `http.client.BadStatusLine` несе сирий рядок сервера до 64 КБ,
        декодований як ISO-8859-1, разом із CR/LF. Рядок з ESC-послідовностями, BEL, C1-символом CSI і 60 000
        символів тексту з ESC; порівняння — з причиною для статус-рядка `x`."""
        server = self.serve({PREMIUM: Reply(raw=HOSTILE_STATUS_LINE), FUNDING: Reply(raw=b"x\r\n")})
        bare = self.unavailable(server.url, FUNDING, {}).reason
        error = self.unavailable(server.url, PREMIUM, {"symbol": "BTCUSDT"})
        self.assertUnavailable(error, f"{server.url}{PREMIUM}?symbol=BTCUSDT", "not-http")
        self.assertServerTextSafe(error.reason, bare)


class NoRedirectOpener(LiveCase):
    """Шов design.md D7, у який тести підставляють шпигуна: типовий відкривач віддає відповідь як контекстний
    менеджер зі `.status` і `.read()`, а на 3xx кидає `HTTPError`, не роблячи другого запиту."""

    def test_returns_the_response_and_refuses_redirects(self):
        server = self.serve({"/ok": Reply(body=SMALL_RAW), "/moved": Reply(301, headers=(("Location", "/ok"),))})
        with live.no_redirect_open(server.url + "/ok", 2) as response:
            self.assertEqual((response.status, response.read()), (200, SMALL_RAW))
        with self.assertRaises(urllib.error.HTTPError) as caught:
            live.no_redirect_open(server.url + "/moved", 2)
        caught.exception.close()
        self.assertEqual(caught.exception.code, 301)
        self.assertEqual(server.targets(), ["/ok", "/moved"])


class ResponseWithoutObjectKeys(LiveCase):
    """Вимога «Відповідь без ключів об'єкта недоступна» (FR-29): хоч один ключ об'єкта верхнього рівня — саме тіло
    чи елемент тіла-масиву — робить відповідь доступною."""

    def test_body_without_any_object_key_is_unavailable(self):
        """Сценарій «Тіло без жодного ключа об'єкта» і решта JSON-скалярів та масив без об'єктів верхнього рівня."""
        bodies = (b"[]", b"{}", b'[1, "a", null]', b"[{}, {}]", b"42",
                  b'"BTCUSDT"', b"true", b"null", b'[[{"symbol": "BTCUSDT"}]]')
        for raw in bodies:
            with self.subTest(body=raw.decode()):
                server = self.serve({FUNDING: Reply(body=raw)})
                error = self.unavailable(server.url, FUNDING, {"symbol": "NOSUCHSYMBOL", "limit": 3})
                self.assertUnavailable(error, f"{server.url}{FUNDING}?symbol=NOSUCHSYMBOL&limit=3", NO_KEYS)
                self.assertEqual(len(server.requests()), 1)

    def test_one_key_makes_the_response_available(self):
        """Сценарій «Один ключ робить відповідь доступною»: у фікстурі все тіло, зокрема порожній об'єкт."""
        raw = b'[{}, {"symbol": "BTCUSDT"}]'
        server = self.serve({FUNDING: Reply(body=raw)})
        fixture = live.capture(server.url, FUNDING, {"symbol": "BTCUSDT", "limit": 3}, self.runs)
        self.assertEqual(read_json(fixture)["body"], [{}, {"symbol": "BTCUSDT"}])

    def test_object_whose_only_key_is_empty_is_available(self):
        """Межа «хоч один ключ»: порожній рядок — теж ключ."""
        server = self.serve({PREMIUM: Reply(body=b'{"": 1}')})
        fixture = live.capture(server.url, PREMIUM, {}, self.runs)
        self.assertEqual(read_json(fixture)["body"], {"": 1})


class NoFixtureWhenUnavailable(LiveCase):
    """Вимога «Недоступна відповідь не лишає фікстури методу» (FR-28)."""

    def test_no_fixture_before_none_after(self):
        """Сценарій «Без фікстури до методу — без фікстури після»: мережева помилка, 400, `[]` зі статусом 200."""
        refused_error()
        server = self.serve({PREMIUM: Reply(400, INVALID_SYMBOL_RAW), FUNDING: Reply(body=b"[]")})
        cases = (("мережева помилка", "http://127.0.0.1:9", PREMIUM),
                 ("статус 400", server.url, PREMIUM),
                 ("тіло [] зі статусом 200", server.url, FUNDING))
        for label, base, path in cases:
            with self.subTest(label):
                fixture = self.runs / registry.slug_for(path) / "fixture.json"
                self.assertFalse(fixture.exists())
                self.unavailable(base, path, {"symbol": "NOSUCHSYMBOL"})
                self.assertFalse(fixture.exists())
                self.assertEqual(self.written(), [])

    def test_existing_fixture_kept_byte_for_byte(self):
        """Сценарій «Наявна фікстура лишається як була»: мережева помилка, 400, `[]` і перевищений ліміт."""
        refused_error()
        fixture = self.runs / "fapi-v1-premiumIndex" / "fixture.json"
        fixture.parent.mkdir(parents=True)
        fixture.write_bytes(OLD_FIXTURE)
        cases = (("мережева помилка", None, {}),
                 ("статус 400", Reply(400, INVALID_SYMBOL_RAW), {}),
                 ("тіло [] зі статусом 200", Reply(body=b"[]"), {}),
                 ("перевищено ліміт", Reply(silent=True), {"timeout": SHORT}))
        for label, reply, kwargs in cases:
            with self.subTest(label):
                base = "http://127.0.0.1:9" if reply is None else self.serve({PREMIUM: reply}).url
                self.unavailable(base, PREMIUM, {"symbol": "BTCUSDT"}, **kwargs)
                self.assertEqual(fixture.read_bytes(), OLD_FIXTURE)
                self.assertEqual(self.written(), ["fapi-v1-premiumIndex/fixture.json"])

    # Regression: review add-input R1-01, R1-10 — write_text спустошував наявну фікстуру до 0 байтів, перш ніж падало кодування
    def test_lone_surrogate_leaves_the_old_fixture_byte_for_byte(self):
        """Сценарій «Наявна фікстура лишається як була» для тіла, яке не кодується в UTF-8: що б не кинув `capture()`
        (клас винятку — окремий тест), фікстура попереднього прогону байт у байт та сама, і поруч нічого не лишилось."""
        fixture = self.runs / "fapi-v1-premiumIndex" / "fixture.json"
        fixture.parent.mkdir(parents=True)
        for label, raw in SURROGATE_BODIES:
            with self.subTest(label):
                fixture.write_bytes(OLD_FIXTURE)
                outcome = self.outcome(self.serve({PREMIUM: Reply(body=raw)}).url, PREMIUM, {"symbol": "BTCUSDT"})
                kept = fixture.read_bytes()
                self.assertEqual(kept, OLD_FIXTURE, f"фікстура попереднього прогону тепер має {len(kept)} байтів замість "
                                                    f"{len(OLD_FIXTURE)}; capture() дав {outcome!r}")
                self.assertEqual(self.written(), ["fapi-v1-premiumIndex/fixture.json"])


class OnlyThisRunsLiveCall(LiveCase):
    """Вимога «Джерело складу полів і енамів — лише живі виклики цього прогону» (FR-30), частина без раннера й
    брифу: один запит на `path` і рядок запиту з `build_url`, фікстура цього прогону замість старої."""

    def test_one_request_on_the_built_url_and_a_fresh_fixture(self):
        fixture = self.runs / "fapi-v1-premiumIndex" / "fixture.json"
        fixture.parent.mkdir(parents=True)
        fixture.write_bytes(OLD_FIXTURE)
        server = self.serve({PREMIUM: Reply(body=PREMIUM_RAW)})
        spy = Spy()
        args = {"symbol": "BTCUSDT"}
        written = live.capture(server.url, PREMIUM, args, self.runs, open_url=spy)
        url = f"{server.url}/fapi/v1/premiumIndex?symbol=BTCUSDT"
        self.assertEqual(live.build_url(server.url, PREMIUM, args), url)
        self.assertEqual(spy.calls, [url])
        self.assertEqual([(seen.method, seen.target) for seen in server.requests()],
                         [("GET", "/fapi/v1/premiumIndex?symbol=BTCUSDT")])
        self.assertTrue(os.path.samefile(written, fixture))
        self.assertFixture(fixture, PREMIUM, args, PREMIUM_RAW)
        self.assertEqual(self.written(), ["fapi-v1-premiumIndex/fixture.json"])

    def test_the_process_opens_one_connection_per_attempt(self):
        """Хук аудиту в дочірньому процесі: `capture` відкриває рівно одне з'єднання — до сервера за `base_url`, а
        невдала спроба не повторюється (FR-26: без повторної спроби)."""
        refused_error()
        server = self.serve({PREMIUM: Reply(body=PREMIUM_RAW)})
        runs = self.tmp / "child-runs"
        seen = run_child(self, CONNECTIONS_CHILD, "no-file-events", server.url, str(runs))

        def connects(phase):
            return [event[2] for event in seen["events"] if event[0] == phase and event[1] == "socket.connect"]

        self.assertEqual(connects("capture"), [["127.0.0.1", server.port]])
        self.assertEqual(server.targets(), ["/fapi/v1/premiumIndex?symbol=BTCUSDT"])
        self.assertTrue((runs / "fapi-v1-premiumIndex" / "fixture.json").is_file())
        self.assertEqual(seen["refused"], "LiveUnavailable")
        self.assertEqual(connects("refused"), [["127.0.0.1", 9]])


# Regression: review add-input R1-02 — тест справжньої біржі в юніт-наборі ставив npm run test:run і CI у залежність від HTTP-стану біржі
@unittest.skipUnless(os.environ.get("METHOD_SYNC_LIVE") == "1",
                     "справжній виклик fapi.binance.com — лише з METHOD_SYNC_LIVE=1 (npm run test:integration): юніт-набір "
                     "і CI не залежать від стану біржі (обмежені локації — 451, бан за частотою — 418/429, збої — 5xx)")
class LiveExchange(LiveCase):
    """Один справжній виклик біржі (FR-23, FR-24): https-шлях типового відкривача і типового ліміту, фікстура.

    Шар інтеграції, а не юніт (tasks.md 6.9). Хто ввімкнув METHOD_SYNC_LIVE=1, чекає справжнього виклику, тож недосяжна
    біржа тут — провал із поясненням, а не пропуск: пропуск дав би зелений прогін без доказу (урок
    `vacuous-pass-not-earned`).
    """

    def test_premium_index_from_the_live_exchange(self):
        try:
            socket.create_connection(("fapi.binance.com", 443), timeout=5).close()
        except OSError as error:
            self.fail(f"передумова не виконана: fapi.binance.com:443 недосяжний ({error}), а з METHOD_SYNC_LIVE=1 "
                      "справжній виклик обов'язковий")
        args = {"symbol": "BTCUSDT"}
        fixture = live.capture(EXCHANGE, PREMIUM, args, self.runs)
        data = read_json(fixture)
        self.assertEqual(sorted(data), FIXTURE_FIELDS)
        self.assertEqual((data["path"], data["args"], data["http_status"]), (PREMIUM, args, 200))
        self.assertIsInstance(data["body"], dict)
        self.assertEqual(data["body"].get("symbol"), "BTCUSDT")
        captured = datetime.datetime.fromisoformat(data["captured_at"])
        self.assertEqual(captured.utcoffset(), datetime.timedelta(0))
        self.assertGreaterEqual(captured, self.started)
        self.assertEqual(self.written(), ["fapi-v1-premiumIndex/fixture.json"])


class ErrorTypes(unittest.TestCase):
    """Три типізовані винятки слайсу: `add-run-cli` дасть їм коди 2, 3 і 1, тож жоден не підклас іншого."""

    def test_three_distinct_error_types(self):
        kinds = (registry.RegistryError, live.LiveUnavailable, live.FixtureWriteError)
        for kind in kinds:
            self.assertTrue(issubclass(kind, Exception))
            for other in kinds:
                if other is not kind:
                    self.assertFalse(issubclass(kind, other), f"{kind.__name__} — підклас {other.__name__}")


def load_tests(loader, tests, pattern):
    """Передумови оточення — першими (tasks.md 2.12): на їхньому провалі решту червоного читають інакше."""
    first = loader.loadTestsFromTestCase(Preconditions)
    rest = [suite for suite in tests if not any(isinstance(test, Preconditions) for test in suite)]
    return unittest.TestSuite([first, *rest])


if __name__ == "__main__":
    unittest.main()
