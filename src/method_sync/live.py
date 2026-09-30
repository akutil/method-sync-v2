"""Живий виклик біржі і фікстура відповіді (принцип II конституції; FR-23–FR-30, NFR-4).

Склад полів і значення енамів виводяться лише з того, що біржа реально віддала в цьому прогоні (принцип II,
FR-30): приклад із документації — гіпотеза, і джерелом бути не може. Тому на метод — рівно одна спроба GET без
ключів біржі, лише за HTTP чи HTTPS і без перенаправлень (FR-23), не довше 15 с на весь виклик (NFR-4), а
відповідь лягає фікстурою `runs/<slug>/fixture.json` у каталозі інструмента (FR-24, FR-25).

Недоступна відповідь — мережева помилка, адреса, яку відхилив клієнт, відхилена схема, перевищений ліміт, статус
не 200, порожнє тіло, не-JSON чи тіло без жодного ключа об'єкта (FR-26, FR-29) — дає `LiveUnavailable` з URL і
причиною, і прогін зупиняє метод до будь-якої дії з бібліотекою (FR-27, слайс `add-run-cli`). Фікстура пишеться
лише після повного успіху, тож недоступна відповідь власної фікстури не лишає, а фікстура попереднього прогону
лишається байт у байт (FR-28).
"""
import datetime
import http.client
import json
import pathlib
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
# Скільки тіла відповіді зі статусом не 200 іде в причину: там біржа пише пояснення (`Invalid symbol.`).
EXCERPT_CHARS = 200
EXCERPT_BYTES = 4096
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

    `path` — каталог чи файл, на якому відмовила ОС; прогін іде далі до наступного методу (FR-15, `add-run-cli`).
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


def no_redirect_open(url, timeout):
    """Типовий відкривач шва `open_url` (design.md D7): stdlib-клієнт без перенаправлень.

    Віддає відповідь — контекстний менеджер зі `.status` і `.read()`; на статус поза 2xx кидає `HTTPError`.
    """
    return urllib.request.build_opener(_NoRedirect).open(url, timeout=timeout)


def fetch(base_url, path, args, *, open_url=None, timeout=TIMEOUT_SECONDS):
    """Одна спроба живого виклику: `(200, розібране тіло)` або `LiveUnavailable` з URL і причиною.

    Порядок — design.md D9: схема до будь-якого відкриття, далі помилка клієнта чи ліміт, статус, порожнє тіло,
    JSON і ключі об'єкта. Повторної спроби немає (FR-26). `credentials` сюди не доходять: виклик іде без ключів
    біржі (FR-3, FR-23).
    """
    url = build_url(base_url, path, args)
    _require_http(url)
    status, raw = _within_limit(url, no_redirect_open if open_url is None else open_url, timeout)
    if status != 200:
        raise LiveUnavailable(url, _status_reason(status, raw))
    if not raw.strip():
        raise LiveUnavailable(url, "тіло відповіді порожнє")
    try:
        body = json.loads(raw)
    except (ValueError, RecursionError) as error:  # JSONDecodeError, UnicodeDecodeError; надто глибока вкладеність
        raise LiveUnavailable(url, f"тіло не розбирається як JSON: {error}") from error
    if not _has_object_key(body):
        raise LiveUnavailable(url, "на верхньому рівні тіла немає жодного ключа об'єкта, тож нема з чого вивести склад полів")
    return status, body


def capture(base_url, path, args, runs_dir=RUNS_DIR, *, open_url=None, timeout=TIMEOUT_SECONDS):
    """Зняти живу відповідь і записати фікстуру `runs/<slug>/fixture.json` поверх наявної; віддати її шлях.

    Фікстура пишеться лише після повного успіху `fetch`, тож FR-28 виконується за побудовою (design.md D10).
    Запис прямий, як у v1: зірваний запис зупиняє метод `FixtureWriteError`, а FR-28 стосується лише недоступної
    відповіді. `default=str` — бо дату з `args` JSON не представляє (FR-24; v1 падав `TypeError`).
    """
    status, body = fetch(base_url, path, args, open_url=open_url, timeout=timeout)
    captured_at = datetime.datetime.now(datetime.UTC).isoformat(timespec="microseconds")
    text = json.dumps({"path": path, "args": args, "captured_at": captured_at, "http_status": status, "body": body},
                      ensure_ascii=False, indent=2, default=str)
    directory = pathlib.Path(runs_dir) / slug_for(path)
    fixture = directory / "fixture.json"
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise FixtureWriteError(directory, error.strerror or str(error)) from error
    try:
        fixture.write_text(text, encoding="utf-8")
    except OSError as error:
        raise FixtureWriteError(fixture, error.strerror or str(error)) from error
    return fixture


def _require_http(url):
    """FR-23: лише HTTP чи HTTPS, і рішення — до будь-якого відкриття.

    Інакше urllib прочитав би `file://` з диска (FR-92) чи `data:` із самої адреси, і фікстура взялася б не з
    біржі (принцип II). Шлюз стоїть перед швом `open_url`, тож той не кличеться взагалі (design.md D6).
    """
    try:
        scheme = urllib.parse.urlsplit(url).scheme
    except ValueError as error:  # «Invalid IPv6 URL»: адреса не розбирається ще до схеми
        raise LiveUnavailable(url, str(error)) from error
    if scheme not in ALLOWED_SCHEMES:
        what = "схема адреси не дозволена" if scheme else "в адресі немає схеми"
        raise LiveUnavailable(url, f"{what}: живий виклик іде лише за HTTP чи захищеним HTTP, адресу не відкрито")


def _within_limit(url, open_url, timeout):
    """NFR-4: ліміт діє на весь виклик — від початку спроби до кінця читання тіла.

    Тайм-аут сокета, як у v1, діє на одну операцію, тож тіло, яке сервер віддає по байту, тягнулося б скільки
    завгодно. Тому запит і читання йдуть у daemon-потоці, а головний потік чекає не довше `timeout`
    (design.md D8). Сокет отримує той самий `timeout`, тож завислий потік відпадає сам; його пізній результат
    відкидається, і він нічого не пише (FR-28).
    """
    outcome = {}

    def attempt():
        try:
            outcome["response"] = _open_and_read(url, open_url, timeout)
        except BaseException as error:  # з потоку нічого не спливає трасуванням: вердикт виносить головний потік
            outcome["error"] = error

    worker = threading.Thread(target=attempt, name="method-sync live call", daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise LiveUnavailable(url, _limit_reason(timeout))
    error = outcome.get("error")
    if error is None:
        return outcome["response"]
    if isinstance(error, CLIENT_ERRORS):
        raise LiveUnavailable(url, _client_reason(error, timeout)) from error
    raise error  # не вада входу, а дефект інструмента чи шва: хай його буде видно


def _open_and_read(url, open_url, timeout):
    """Одна спроба в потоці виклику: `(статус, сирі байти тіла)`.

    Статус поза 2xx urllib віддає як `HTTPError`; тут він стає таким самим результатом зі статусом і початком
    тіла, бо там біржа пише пояснення (design.md D9).
    """
    try:
        with open_url(url, timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        with error:
            try:
                return error.code, error.read(EXCERPT_BYTES)
            except CLIENT_ERRORS:  # тіло відповіді з помилкою — лише пояснення; статус відомий і без нього
                return error.code, b""


def _status_reason(status, raw):
    """Статус числом і до 200 символів тіла в один рядок (FR-26, design.md D9)."""
    reason = f"статус HTTP {status}, а не 200"
    if 300 <= status < 400:
        reason += " (перенаправлення не виконується)"
    excerpt = " ".join(raw.decode("utf-8", errors="replace").split())
    if len(excerpt) > EXCERPT_CHARS:
        excerpt = excerpt[:EXCERPT_CHARS] + "…"
    if excerpt:
        reason += f"; тіло: {excerpt}"
    return reason


def _limit_reason(timeout):
    return f"перевищено ліміт {f'{timeout:g}'.replace('.', ',')} с"


def _client_reason(error, timeout):
    """Текст помилки мережевого клієнта дослівно (NFR-13); тайм-аут сокета — той самий ліміт NFR-4.

    `URLError` загортає первинну помилку (`gaierror`, відмову в з'єднанні, тайм-аут з'єднання) у `reason`;
    тайм-аут читання приходить голим `TimeoutError`.
    """
    cause = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(cause, TimeoutError):
        return _limit_reason(timeout)
    return str(cause) or type(cause).__name__


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
