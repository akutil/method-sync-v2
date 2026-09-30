"""Навігація по цільовій бібліотеці: модуль зі шляху, стандарт стилю, файл моделі, файл еталона.

Принцип I конституції: кожна правка мірорить найближчий існуючий ендпоінт — ті самі файли, той самий порядок, ті самі
імена. Письмовий стандарт стилю бібліотеки є обов'язковим входом прогону: якщо його немає, метод зупиняється, а не
імпровізує (FR-22). Режиму реалізації з нуля в v2 немає (FR-94): метод без класу моделі до циклу не доходить (FR-20),
тож функцій v1 для нього (`style_skill`, `service_file`, `is_implemented`) тут немає.
"""
import pathlib

STYLE_STANDARD = ".claude/skills/add-binance-rest-endpoint/SKILL.md"

# Шлях ендпоінта мапиться в продуктовий модуль напряму — так само, як це описує стандарт стилю (FR-21).
MODULE_BY_PREFIX = {
    "/fapi/": "binanceFutures",
    "/dapi/": "binanceDelivery",
    "/sapi/": "binanceMargin",
    "/papi/": "portfolioMargin",
    "/api/": "binanceSpot",
}


class StyleStandardMissing(Exception):
    """У бібліотеки немає письмового стандарту стилю — метод зупиняється (FR-22)."""


def module_for(path):
    """Шлях ендпоінта → продуктовий модуль цільової бібліотеки (FR-21); інший префікс — `ValueError`."""
    for prefix, module in MODULE_BY_PREFIX.items():
        if path.startswith(prefix):
            return module
    raise ValueError(f"невідомий префікс шляху {path}: модуль бібліотеки виводиться лише з "
                     f"{', '.join(MODULE_BY_PREFIX)}")


def style_standard(lib):
    """Шлях письмового стандарту стилю бібліотеки або `StyleStandardMissing` з очікуваним шляхом (FR-22).

    Вміст не читається: режиму реалізації з нуля, якому v1 передавав стандарт, у v2 немає, а бриф актуалізації
    велить мірорити еталон (FR-72). Стандарт тут — гейт наявності, як у v1.
    """
    standard = pathlib.Path(lib) / STYLE_STANDARD
    if not standard.is_file():
        raise StyleStandardMissing(
            f"немає письмового стандарту стилю {standard} — метод зупинено, інструмент не вводить власних шаблонів "
            "коду (принцип I)")
    return standard


def _source_root(lib):
    return pathlib.Path(lib) / "src" / "main" / "java"


def model_file(lib, model_fqn):
    """Файл класу моделі за повним ім'ям (FR-20), або None, якщо його в бібліотеці немає."""
    candidate = _source_root(lib) / (model_fqn.replace(".", "/") + ".java")
    return candidate if candidate.is_file() else None


def reference_model(lib, module):
    """Найближчий уже реалізований файл модуля — еталон, який агент мірорить (принцип I, FR-72).

    Еталон — найпростіша self-contained модель: перший за іменем, за кодовими точками Unicode, `*.java` у
    `response/`, без успадкування і без класів зовнішнього артефакту. Шлях — від `lib`, як його передали: CLI дає
    абсолютний.
    """
    responses = _source_root(lib) / "com" / "example" / module / "response"
    if not responses.is_dir():
        return None
    for candidate in sorted(responses.glob("*.java"), key=lambda path: path.name):
        text = candidate.read_text(encoding="utf-8", errors="replace")
        if " extends " not in text and "import com.binance" not in text:
            return candidate
    return None
