# Беклог minor-знахідок review-gate

Знахідки нижче блокуючої серйозності (ADR-0003): знайдені й підтверджені, але не блокують архів слайсу.
Рядок живе тут, доки його не закрито комітом або явно не відхилено.

| Слайс | Звідки | Знахідка | Місце | Стан |
|---|---|---|---|---|
| add-input | implementer, раунд 2 | Ціле з понад 4300 цифр у `args` (напр. hex у TOML) → сирий `ValueError` із `build_url` | `src/method_sync/live.py` | відкрито |
| add-input | implementer, раунд 2 | Глибоко вкладене тіло роздуває фікстуру з `indent=2` квадратично (16 КБ → 128 МБ при 8000 рівнях, виміряно) | `src/method_sync/live.py` | відкрито |
| add-input | implementer, раунд 2 | Перевірка обрізаного тіла (`IncompleteRead` при меншому за `Content-Length`) не має тесту | `tests/live_test.py` | відкрито |
| add-input | implementer, раунд 2 | FR-26 не називає «тіло більше за 32 МБ» і «тіло надто глибоке для фікстури» серед причин недоступності | `docs/requirements.md` | відкрито |
| add-input | review раунд 3 | Пам'ять не обмежена межею тіла для chunked-відповідей (дрібні чанки → ~1,7 ГБ піку) і для 2xx≠200 (розбір усього тіла в причині) | `src/method_sync/live.py` | відкрито |
| add-input | review раунд 3 | Обґрунтування `MAX_BODY_BYTES` неточне: найбільші відповіді REST Binance сягають ~17 МБ, тож 32 МБ — ~2× запасу, не «у тисячі разів» | `src/method_sync/live.py:42` | відкрито |
| add-input | review раунд 3 | `check-trajectory` не перевіряє, за якою політикою (`blockingSeverities`) отримано `clean: true` | `scripts/check-trajectory.mjs` (locked) | відкрито |
| add-input | review раунд 3 | Тексти процесу слайсу (tasks 5.6, current-state) ще формулювали «виправити кожну підтверджену знахідку» до ADR-0003 | `openspec/changes/add-input/tasks.md` | закрито в цьому коміті |
