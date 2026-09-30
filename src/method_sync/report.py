"""Звіт прогону `runs/<slug>/report.md` (FR-77–FR-84, NFR-12).

Правку інструмент лишає некомічену, і що з нею робити — вирішує людина (принцип VI). Рішення вона ухвалює з цього
файлу, тож звіт пишеться для кожного методу, що дійшов до перевірки: і коли перевірка зелена, і коли цикл не зійшовся,
і на `--dry-run` (FR-77). Методу, зупиненому до перевірки, звіту немає, і попередній лишається байт у байт.

Окремо про видалення: воно не мовчазне. Модель, яка накопичує поля, яких біржа вже не віддає, бреше не менше за
модель, якій полів бракує, — але видалення ламає споживачів, тож кожне назване тут поіменно (FR-81). Константи енамів
навпаки не видаляються зовсім: невидимі лише названо з позначкою «не видалено» (FR-57, принцип IX).

Відмінності від v1: дванадцять полів (`enum_mismatch`, `enum_unseen`), описи всіх шести стадій, ліміт `verify_cmd` у
`mismatch`; неповний звіт не створює і не змінює `report.md`.
"""
import pathlib

from .boundaries import assert_writable
from .verify import COMPILE_LIMIT_LABEL, STAGE_LABEL, seconds

REPORT_FIELDS = (
    "mode",
    "request_source",
    "response_source",
    "mismatch",
    "removed",
    "verify_cmd",
    "verify_result",
    "iterations",
    "reviewer",
    "left_to_human",
    "enum_mismatch",
    "enum_unseen",
)

LABELS = {
    "mode": "Режим",
    "request_source": "Джерело параметрів запиту",
    "response_source": "Джерело моделі відповіді",
    "mismatch": "Розходження до правки",
    "removed": "Видалені поля",
    "verify_cmd": "Команда перевірки",
    "verify_result": "Результат перевірки",
    "iterations": "Ітерацій циклу",
    "reviewer": "Висновок рецензента",
    "left_to_human": "Лишилось на людину",
    "enum_mismatch": "Значення енамів, яких бракувало (до правки)",
    "enum_unseen": "Оголошені константи, яких не було в живій відповіді (не видалено)",
}

NO_COMPARISON = "звіряння не відбулося"
CLOSING = (
    "Правка лишена некомічена в робочій копії цільової бібліотеки. Рішення про історію",
    "репозиторію належить людині (принцип VI конституції).",
)


def _names(values):
    return ", ".join(values) if values else "—"


def _stage(verdict, verify_cmd):
    """FR-80: стадія першої перевірки словами, а не тире; ліміт `verify_cmd` — окремим описом."""
    stage = verdict["stage"]
    if stage == "compile" and verdict.get("limit_s") is not None:
        text = COMPILE_LIMIT_LABEL.format(limit=seconds(verdict["limit_s"]), verify_cmd=verify_cmd)
    elif stage in STAGE_LABEL:
        text = STAGE_LABEL[stage].format(verify_cmd=verify_cmd)
    else:
        text = stage
    return f"{NO_COMPARISON}: {text}"


def _enum_groups(verdict, key, suffix, empty):
    """FR-56, FR-57: групи записів `enums` із непорожнім `key` через «; », інакше — `empty`."""
    if verdict.get("stage"):
        return NO_COMPARISON
    groups = [f"{entry['field']} ({entry['enum']}): {', '.join(entry[key])}{suffix}"
              for entry in verdict.get("enums") or [] if entry.get(key)]
    return "; ".join(groups) or empty


def _render(field, value, fields):
    if field == "mismatch":
        if value.get("stage"):
            return _stage(value, fields["verify_cmd"])
        return f"зайві в моделі: {_names(value.get('extra'))}; бракує в моделі: {_names(value.get('missing'))}"
    if field == "removed":
        return ", ".join(value) if value else "нічого не видалено"
    if field == "left_to_human":
        return "; ".join(value) if value else "—"
    if field == "enum_mismatch":
        return _enum_groups(value, "missing", "", "розходжень енамів немає")
    if field == "enum_unseen":
        return _enum_groups(value, "unseen", " — не видалено", "невидимих констант немає")
    return str(value)


def write_report(runs_dir, slug, **fields):
    """Скласти звіт прогону і покласти його поряд із фікстурою; повернути шлях.

    Бракує поля — `ValueError` до будь-якої дії з диском, тож попередній звіт лишається байт у байт (FR-78). Шлях
    звіту звіряється з `runs_dir` після розкриття символьних посилань (FR-91).
    """
    missing = [name for name in REPORT_FIELDS if name not in fields]
    if missing:
        raise ValueError(f"звіт не записано: бракує полів {', '.join(missing)}")

    lines = [f"# Звіт прогону — {slug}", ""]
    for name in REPORT_FIELDS:
        lines.append(f"- **{LABELS[name]}** (`{name}`): {_render(name, fields[name], fields)}")
    lines += ["", *CLOSING]

    directory = pathlib.Path(runs_dir) / slug
    path = directory / "report.md"
    assert_writable(path, [runs_dir])
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
