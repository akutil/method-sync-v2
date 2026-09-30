"""Реєстр методів — вхід прогону, який людина веде руками (FR-1–FR-10).

Формат — TOML, читається stdlib-модулем `tomllib` (FR-1, NFR-14): реєстр method-sync v1 приймається без змін,
а YAML означав би залежність або власний парсер там, де стандартна бібліотека вже має готовий формат.

Реєстр перевіряється цілком до першого методу, і перша ж вада зупиняє весь прогін (FR-2, FR-4–FR-10): мовчки
проковтнута опечатка в назві поля коштує дорожче за зупинку з поясненням. Тому невідоме поле — вада, тип поля
перевіряється раніше за його наявність, а повідомлення називає поле і місце так, щоб людина знайшла рядок у
файлі (NFR-11). Назовні виходить лише `RegistryError`: будь-який інший клас винятку CLI показав би трасуванням
стеку (design.md D5).

Перевіряється лише те, що називають FR-2 і FR-4–FR-10. Решту значень — `status`, `credentials`, значення
всередині `args` — реєстр, як v1, передає прогону такими, як їх дав `tomllib` (FR-3).
"""
import datetime
import os
import pathlib
import stat
import tomllib
from dataclasses import dataclass, field

TOP_LEVEL = "верхнього рівня"
LIVE_SECTION = "у секції [live]"

# Відомі поля кожного рівня в порядку формату (FR-4). Ключі всередині `args` полями реєстру не є.
TOP_LEVEL_KEYS = ("lib", "verify_cmd", "status", "credentials", "live", "method")
LIVE_KEYS = ("base_url",)
METHOD_KEYS = ("path", "model", "client_method", "args", "call")

# Очікуваний тип TOML (FR-4, FR-9, design.md D3). `status` і `credentials` сюди навмисно не входять: FR-3
# приймає їх із будь-яким значенням, як v1.
TOP_LEVEL_TYPES = {"lib": str, "verify_cmd": str, "live": dict, "method": list}
LIVE_TYPES = {"base_url": str}
METHOD_TYPES = {"path": str, "model": str, "client_method": str, "args": dict, "call": str}

TOP_LEVEL_REQUIRED = ("lib", "verify_cmd")
LIVE_REQUIRED = ("base_url",)
METHOD_REQUIRED = ("path", "model", "client_method")

# Типи TOML словами, в орудному відмінку: «має бути рядком, а не цілим числом». Порядок важливий: у Python
# `bool` — підклас `int`, а `datetime` — підклас `date`, тож вужчий тип стоїть першим.
_KINDS = (
    (bool, "булевим значенням"),
    (int, "цілим числом"),
    (float, "дробовим числом"),
    (str, "рядком"),
    (datetime.datetime, "датою й часом"),
    (datetime.date, "датою"),
    (datetime.time, "часом"),
    (list, "масивом"),
    (dict, "таблицею"),
)
_KIND_OF_TYPE = dict(_KINDS)


class RegistryError(Exception):
    """Реєстр непридатний (FR-2, FR-4–FR-10): прогін зупиняється до першого методу.

    Повідомлення самодостатнє — поле і місце, шлях файлу реєстру чи шлях `lib` (NFR-11), — бо CLI друкує лише
    `str(error)`, а первинна помилка лишається в `__cause__` (design.md D11).
    """


def slug_for(path):
    """Шлях ендпоінта → ім'я каталогу методу в `runs/` (FR-25): `/fapi/v1/premiumIndex` → `fapi-v1-premiumIndex`.

    Крайні `/` відкидаються, решта стають `-`, а інші символи і регістр лишаються як є. Функція живе тут, бо
    slug від `Method` беруть і фікстура, і звіт, і цикл (design.md D1).
    """
    return path.strip("/").replace("/", "-")


@dataclass(frozen=True)
class Method:
    """Один уже реалізований метод біржі зі списку (FR-8): що викликати і з чим.

    `frozen` лише забороняє переприсвоювати поля; `args` — звичайний `dict`, як у v1, тож вміст від змін
    береже домовленість, а не тип, і `Method` не хешується (design.md D1). `args` — таблиця `tomllib` у порядку
    запису (FR-9), `call` — рядок Java дослівно, зокрема `""` (FR-8).
    """

    path: str
    model: str
    client_method: str
    args: dict = field(default_factory=dict)
    call: str | None = None

    @property
    def slug(self):
        return slug_for(self.path)


@dataclass(frozen=True)
class Registry:
    """Прочитаний і перевірений реєстр: бібліотека, її єдина команда перевірки, біржа і методи.

    `verify_cmd` обов'язковий, бо кожна бібліотека має рівно одну команду перевірки (принцип IV). `lib` — шлях як
    записано, лише з розгорнутим `~` (FR-6); `status` і `credentials` — будь-яке значення TOML (FR-3).
    """

    lib: pathlib.Path
    verify_cmd: str
    base_url: str
    status: object
    credentials: object | None
    methods: list[Method]


def _kind(value):
    for kind, name in _KINDS:
        if isinstance(value, kind):
            return name
    return type(value).__name__


def _check_table(table, keys, types, required, where):
    """Одна таблиця реєстру в порядку design.md D2: невідомі поля → типи → обов'язкові й непорожні.

    Тип іде раніше за «бракує», тож на `lib = 5` людина чує «має бути рядком», а не загадкове «бракує lib».
    """
    unknown = [key for key in table if key not in keys]
    if unknown:
        noun = "невідоме поле" if len(unknown) == 1 else "невідомі поля"
        raise RegistryError(f"{noun} {where}: {', '.join(unknown)} (відомі: {', '.join(keys)})")
    for key, value in table.items():
        expected = types.get(key)
        if expected is not None and not isinstance(value, expected):
            raise RegistryError(f"поле {key} {where} має бути {_KIND_OF_TYPE[expected]}, а не {_kind(value)}")
    for key in required:
        if key not in table:
            raise RegistryError(f"бракує обов'язкового поля {key} {where}")
        if table[key] == "":
            raise RegistryError(f"обов'язкове поле {key} {where} порожнє")


def _parse(source, shown):
    """FR-5: файл є і розбирається як TOML; інакше — шлях файлу і текст первинної помилки (design.md D5)."""
    try:
        text = source.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise RegistryError(f"реєстру немає: {shown}") from error
    except UnicodeDecodeError as error:
        raise RegistryError(f"реєстр {shown} не в кодуванні UTF-8: {error}") from error
    except (OSError, ValueError) as error:  # каталог замість файлу, немає прав, нуль-байт у шляху
        raise RegistryError(f"реєстр {shown} не читається: {getattr(error, 'strerror', None) or error}") from error
    try:
        return tomllib.loads(text)
    except ValueError as error:  # TOMLDecodeError; голий ValueError з int() — ціле понад 4300 цифр (R1-05)
        raise RegistryError(f"реєстр {shown} не розбирається як TOML: {error}") from error
    except RecursionError as error:  # tomllib розбирає вкладені масиви й таблиці рекурсивно
        raise RegistryError(f"реєстр {shown} не розбирається як TOML: надто глибока вкладеність ({error})") from error


def _library(value):
    """FR-6: `lib` — наявний каталог із `.git`, бо результат прогону — правка в робочій копії, яку людина
    переглядає й мерджить сама (принцип VI).

    Як у v1, `~` розгортається, а відносний шлях перевіряється від поточного каталогу процесу, не від каталогу
    файлу реєстру; назад віддається шлях як записано, без резолву.
    """
    try:
        lib = pathlib.Path(value).expanduser()
    except (RuntimeError, ValueError) as error:  # `~` неіснуючого користувача; нуль-байт в імені користувача
        raise RegistryError(f"не вдалося розгорнути ~ у шляху lib {value}: {error}") from error
    if value.startswith("~"):
        named = f"{value} ({lib})"
    elif not lib.is_absolute():
        named = f"{value} (відносно поточного каталогу процесу)"
    else:
        named = value
    mode = _stat_mode(lib, "цільової бібліотеки lib", named)
    if mode is None:
        raise RegistryError(f"цільової бібліотеки lib немає: {named}")
    if not stat.S_ISDIR(mode):
        raise RegistryError(f"цільова бібліотека lib — не каталог: {named}")
    if _stat_mode(lib / ".git", ".git цільової бібліотеки lib", named) is None:
        raise RegistryError(f"цільова бібліотека lib не є git-репозиторієм (немає .git): {named}")
    return lib


def _stat_mode(path, what, named):
    """`st_mode` шляху або `None`, якщо його немає; іншу відмову ОС названо, а не звернено на «немає» (NFR-11).

    `Path.exists()` у Python 3.14 віддає False на будь-яку помилку ОС, тож каталог, у який процес не може увійти,
    звучав би як відсутній, і людина шукала б не ту ваду. `what` — що перевіряється, у родовому відмінку.
    """
    try:
        return os.stat(path).st_mode
    except (FileNotFoundError, NotADirectoryError):
        return None
    except PermissionError as error:
        raise RegistryError(f"немає доступу до {what}: {named} — {error.strerror}") from error
    except (OSError, ValueError) as error:  # задовге ім'я, петля символьних посилань, нуль-байт у шляху
        reason = getattr(error, "strerror", None) or error
        raise RegistryError(f"шлях {what} не перевірено: {named} — {reason}") from error


def _method(entry, number):
    """Запис `[[method]]` у порядку design.md D2: тип елемента → коротка форма → невідомі → типи → обов'язкові.

    Запис називається номером `#N` (лік із 1) і своїм `path`, а без придатного `path` — лише номером (NFR-11).
    """
    if not isinstance(entry, (dict, str)):
        raise RegistryError(f"запис методу #{number} має бути таблицею або рядком, а не {_kind(entry)}")
    if isinstance(entry, str):
        # FR-10: коротка форма синтаксично приймається, але вивести з неї model і client_method нема з чого —
        # це FR-11, поза обсягом MVP.
        raise RegistryError(
            f"запис методу #{number} ({entry}) — коротка форма: без model і client_method працювати нема з чим; "
            "запишіть метод таблицею [[method]] з полями path, model і client_method"
        )
    path = entry.get("path")
    where = f"у записі методу #{number}" + (f" ({path})" if isinstance(path, str) and path else "")
    _check_table(entry, METHOD_KEYS, METHOD_TYPES, METHOD_REQUIRED, where)
    return Method(path=entry["path"], model=entry["model"], client_method=entry["client_method"],
                  args=entry.get("args", {}), call=entry.get("call"))


def load(path):
    """Прочитати реєстр і віддати перевірений `Registry` або кинути `RegistryError` з винуватцем.

    Порядок — design.md D2: файл → TOML → верхній рівень → `lib` → `[live]` → `method` → кожен запис по черзі.
    Вада будь-якого запису відхиляє весь реєстр, тож прогін не отримує жодного методу (FR-2, FR-4–FR-10).
    """
    shown = os.fspath(path)
    raw = _parse(pathlib.Path(path), shown)
    _check_table(raw, TOP_LEVEL_KEYS, TOP_LEVEL_TYPES, TOP_LEVEL_REQUIRED, TOP_LEVEL)
    lib = _library(raw["lib"])
    live = raw.get("live", {})
    _check_table(live, LIVE_KEYS, LIVE_TYPES, LIVE_REQUIRED, LIVE_SECTION)
    entries = raw.get("method", [])
    if not entries:
        raise RegistryError("у реєстрі немає жодного методу — прогону нема з чим працювати")
    methods = [_method(entry, number) for number, entry in enumerate(entries, 1)]
    return Registry(
        lib=lib,
        verify_cmd=raw["verify_cmd"],
        base_url=live["base_url"],
        status=raw.get("status", "active"),
        credentials=raw.get("credentials"),
        methods=methods,
    )
