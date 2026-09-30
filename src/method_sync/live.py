"""Живий виклик біржі і фікстура відповіді (принцип II конституції; FR-23–FR-30, NFR-4).

Склад полів і значення енамів виводяться лише з того, що біржа реально віддала в цьому прогоні (принцип II,
FR-30): приклад із документації — гіпотеза, і джерелом бути не може. Тому на метод — рівно одна спроба GET без
ключів біржі, лише за HTTP чи HTTPS і без перенаправлень (FR-23), не довше 15 с на весь виклик (NFR-4), а
відповідь лягає фікстурою `runs/<slug>/fixture.json` у каталозі інструмента (FR-24, FR-25).

Недоступна відповідь — мережева помилка, адреса, яку відхилив клієнт, відхилена схема, перевищений ліміт, статус
не 200, тіло понад `MAX_BODY_BYTES`, порожнє тіло, не-JSON, тіло без жодного ключа об'єкта (FR-26, FR-29) чи тіло,
якого фікстура не збереже як є (design.md D10), — дає `LiveUnavailable` з URL і причиною, і прогін зупиняє метод до
будь-якої дії з бібліотекою (FR-27, слайс `add-run-cli`). Фікстура пишеться лише після повного успіху, тож
недоступна відповідь власної фікстури не лишає, а фікстура попереднього прогону лишається байт у байт (FR-28). Пише
вона лише під `runs/` і атомарно (принцип VII, design.md D10).
"""
import contextlib
import datetime
import functools
import http.client
import json
import math
import os
import pathlib
import secrets
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request

from .registry import slug_for

TIMEOUT_SECONDS = 15
# Каталог прогонів виводиться з розташування пакета, а не з робочого каталогу процесу (FR-24): CLI можна
# запускати звідки завгодно, а фікстури лягають у `runs/` інструмента, як у v1.
RUNS_DIR = pathlib.Path(__file__).resolve().parents[2] / "runs"
ALLOWED_SCHEMES = frozenset({"http", "https"})
# Скільки тексту сервера — початку тіла зі статусом не 200 чи статус-рядка — іде в причину: там біржа пише
# пояснення (`Invalid symbol.`), але рядок методу не мусить тонути в кілобайтах (design.md D9).
EXCERPT_CHARS = 200
EXCERPT_BYTES = 4096
# Межа тіла відповіді (design.md D8, D9): читається не більше за `MAX_BODY_BYTES + 1` байтів, а тіло, довше за межу, —
# недоступна відповідь. Тіло REST Binance важить кілобайти, тож 32 МБ у тисячі разів більше за будь-яке, а сервер
# не змусить клієнта ні виділити пам'ять під названий ним `Content-Length`, ні тягнути в неї тіло до вердикту
# ліміту (рецензія R2-06, R2-08).
MAX_BODY_BYTES = 32 * 1024 * 1024
# Помилки клієнта, які означають недоступну відповідь (design.md D9): `OSError` — мережа й тайм-аут, зокрема
# `URLError`; `HTTPException` — адреса, яку відхилив `http.client` (`InvalidURL`), чи обірвана відповідь;
# `ValueError` — адреса, яку не розібрано (`Invalid IPv6 URL`, мітка IDNA довша за 63 символи).
CLIENT_ERRORS = (OSError, http.client.HTTPException, ValueError)


class LiveUnavailable(Exception):
    """Жива відповідь недоступна (FR-26, FR-29): метод зупиняється до перевірки й агента (FR-27).

    `url` — адреса, як її склав інструмент, `reason` — причина. Обидві стоять у повідомленні, бо CLI друкує лише
    `str(error)`, без трасування (NFR-11, design.md D11).
    """

    def __init__(self, url, reason):
        super().__init__(url, reason)
        self.url = url
        self.reason = reason

    def __str__(self):
        return f"жива відповідь недоступна: {self.url} — {self.reason}"


class FixtureWriteError(Exception):
    """Фікстуру не вдалося записати (FR-24): внутрішня помилка методу, а не недоступна відповідь.

    `path` — каталог чи файл, на якому відмовила ОС, або розкритий шлях фікстури поза `runs/` (принцип VII); прогін
    іде далі до наступного методу (FR-15, `add-run-cli`).
    """

    def __init__(self, path, reason):
        super().__init__(path, reason)
        self.path = pathlib.Path(path)
        self.reason = reason

    def __str__(self):
        return f"фікстуру не записано: {self.path} — {self.reason}"


def build_url(base_url, path, args):
    """Адреса живого виклику (FR-23): `base_url` без кінцевої `/` плюс `path`, а для непорожніх `args` — `?` і
    пари в порядку реєстру, закодовані `urllib.parse.urlencode`, як у v1."""
    url = f"{base_url.rstrip('/')}{path}"
    if args:
        url = f"{url}?{urllib.parse.urlencode(args)}"
    return url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Перенаправлення не виконується (FR-23): v1 ішов за `Location` другим запитом на іншу адресу.

    `redirect_request` повертає `None`, тож urllib не робить другого запиту, а віддає 3xx обробнику помилок, і той
    кидає `HTTPError` з цим кодом.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Живий виклик, у потоці якого відкривається з'єднання: так `_Connection` знаходить `_Line` свого виклику.
_CALL = threading.local()


class _Line:
    """З'єднання одного живого виклику, яке головний потік обриває на вердикті ліміту (NFR-4, design.md D8).

    Тайм-аут сокета діє на одну операцію, тож сервер чи проксі, що крапає байти частіше за нього, тримав би після
    вердикту робочий потік, сокет і буфер тіла до кінця прогону. Тому з'єднання типового відкривача, щойно
    встановлено TCP-з'єднання, кладе сюди дублікат свого сокета (`attach`), а головний потік на вердикті робить на
    ньому `shutdown` (`cut`): блоковане читання — відповідь проксі на CONNECT, рукостискання TLS, заголовки чи
    тіло — повертає кінець потоку, і робочий потік завершується. Дублікат закриває лише сам робочий потік
    (`release`), тож `shutdown` не влучить у чужий дескриптор із тим самим номером.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._socket = None
        self._cut = False

    def attach(self, sock):
        """Робочий потік: з'єднання встановлено. Якщо вердикт уже винесено, воно обривається одразу."""
        duplicate = sock.dup()
        with self._lock:
            previous, self._socket = self._socket, duplicate
            if self._cut:
                _hang_up(duplicate)
        if previous is not None:
            previous.close()

    def cut(self):
        """Головний потік, вердикт ліміту: обірвати з'єднання — наявне зараз і те, що встановиться пізніше."""
        with self._lock:
            self._cut = True
            if self._socket is not None:
                _hang_up(self._socket)

    def release(self):
        """Робочий потік, кінець спроби: дублікат сокета більше не потрібен."""
        with self._lock:
            duplicate, self._socket = self._socket, None
        if duplicate is not None:
            duplicate.close()


def _hang_up(sock):
    """`shutdown` в обидва боки: сервер бачить кінець з'єднання, а блоковане читання повертає кінець потоку.
    З'єднання, вже закрите з того боку, — не подія."""
    with contextlib.suppress(OSError):
        sock.shutdown(socket.SHUT_RDWR)


class _Connection(http.client.HTTPConnection):
    """З'єднання типового відкривача: віддає сокет `_Line` свого живого виклику, щойно встановлено TCP-з'єднання,
    — до тунелю проксі й до рукостискання TLS (design.md D8). Поза живим викликом — наприклад, `no_redirect_open`
    у головному потоці — звичайне з'єднання.

    `HTTPConnection.connect` створює сокет через атрибут `_create_connection` (типово `socket.create_connection`) і
    на тому самому сокеті, ще до повернення, веде `_tunnel`: шле проксі CONNECT і читає його відповідь. Тому
    обгортається `_create_connection`, а не `connect`: сокет, зареєстрований після `connect`, не давав вердиктові
    обірвати проксі, що крапає відповідь на CONNECT (рецензія R2-05).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = functools.partial(_connect_on_line, self._create_connection)


def _connect_on_line(create, *args, **kwargs):
    """TCP-з'єднання через `create`, чий сокет одразу йде в `_Line` живого виклику цього потоку, якщо той є.
    Невдалий `attach` (дублікат — теж дескриптор) закриває сокет, а не лишає його збирачеві сміття."""
    sock = create(*args, **kwargs)
    line = getattr(_CALL, "line", None)
    if line is not None:
        try:
            line.attach(sock)
        except BaseException:
            sock.close()
            raise
    return sock


class _SecureConnection(http.client.HTTPSConnection, _Connection):
    """HTTPS: `HTTPSConnection.__init__` через `super()` доходить до `_Connection.__init__`, тож сокет потрапляє в
    `_Line` так само — до тунелю проксі й до рукостискання TLS, і обрив на вердикті уриває вже їх."""


class _HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_Connection, req)


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_SecureConnection, req, context=self._context)


def no_redirect_open(url, timeout):
    """Типовий відкривач шва `open_url` (design.md D7, D8): stdlib-клієнт без перенаправлень, чиє з'єднання
    головний потік може обірвати на вердикті ліміту.

    Віддає відповідь — контекстний менеджер зі `.status` і `.read(amt)`; на статус поза 2xx кидає `HTTPError`.
    """
    return urllib.request.build_opener(_NoRedirect, _HTTPHandler, _HTTPSHandler).open(url, timeout=timeout)


def fetch(base_url, path, args, *, open_url=None, timeout=TIMEOUT_SECONDS):
    """Одна спроба живого виклику: `(200, розібране тіло)` або `LiveUnavailable` з URL і причиною.

    Порядок — design.md D9: схема до будь-якого відкриття, далі помилка клієнта чи ліміт, статус, розмір тіла,
    порожнє тіло, JSON і ключі об'єкта. Повторної спроби немає (FR-26). `credentials` сюди не доходять: виклик іде
    без ключів біржі (FR-3, FR-23).
    """
    url = build_url(base_url, path, args)
    _require_http(url)
    status, raw = _within_limit(url, no_redirect_open if open_url is None else open_url, timeout)
    if status != 200:
        raise LiveUnavailable(url, _status_reason(status, raw))
    if len(raw) > MAX_BODY_BYTES:  # `_open_and_read` читає на байт понад межу саме для цієї перевірки
        raise LiveUnavailable(url, _size_reason(MAX_BODY_BYTES))
    if not raw.strip():
        raise LiveUnavailable(url, "тіло відповіді порожнє")
    # ValueError — JSONDecodeError, UnicodeDecodeError, NaN чи 1e999 (D9); RecursionError — надто глибока вкладеність.
    try:
        body = json.loads(raw, parse_constant=_not_json, parse_float=_finite)
    except (ValueError, RecursionError) as error:
        raise LiveUnavailable(url, f"тіло не розбирається як JSON: {error}") from error
    if not _has_object_key(body):
        raise LiveUnavailable(url, "на верхньому рівні тіла немає жодного ключа об'єкта, тож нема з чого вивести склад полів")
    return status, body


def capture(base_url, path, args, runs_dir=RUNS_DIR, *, open_url=None, timeout=TIMEOUT_SECONDS):
    """Зняти живу відповідь і записати фікстуру `runs/<slug>/fixture.json` поверх наявної; віддати її шлях.

    Порядок — design.md D10. Фікстура пишеться лише після повного успіху `fetch`, тож FR-28 виконується за
    побудовою. Вона серіалізується й кодується в UTF-8 до будь-якої дії з диском, каталог запису звіряється з
    `runs_dir` після розкриття `..` і символьних посилань (принцип VII), а запис атомарний: збій не лишає ні
    обрізаної фікстури, ні порожньої на місці попередньої. `args`, яких JSON не представляє, — рядком (FR-24): дата
    — через `default=str` (v1 падав `TypeError`), `nan` і `inf` — через `_json_value`, бо `default` на float не
    кличеться.
    """
    status, body = fetch(base_url, path, args, open_url=open_url, timeout=timeout)
    captured_at = datetime.datetime.now(datetime.UTC).isoformat(timespec="microseconds")
    record = {"path": path, "args": _json_value(args), "captured_at": captured_at, "http_status": status, "body": body}
    try:
        text = json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False, default=str)
    except (RecursionError, ValueError) as error:
        # RecursionError: серіалізація бере на рівень вкладеності більше C-стека, ніж розбір у `fetch`, тож тіло,
        # яке той прийняв, може не серіалізуватись (рецензія R2-02). ValueError — сітка `allow_nan=False` (D10).
        what = ("тіло надто глибоко вкладене, щоб записати фікстуру" if isinstance(error, RecursionError)
                else "фікстура не серіалізується в JSON")
        raise LiveUnavailable(build_url(base_url, path, args), f"{what}: {error}") from error
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError as error:
        # `path` і `args` із реєстру непарного сурогата не несуть (файл реєстру читається як UTF-8, а `tomllib` не
        # приймає `\ud800`), тож винуватець — тіло: `json.loads` приймає і escape `\ud800`, і сирі байти ED A0 80.
        raise LiveUnavailable(build_url(base_url, path, args),
                              f"тіло містить непарний сурогат U+{ord(error.object[error.start]):04X}, який не "
                              "кодується в UTF-8, тож фікстура не збереже тіло як є") from error
    directory = pathlib.Path(runs_dir) / slug_for(path)
    fixture = directory / "fixture.json"
    _require_inside(fixture, runs_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise FixtureWriteError(directory, error.strerror or str(error)) from error
    _write_atomically(fixture, data)
    return fixture


def _not_json(token):
    """`json.loads` за замовчуванням приймає `NaN`, `Infinity` і `-Infinity`, а RFC 8259 їх не знає (FR-26):
    фікстуру з ними строгий розбирач не прочитав би."""
    raise ValueError(f"{token} не є значенням JSON (RFC 8259)")


def _finite(literal):
    """Дробове число тіла — `float`, але не безмежність: `1e999` — число за RFC 8259, проте `float` його не вміщає
    і дає `inf`, який фікстура записала б недійсним `Infinity`. RFC 8259, розділ 6, дозволяє так обмежити
    діапазон чисел."""
    value = float(literal)
    if math.isinf(value):
        raise ValueError(f"число {_server_text(literal)} поза діапазоном float (RFC 8259, розділ 6)")
    return value


def _json_value(value):
    """Значення `args` для фікстури (FR-24): `nan`, `inf` і `-inf` із TOML — рядком `str(value)`, як їх пише в
    рядок запиту `urlencode`, бо JSON за RFC 8259 їх не представляє; вкладені масиви й таблиці — так само."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _require_inside(fixture, runs_dir):
    """Принцип VII: інструмент пише лише у власний `runs/` (FR-91, capability `run-cli`), тож каталог, у якому
    справді йде запис, звіряється з `runs_dir` після розкриття `..` і символьних посилань.

    Звіряється каталог `fixture.parent`, а не розкритий `fixture.json`: `open(…, "xb")` і `os.replace` у
    `_write_atomically` за останнім компонентом не йдуть, тож байти лягають у розкритий каталог, хай куди веде
    посилання на місці `fixture.json` (рецензія R2-01, R2-10). v1 (`boundaries.assert_writable`) розкривав увесь
    шлях, бо писав `write_text` крізь посилання. Каталог мусить бути самим `runs_dir` — slug `""` чи `.` (D10) — або
    лежати під ним. Slug `..` чи каталог `runs/<slug>` — посилання назовні — дають `FixtureWriteError` з
    `<розкритий каталог>/fixture.json`, і нічого не створено. Розкритий шлях потрібен лише для цієї перевірки:
    каталог і файл далі створюються за шляхом, як його склав інструмент, і так їх називають решта
    `FixtureWriteError`.
    """
    try:
        where, root = fixture.parent.resolve(), pathlib.Path(runs_dir).resolve()
    except (OSError, ValueError) as error:  # getcwd() для відносного runs_dir; нуль-байт у шляху
        raise FixtureWriteError(fixture, f"шлях не розкривається: {error}") from error
    if not where.is_relative_to(root):
        raise FixtureWriteError(where / fixture.name,
                                f"каталог {fixture.parent} після розкриття «..» і символьних посилань лежить поза "
                                f"каталогом прогонів {root}; запис не виконано (принцип VII)")


def _write_atomically(fixture, data):
    """Запис, який жоден збій не обриває посеред наявної фікстури (design.md D10), як `_write_atomic` в
    `importlib`: тимчасовий файл у тому ж каталозі, потім `os.replace`.

    `open(…, "xb")` створює лише новий файл із правами за umask. Помилка ОС на будь-якому кроці — немає місця,
    ліміт розміру файлу, каталог на місці `fixture.json` — прибирає тимчасовий файл і дає `FixtureWriteError` зі
    шляхом фікстури, а фікстура попереднього прогону лишається байт у байт. `os.replace` підміняє сам запис
    каталогу, тож і символьне посилання на місці `fixture.json` наскрізь не проходиться, а стає звичайним файлом у
    цьому каталозі; тому `_require_inside` звіряє каталог, а не розкритий `fixture.json`.
    """
    temporary = fixture.with_name(f".{fixture.name}.{secrets.token_hex(8)}.tmp")
    try:
        handle = open(temporary, "xb")
    except OSError as error:
        raise FixtureWriteError(fixture, error.strerror or str(error)) from error
    try:
        with handle:
            handle.write(data)
        os.replace(temporary, fixture)
    except OSError as error:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise FixtureWriteError(fixture, error.strerror or str(error)) from error


def _require_http(url):
    """FR-23: лише HTTP чи HTTPS, і рішення — до будь-якого відкриття.

    Інакше urllib прочитав би `file://` з диска (FR-92) чи `data:` із самої адреси, і фікстура взялася б не з
    біржі (принцип II). Шлюз стоїть перед швом `open_url`, тож той не кличеться взагалі (design.md D6).
    """
    try:
        scheme = urllib.parse.urlsplit(url).scheme
    except ValueError as error:  # «Invalid IPv6 URL»: адреса не розбирається ще до схеми
        raise LiveUnavailable(url, _server_text(str(error))) from error  # причина від клієнта — як у _client_reason
    if scheme not in ALLOWED_SCHEMES:
        what = "схема адреси не дозволена" if scheme else "в адресі немає схеми"
        raise LiveUnavailable(url, f"{what}: живий виклик іде лише за HTTP чи захищеним HTTP, адресу не відкрито")


def _within_limit(url, open_url, timeout):
    """NFR-4: ліміт діє на весь виклик — від початку спроби до кінця читання тіла.

    Тайм-аут сокета, як у v1, діє на одну операцію, тож тіло, яке сервер віддає по байту, тягнулося б скільки
    завгодно. Тому запит і читання йдуть у daemon-потоці, а головний потік чекає не довше `timeout`
    (design.md D8). На вердикті він обриває з'єднання (`_Line.cut`): блоковане читання в робочому потоці
    повертає кінець потоку, і той завершується, а не дочитує тіло чи відповідь проксі на CONNECT, які сервер чи
    проксі крапає й далі. До TCP-з'єднання (резолв імені, `connect`) обривати ще нічого — там потік живе до
    тайм-ауту сокета чи резолвера. Пізній результат потоку відкидається, і він нічого не пише (FR-28).
    """
    outcome, line = {}, _Line()

    def attempt():
        _CALL.line = line
        try:
            outcome["response"] = _open_and_read(url, open_url, timeout)
        except BaseException as error:  # з потоку нічого не спливає трасуванням: вердикт виносить головний потік
            outcome["error"] = error
        finally:
            line.release()

    worker = threading.Thread(target=attempt, name="method-sync live call", daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        line.cut()
        raise LiveUnavailable(url, _limit_reason(timeout))
    error = outcome.get("error")
    if error is None:
        return outcome["response"]
    if isinstance(error, CLIENT_ERRORS):
        raise LiveUnavailable(url, _client_reason(error, timeout)) from error
    raise error  # не вада входу, а дефект інструмента чи шва: хай його буде видно


def _open_and_read(url, open_url, timeout):
    """Одна спроба в потоці виклику: `(статус, сирі байти тіла)`.

    Тіло читається не більше за `MAX_BODY_BYTES + 1` байтів (design.md D8): зайвий байт каже `fetch`, що тіло довше
    за межу. `read()` без межі виділяв би пам'ять під `Content-Length` чи розмір фрагмента, які назвав сервер, —
    сирий `OverflowError` чи `MemoryError` (рецензія R2-06), — і тягнув би в пам'ять усе, що сервер устигне віддати
    до вердикту ліміту (R2-08). Але `read(amt)`, на відміну від `read()`, мовчить, коли з'єднання закрилось раніше,
    ніж надійшов увесь `Content-Length`, тож `IncompleteRead`, як `_safe_read` у `http.client`, кидає сама функція:
    обірвана відповідь лишається недоступною (D9), хоч би її початок і розбирався як JSON. Статус поза 2xx urllib
    віддає як `HTTPError`; тут він стає таким самим результатом зі статусом і початком тіла, бо там біржа пише
    пояснення (design.md D9).
    """
    try:
        with open_url(url, timeout) as response:
            raw = response.read(MAX_BODY_BYTES + 1)
            owed = getattr(response, "length", None)  # http.client: скільки байтів Content-Length ще не надійшло
            if owed and len(raw) <= MAX_BODY_BYTES:
                raise http.client.IncompleteRead(raw, owed)
            return response.status, raw
    except urllib.error.HTTPError as error:
        with error:
            try:
                return error.code, error.read(EXCERPT_BYTES)
            except CLIENT_ERRORS:  # тіло відповіді з помилкою — лише пояснення; статус відомий і без нього
                return error.code, b""


def _status_reason(status, raw):
    """Статус числом і початок тіла (FR-26, NFR-11, design.md D9): там біржа пише пояснення, яке називає
    винуватця (`Invalid symbol.`). Тіло пише сервер, тож воно йде крізь `_server_text`."""
    reason = f"статус HTTP {status}, а не 200"
    if 300 <= status < 400:
        reason += " (перенаправлення не виконується)"
    excerpt = _server_text(raw.decode("utf-8", errors="replace"))
    if excerpt:
        reason += f"; тіло: {excerpt}"
    return reason


def _server_text(text):
    """Текст сервера для причини (NFR-11, design.md D9, D11): CLI друкує `str(error)` як є, тож цей текст не
    мусить ні керувати терміналом (ESC, BEL, C1-символ CSI), ні рвати рядок методу (CR/LF), ні топити його в
    кілобайтах.

    Пробіли згортаються в один; недруковані символи — C0, DEL, C1, форматні — стають escape-послідовністю
    Python (`ascii()`: `\\x1b`, `\\u202e`). Обрізання до `EXCERPT_CHARS` символів із «…» іде після заміни, тож і
    текст із самих ESC не виходить за межу.
    """
    kept, size = [], 0
    for char in " ".join(text.split()):
        piece = char if char.isprintable() else ascii(char)[1:-1]
        if size + len(piece) > EXCERPT_CHARS:
            return "".join(kept) + "…"
        kept.append(piece)
        size += len(piece)
    return "".join(kept)


def _limit_reason(timeout):
    return f"перевищено ліміт {f'{timeout:g}'.replace('.', ',')} с"


def _size_reason(limit):
    """«тіло більше за 32 МБ»: число виводиться з самої межі в мебібайтах, як її задано (`32 * 1024 * 1024`)."""
    return f"тіло більше за {f'{limit / (1024 * 1024):g}'.replace('.', ',')} МБ"


def _client_reason(error, timeout):
    """Текст помилки мережевого клієнта (NFR-13) крізь `_server_text`; тайм-аут сокета — той самий ліміт NFR-4.

    `URLError` загортає первинну помилку (`gaierror`, відмову в з'єднанні, тайм-аут з'єднання, відмову проксі на
    CONNECT) у `reason`; тайм-аут читання приходить голим `TimeoutError`. Текст сервера може нести не лише
    `HTTPException` — `BadStatusLine` кладе в себе сирий статус-рядок до 64 КБ разом із CR/LF, — а й `OSError`:
    `http.client` пише в «Tunnel connection failed: …» фразу, якою проксі відмовив на CONNECT (рецензія R2-04). Тому
    крізь `_server_text` іде кожна причина від клієнта; друкований текст до 200 символів з одиничними пробілами — як
    сталі тексти ОС, TLS і резолвера — він лишає як є.
    """
    cause = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(cause, TimeoutError):
        return _limit_reason(timeout)
    return _server_text(str(cause)) or type(cause).__name__


def _has_object_key(body):
    """FR-29: хоч один ключ об'єкта верхнього рівня — у самому тілі чи в елементі тіла-масиву.

    З тіла без жодного ключа нема з чого вивести склад полів, а симетрія полів (принцип VIII) інакше прибрала б
    усі поля моделі. Об'єднання ключів тут не рахується — це FR-38 у перевірці.
    """
    if isinstance(body, dict):
        return bool(body)
    if isinstance(body, list):
        return any(isinstance(item, dict) and item for item in body)
    return False
