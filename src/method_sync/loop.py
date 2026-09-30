"""Цикл до зеленого (принцип IV конституції, FR-60–FR-64, FR-68, NFR-1).

Це і є те, чим інструмент відрізняється від покрокового промптингу: людина не сидить у ролі диспетчера між агентом і
компілятором. Цикл жене агента до зеленого вердикту перевірки, рахує ітерації і лишає лог кожної. Вердикт дає лише
перевірка інструмента: слова й код виходу агента на нього не впливають (FR-75).

Про перевірку і про агента цикл нічого не знає — обидва подаються ззовні. Це не абстракція заради абстракції: рівно
так тест ганяє цикл без Maven і без агента, як `live_test.py` ганяє знімання фікстури без мережі.

Відмінності від v1: `verify_cmd` із `*` — агента не кличуть (FR-68); лог несе ключі `green`, `extra`, `missing`
англійською, розходження енамів, а для вердикту стадії — `stage` і `reason` замість порожніх переліків (FR-64).
"""
import pathlib
from dataclasses import dataclass, field

from .boundaries import assert_writable

MAX_ITERATIONS = 5
# Claude Code читає `*` у правилі `Bash(…)` як шаблон, тож єдина дозволена команда розширилась би (FR-67, FR-68).
STAR_REASON = "verify_cmd містить *, а Claude Code читає * у Bash(…) як шаблон дозволу"


@dataclass
class LoopResult:
    """Чим скінчився цикл: зеленим, чи вичерпаним лімітом ітерацій.

    `verdict` — останній вердикт, `initial_verdict` — найперший. Обидва потрібні: перший каже, що інструмент застав,
    останній — чим усе скінчилось. Звіт без першого мовчить про роботу, яку щойно зробив (FR-79).
    """

    green: bool
    converged: bool
    iterations: int
    verdict: dict
    summary: str
    initial_verdict: dict = field(default_factory=dict)
    logs: list = field(default_factory=list)


def _verdict_lines(verdict):
    """Вердикт для логу: ключі англійською, як у вердикті; для стадії — `stage` і `reason`, без порожніх переліків."""
    lines = [f"green={verdict.get('green')}"]
    if verdict.get("stage"):
        lines.append(f"stage = {verdict['stage']}")
        lines.append(f"reason = {verdict.get('reason')}")
        if verdict.get("limit_s") is not None:
            lines.append(f"limit_s = {verdict['limit_s']}")
        return lines
    lines.append(f"extra   = {verdict.get('extra')}   (зайві в моделі)")
    lines.append(f"missing = {verdict.get('missing')}   (бракує в моделі)")
    if verdict.get("client_error"):
        lines.append(f"client_error = {verdict['client_error']}")
    for entry in verdict.get("enums") or []:
        lines.append(f"енам {entry.get('field')} ({entry.get('enum')}): missing = {entry.get('missing')}, "
                     f"unseen = {entry.get('unseen')}")
    return lines


def _write_log(runs_dir, slug, number, verdict, output, agent_invoked, agent_output, skipped=None):
    directory = pathlib.Path(runs_dir) / slug
    path = directory / f"iteration-{number}.log"
    called = "так" if agent_invoked else ("ні — " + skipped if skipped else "ні")
    lines = [
        f"ітерація {number}",
        *_verdict_lines(verdict),
        f"агента покликано: {called}",
        "",
        "--- вивід команди перевірки ---",
        output or "",
    ]
    if agent_output is not None:
        lines += ["", "--- вивід агента ---", agent_output]
    assert_writable(path, [runs_dir])
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run_loop(runs_dir, slug, verify, agent, max_iterations=MAX_ITERATIONS, verify_cmd=""):
    """Ганяти `verify` і `agent` по черзі, доки перевірка не позеленіє або не скінчаться ітерації (FR-60, FR-61).

    `verify()` віддає (вердикт, вивід), `agent(вердикт, вивід)` — текст для логу; агент ніколи не кидає (FR-68).
    """
    logs = []
    verdict = {}
    initial = None
    star = "*" in (verify_cmd or "")

    for number in range(1, max_iterations + 1):
        verdict, output = verify()
        if initial is None:
            initial = verdict
        green = bool(verdict.get("green"))
        # Кликати агента після останньої перевірки безглуздо: його правку вже нікому перевірити (FR-62).
        wanted = not green and number < max_iterations
        agent_invoked = wanted and not star
        agent_output = agent(verdict, output) if agent_invoked else None
        logs.append(_write_log(runs_dir, slug, number, verdict, output, agent_invoked, agent_output,
                               skipped=STAR_REASON if wanted and star else None))

        if green:
            return LoopResult(
                green=True, converged=True, iterations=number, verdict=verdict,
                summary=f"перевірка зелена за {number} ітерацій",
                initial_verdict=initial, logs=logs)

    return LoopResult(
        green=False, converged=False, iterations=max_iterations, verdict=verdict,
        summary=f"цикл не зійшовся за {max_iterations} ітерацій",
        initial_verdict=initial or {}, logs=logs)
