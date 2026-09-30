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
| add-core | review | Brief goes in argv with the full verify output uncapped; once it is too big the agent never starts | `src/method_sync/agent.py:137` | відкрито |
| add-core | review | On timeout only the direct child is killed; processes it started keep running | `src/method_sync/agent.py:180` | відкрито |
| add-core | review | A few unexpected errors still end in a traceback and stop the remaining methods (FR-15) | `src/method_sync/__main__.py:129` | відкрито |
| add-core | review | `--add-dir runs` with acceptEdits lets the agent edit the tool's own runs/, not only read the fixture | `src/method_sync/__main__.py:146` | відкрито |
| add-core | review | `_seconds` and `_decoded` in agent.py duplicate the helpers in verify.py | `src/method_sync/agent.py:163` | відкрито |
| add-core | review | Сесія агента успадковує налаштування, хуки і CLAUDE.md користувача та бібліотеки | `src/method_sync/agent.py:155` | відкрито |
| add-core | review | Таймаут агента вбиває лише процес claude, його дочірні процеси продовжують працювати | `src/method_sync/agent.py:180` | відкрито |
| add-core | review | Бриф передається одним аргументом argv і несе повний вивід перевірки, тож може впертися в ARG_MAX | `src/method_sync/agent.py:137` | відкрито |
| add-core | review | Coverage summary (informational, not a defect): 131 scenarios — 118 implemented (7 of them still need the e2e evidence from open task 4.4), 13 partial, 0 missing, 0 contradicted | `openspec/changes/add-core/specs:` | відкрито |
| add-core | review | Several scenario variants are covered only by source-text checks or not at all (behaviour confirmed by probes) | `tests/verify_test.py:` | відкрито |
| add-core | review | The workdir check calls tempfile.gettempdir(), which writes and deletes a probe file inside lib when TMPDIR is inside it | `src/method_sync/verify.py:341` | відкрито |
| add-core | review | On a timeout, only the direct child is killed; the agent's and verify_cmd's own children keep running into the next iteration | `src/method_sync/agent.py:180` | відкрито |
| add-core | review | A few error paths outside the guarded sections can end the whole run with a traceback | `src/method_sync/__main__.py:129` | відкрито |
| add-core | review | CLI messages still leak English argparse text in edge cases (NFR-13) | `src/method_sync/__main__.py:65` | відкрито |
| add-core | review | The brief has behaviour the spec does not describe (stage advice, a client_error line, and a fallback when no reference file exists) | `src/method_sync/agent.py:89` | відкрито |
| add-core | review | The proposal's FR range includes FR-59, which the enum spec lists as out of scope | `openspec/changes/add-core/proposal.md:` | відкрито |
| add-core | review | Код виходу раннера відкидається, тож вердикт перекриває будь-який рядок, надрукований після нього | `src/method_sync/verify.py:530` | відкрито |
| add-core | review | Покриття чек-листа (не дефект): що переглянуто і виявилось чистим | `src/method_sync/__main__.py:187` | відкрито |
