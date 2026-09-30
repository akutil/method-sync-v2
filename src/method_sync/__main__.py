"""CLI method-sync: прогін по реєстру методів (FR-14–FR-22, NFR-6, NFR-7).

    PYTHONPATH=src python3 -m method_sync --registry registry.toml [--only /fapi/v1/premiumIndex]

Прогін іде списком згори вниз. Падіння одного методу не спиняє решту (FR-15), а підсумковий код виходу показує
найгірше, що сталося, а не останнє (NFR-7). Результат прогону — правка в робочій копії бібліотеки плюс звіт; рішення
про історію репозиторію належить людині (принцип VI).

Відмінності від v1 (design.md): ранні перевірки FR-22 → FR-20 → FR-21 ідуть до живого виклику; відсутній клас моделі
— код 2; `FixtureWriteError` — код 1, і прогін іде далі; `--dry-run` пише `iteration-1.log`; `--max-iterations` ≥ 1;
хибний командний рядок — код 2 і пояснення українською без тексту argparse.
"""
import argparse
import pathlib
import sys

from . import agent as agent_module
from . import boundaries, library, live, loop, registry, report
from . import verify as verify_module

EXIT_OK = 0
EXIT_RED = 1
EXIT_REGISTRY = 2
EXIT_LIVE_UNAVAILABLE = 3
EXIT_NO_STYLE_STANDARD = 4

# Що гірше, те й перемагає: непридатний реєстр і відсутній стандарт стилю кажуть про прогін більше, ніж одна червона
# перевірка чи недоступна біржа (NFR-7).
SEVERITY = (EXIT_OK, EXIT_RED, EXIT_LIVE_UNAVAILABLE, EXIT_REGISTRY, EXIT_NO_STYLE_STANDARD)

RUNS_DIR = live.RUNS_DIR
REVIEWER = "не викликався — рецензію запускає окрема сесія (принцип V)"
DRY_RUN_RESULT = "dry-run: агента не кликали"


class CommandLineError(Exception):
    """Командний рядок не приймається: прогін зупиняється до першого методу з кодом 2 (FR-61, NFR-13)."""


class _Parser(argparse.ArgumentParser):
    """argparse без виходу з процесу: помилку пояснює `parse_args` українською, а не англомовний `usage:`."""

    def error(self, message):
        raise CommandLineError(f"хибний командний рядок: {message}")


def _max_iterations(text):
    try:
        value = int(text)
    except ValueError:
        value = 0
    if value < 1:
        raise argparse.ArgumentTypeError(f"--max-iterations {text}: потрібне ціле число, не менше 1")
    return value


def _explain(error):
    name = error.argument_name
    if name is None:
        return f"хибний командний рядок: {error.message}"
    if error.message.startswith(name):  # власне пояснення `_max_iterations`
        return error.message
    if "expected one argument" in error.message:
        return f"прапорець {name} потребує значення, а його не задано"
    return f"прапорець {name} задано хибно: {error.message}"


def parse_args(argv=None):
    parser = _Parser(prog="method_sync", description=__doc__, allow_abbrev=False, exit_on_error=False,
                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--registry", help="шлях до TOML-реєстру методів")
    parser.add_argument("--only", help="прогнати лише записи з цим path")
    parser.add_argument("--max-iterations", type=_max_iterations, default=loop.MAX_ITERATIONS,
                        help="ліміт ітерацій циклу на метод, ціле число ≥ 1")
    parser.add_argument("--dry-run", action="store_true",
                        help="зняти фікстуру і перевірити один раз, агента не кликати")
    try:
        args, unknown = parser.parse_known_args(argv)
    except argparse.ArgumentError as error:
        raise CommandLineError(_explain(error)) from error
    if unknown:
        raise CommandLineError(f"невідомий аргумент командного рядка: {' '.join(unknown)}")
    if args.registry is None:
        raise CommandLineError("бракує прапорця --registry — шляху до TOML-реєстру методів")
    return args


def worst(codes):
    """Найгірший код виходу зі списку — за шкалою серйозності 0 < 1 < 3 < 2 < 4, а не за числом (NFR-7)."""
    return max(codes, key=SEVERITY.index, default=EXIT_OK)


def _early_stop(reg, method):
    """Ранні перевірки до живого виклику у відносному порядку v1 (FR-22 → FR-20 → FR-21): (код, причина) або None."""
    try:
        library.style_standard(reg.lib)
    except library.StyleStandardMissing as error:
        return EXIT_NO_STYLE_STANDARD, str(error)
    if library.model_file(reg.lib, method.model) is None:
        return EXIT_REGISTRY, (f"клас моделі {method.model} у бібліотеці {reg.lib} відсутній — реалізація з нуля поза "
                               "обсягом")
    try:
        library.module_for(method.path)
    except ValueError as error:
        return EXIT_REGISTRY, str(error)
    return None


def _sync_one(reg, method, args, runs_dir, verify, agent):
    """Прогнати один метод. Віддає (код виходу, рядок підсумку)."""
    stop = _early_stop(reg, method)
    if stop:
        code, reason = stop
        return code, f"{method.path}  {reason}"

    url = live.build_url(reg.base_url, method.path, method.args)
    try:
        fixture = live.capture(reg.base_url, method.path, method.args, runs_dir)
    except live.LiveUnavailable as error:
        return EXIT_LIVE_UNAVAILABLE, f"{method.path}  {error}"
    except live.FixtureWriteError as error:
        return EXIT_RED, f"{method.path}  {error}"

    # Агент працює з кореня бібліотеки, а фікстура лежить у каталозі інструмента — обидва шляхи абсолютні, інакше
    # агент фікстури не побачить (з'ясовано першим живим прогоном v1).
    lib = pathlib.Path(reg.lib).resolve()
    runs = pathlib.Path(runs_dir).resolve()
    fixture = pathlib.Path(fixture).absolute()
    reference = library.reference_model(lib, library.module_for(method.path))

    def check():
        return verify(lib, method, url, reg.verify_cmd)

    def fix(verdict, output):
        brief = agent_module.build_brief(
            lib=str(lib),
            method_path=method.path,
            model=method.model,
            reference_method=str(reference) if reference else "(у response/ модуля немає self-contained файлу)",
            fixture_path=str(fixture),
            mismatch=verdict,
            verify_output=output,
            verify_cmd=reg.verify_cmd,
        )
        # Команда перевірки — єдиний Bash, який агентові дозволено: інакше він повертає правку неперевіреною.
        return agent(brief, cwd=lib, add_dirs=[runs], allowed_commands=[reg.verify_cmd])

    iterations = 1 if args.dry_run else args.max_iterations
    try:
        result = loop.run_loop(runs_dir, method.slug, check, fix, max_iterations=iterations,
                               verify_cmd=reg.verify_cmd)
    except (boundaries.OutsideBoundary, OSError) as error:
        return EXIT_RED, f"{method.path}  лог ітерації не записано: {error}"

    first = result.initial_verdict
    if result.green:
        verify_result = "green"
    else:
        verify_result = DRY_RUN_RESULT if args.dry_run else result.summary
    try:
        report.write_report(
            runs_dir, method.slug,
            mode="refresh",
            request_source="registry",
            response_source=str(fixture),
            # Розходження показуються ті, що інструмент застав, а не ті, що лишились після правки (FR-79).
            mismatch=first,
            removed=first.get("extra") or [],
            verify_cmd=reg.verify_cmd,
            verify_result=verify_result,
            iterations=result.iterations,
            reviewer=REVIEWER,
            left_to_human=[],
            enum_mismatch=first,
            enum_unseen=first,
        )
    except ValueError as error:
        return EXIT_RED, f"{method.path}  {error}"
    except (boundaries.OutsideBoundary, OSError) as error:
        return EXIT_RED, f"{method.path}  звіт не записано: {error}"

    code = EXIT_OK if result.green else EXIT_RED
    return code, (f"{method.path}  refresh  ітерацій={result.iterations}  "
                  f"перевірка={'green' if result.green else 'red'}")


def main(argv=None, *, runs_dir=RUNS_DIR, verify=verify_module.run, agent=agent_module.invoke):
    """Прогін по реєстру. `runs_dir`, `verify` і `agent` — межа зі стороннім світом, як у v1: тести підміняють лише її."""
    try:
        args = parse_args(argv)
    except CommandLineError as error:
        print(error, file=sys.stderr)
        return EXIT_REGISTRY

    try:
        reg = registry.load(args.registry)
    except registry.RegistryError as error:
        print(f"реєстр непридатний: {error}", file=sys.stderr)
        return EXIT_REGISTRY

    methods = [method for method in reg.methods if args.only in (None, method.path)]
    if not methods:
        print(f"у реєстрі немає методу {args.only}", file=sys.stderr)
        return EXIT_REGISTRY

    codes = []
    for method in methods:
        code, line = _sync_one(reg, method, args, runs_dir, verify, agent)
        codes.append(code)
        print(line, flush=True)

    green = sum(1 for code in codes if code == EXIT_OK)
    print(f"підсумок: {len(codes)} методів, {green} зелених, {len(codes) - green} червоних")
    return worst(codes)


if __name__ == "__main__":
    sys.exit(main())
