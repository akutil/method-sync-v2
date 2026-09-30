"""Межі запису інструмента (FR-91, принцип VII конституції).

Прогін пише рівно в три корені: цільову бібліотеку цього прогону (туди пише агент), власний каталог `runs/` і
тимчасовий каталог прогону. Усе інше — помилка, а не попередження: конституція каже, що правило без
автоматизованого гейта слабке, тож гейт тут, а не в голові рецензента. Шлях звіряється після розкриття `..` і
символьних посилань, як у v1.
"""
import pathlib


class OutsideBoundary(Exception):
    """Спроба записати файл поза дозволеними коренями прогону."""


def assert_writable(path, roots):
    """Пропустити шлях, якщо він лежить під одним із коренів; інакше впасти з його розкритою назвою."""
    target = pathlib.Path(path).resolve()
    for root in roots:
        if target.is_relative_to(pathlib.Path(root).resolve()):
            return target
    allowed = ", ".join(str(pathlib.Path(root).resolve()) for root in roots)
    raise OutsideBoundary(f"запис поза межами прогону: {target} (дозволено: {allowed})")
