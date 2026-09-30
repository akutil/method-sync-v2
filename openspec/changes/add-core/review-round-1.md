# review-gate — add-core (2026-09-30, єдиний раунд швидкого шляху)

Форк `review-gate` (ADR-0003) на диф `5120275..db8018e`. 53 агенти. 22 підтверджено, 2 спірні, 0 відхилено;
блокують 6 (після дедуплікації — три проблеми), 18 — у `docs/qa/review-backlog.md`. Виправлення: регресійні тести
`d039425` (червоні) → `a14272e` (зелені); права агента — зміна специфікації `961991f` за пробою R-017.

## Блокуючі

### B-01 [major, correctness] Runner compares a non-200 or empty raw response as if it were the live body, so the verdict tells the agent to delete every model field

- **Місце:** `src/method_sync/verify.py:118`
- **Доказ:** The runner template takes `HttpClient.newHttpClient().send(...).body()` and never checks `statusCode()` or whether the body parsed to an object or array. Only the first `live.capture` checks for status 200. Every later loop iteration makes its own raw request, and a 429/418 rate limit or a 5xx during maintenance is compared as real data. I ran `verify.run` against `.sandbox/binancefutures` with a LocalServer, and the clone stayed clean. A 429 with a Binance error body `{"code":-1003,"msg":...}` gave `stage=None`, `extra` = all 8 `FuturesMarkPriceInfo` fields and `missing=["code","msg"]`. An empty 503 gave `extra` = all 8 fields and `missing=[]`. `agent._mismatch_block` turns that into "Зайві в моделі (біржа їх не віддає — прибрати): <every field>". So the agent is briefed to strip the model in the library working copy. If this happens on the first check, the report records `removed` as every field. The same code exists in v1, so it was carried over, not introduced here.
- **Пропозиція:** In the template, if `response.statusCode() != 200` throw an exception that names the status and the start of the body. Also throw when `readTree` gives a node that is neither an object nor an array (MissingNode or empty body). The outer catch then prints one line and the tool returns stage `runner` with no field lists. Optionally set a request timeout below RUNNER_TIMEOUT_SECONDS. Add integration cases to runner_integration_test.py with a LocalServer answering 429 and an empty 503, and extend FR-35 to say a non-200 raw response is a `runner` stage.

### B-02 [major, security] Раннер приймає будь-який HTTP-статус і будь-яке тіло сирого запиту: відповідь-помилка стає «живими ключами»

- **Місце:** `src/method_sync/verify.py:118`
- **Доказ:** Сирий JSON шаблон бере через `HttpClient.send(...).body()` і ніде не перевіряє `statusCode()` та наявність хоч одного ключа об'єкта. Фікстуру live.fetch знімає один раз за метод і перевіряє (200, FR-26/FR-29), а раннер робить окремий запит на кожній ітерації, хвилинами пізніше. Перевірено пробою: `verify.run` проти `.sandbox/binancefutures` з `verify_cmd="true"`, сирий URL віддає 429 `{"code":-1003,"msg":"Too many requests..."}`. Вердикт: `extra` — усі 8 полів FuturesMarkPriceInfo, `missing` — `["code","msg"]`, `client_error` — null (клієнт пройшов, помилку дав лише сирий запит). Далі бриф велить агентові прибрати всі поля прод-моделі й додати `code`/`msg`, а report.md заносить усі 8 у «Видалені поля». Тіло `[]` (FR-29) іде тим самим шляхом і дає `extra`, що дорівнює всій моделі.
- **Пропозиція:** У шаблоні раннера до `readTree` кидати виняток, якщо `statusCode() != 200`, а після розбору — якщо на верхньому рівні немає жодного ключа об'єкта (ті самі правила, що в live.fetch). Причину з кодом статусу і початком тіла назвати в тексті винятку, тоді вердикт стане стадією `runner` з цим reason. Додати інтеграційний тест з локальним сервером, що віддає 429 з JSON-тілом.

### B-03 [major, security] Агент фактично має більше, ніж одну команду verify_cmd: acceptEdits дозволяє Bash-команди файлової системи, а --add-dir дає запис у runs/

- **Місце:** `src/method_sync/agent.py:155`
- **Доказ:** Перевірено пробою на Claude Code 2.1.267 тими самими прапорцями, що дає `command()`: `-p … --permission-mode acceptEdits --add-dir <dir> --allowedTools "Bash(true)"`. Bash виконав `mkdir -p made_by_bash && touch made_by_bash/x`, хоча в allowedTools цієї команди немає. Інструмент Write створив файл у каталозі з `--add-dir`. `git add -A` відхилено. Для прогону це означає: агент може переписати `runs/<slug>/fixture.json`, тобто «джерело правди», на яке посилається `response_source` у звіті, і логи попередніх ітерацій. У lib він запускає команди ФС поза verify_cmd. Правило AGENTS.md про «рівно одну дозволену команду» і обґрунтування NFR-10 «як наслідок обмежень запуску» насправді не виконуються.
- **Пропозиція:** Фікстуру давати агентові лише на читання: або заборонити правки в runs/ (`--disallowedTools "Edit(<runs>/**)" "Write(<runs>/**)"`), або копіювати фікстуру в окремий каталог, який після агента звіряти за хешем. Замість acceptEdits розглянути явний перелік `--allowedTools "Edit(<lib>/**)" "Write(<lib>/**)" "Bash(<verify_cmd>)"` з режимом, у якому все інше автоматично відхиляється (`--permission-prompts none` / `dontAsk`). Для цього треба свідомо оновити FR-65–FR-67. Ту саму пробу закріпити e2e-перевіркою.

### B-04 [major, spec-compliance] The runner treats any HTTP reply at the method URL as the live response, so a 5xx/4xx error body or an empty 3xx gives a wrong verdict that tells the agent to delete every model field

- **Місце:** `src/method_sync/verify.py:118`
- **Доказ:** Spec field-verification FR-35: "Раннер MUST окремо брати сирий JSON рівно за рядком URL… 3xx до перевірки не доходить: живий виклик уже зупинив метод із кодом 3 (FR-26)". Code: `HttpClient.newHttpClient().send(HttpRequest.newBuilder(URI.create(__URL__)).build(), HttpResponse.BodyHandlers.ofString()).body()` has no statusCode check. The runner's request is a separate request. It is made after verify_cmd, which can take up to 600 s, and again in every iteration, so the status check in the live capture does not cover it. Probe on the .sandbox clone with a local server at the raw URL: HTTP 503 with body `{"code":-1007,"msg":"Timeout waiting…"}` gives a verdict with green=false, live=["code","msg"], extra = all 8 FuturesMarkPriceInfo fields, missing=["code","msg"], and no stage. HTTP 302 with an empty body gives live=[], extra = all 8 fields, missing=[], and no stage. The brief then says "Зайві в моделі (біржа їх не віддає — прибрати): estimatedSettlePrice, indexPrice, …". If this happens on the first check, the report's `removed` lists every field.
- **Пропозиція:** In the runner, require `statusCode() == 200` and a non-empty body before `readTree`. Otherwise throw with the status in the message, so the check reports stage `runner` with that reason. Amend FR-35/FR-43: a non-200 or empty raw response gives stage `runner`, not a comparison. Add integration tests with LocalServer returning 503 JSON and 302 empty.

### B-05 [major, spec-compliance] `--permission-mode acceptEdits` lets the agent run rm/mv/touch, which contradicts the spec's 'exactly one allowed command'

- **Місце:** `src/method_sync/agent.py:155`
- **Доказ:** Spec sync-loop Purpose: "окремий процес на ітерацію з рівно однією дозволеною командою". run-cli FR-90: "За обмежень запуску агента (FR-65–FR-67: одна дозволена команда — verify_cmd, жодної команди git)". Code: `[CLI, "-p", brief, "--permission-mode", "acceptEdits"]` + `--allowedTools Bash(<verify_cmd>)`. Probe: Claude Code 2.1.267 (the NFR-15 version) in a scratch git repo with exactly these flags (`--permission-mode acceptEdits --allowedTools 'Bash(true)'`). ~/.claude/settings.json has no permission rules and there are no managed settings. `rm victim.txt`, `mv victim2.txt moved.txt` and `touch made.txt` ran without approval and the files were really deleted, moved and created. `git add -A` was denied. So the agent can delete and move files in lib and in runs/ (the --add-dir), beyond verify_cmd. NFR-10 (no git) still holds. The scenario 'Рядок запуску агента' passes to the letter, but the requirement's premise is false.
- **Пропозиція:** Option 1: use `--permission-mode dontAsk` with explicit `--allowedTools Edit Write Bash(<verify_cmd>)`, and first check by a probe that edits stay limited to lib and runs/. Option 2: add `--disallowedTools` for the filesystem commands acceptEdits auto-approves. Option 3: amend the Purpose, FR-67 and FR-90 to say acceptEdits also allows its built-in filesystem commands. Add a probe or e2e check either way.

### B-06 [major, spec-compliance] FR-40 and FR-54 have no test anywhere (unit, integration or e2e)

- **Місце:** `tests/runner_integration_test.py:`
- **Доказ:** No `@trace FR-40` or `FR-54` appears in tests/*.py or tests/e2e/evidence.py. Uncovered scenarios: 'Успадкована властивість із зовнішнього артефакту' ("extra містить x, owners відносить x до повного імені класу P, а вердикт червоний") and 'Вкладені orderTypes і timeInForce у /fapi/v1/exchangeInfo' ("вердикт має \"enums\": []"). The behaviour itself is correct; I checked it on the clone against the live exchange. /fapi/v1/exchangeInfo with FuturesExchangeInfo gives enums=[] (plus missing ['futuresType']). /fapi/v1/ticker/price with FuturesTickerPrice gives owners price and symbol → com.binance.api.client.domain.market.TickerPrice and time → FuturesTickerPrice. What is missing is a regression test.
- **Пропозиція:** Add two RunnerOnTheClone integration tests: exchangeInfo checks enums == []; FuturesTickerPrice, or a LocalServer body without `price`, checks the owner is TickerPrice and that `extra` turns the verdict red.

## Беклог

### B-01 [minor, correctness] Brief goes in argv with the full verify output uncapped; once it is too big the agent never starts

- **Місце:** `src/method_sync/agent.py:137`
- **Доказ:** `build_brief` puts `verify_output` into the brief uncapped, and `command()` passes the whole brief as one argv element (`[CLI, "-p", brief, ...]`, line 155). The verify output holds the full Maven or javac error text and the runner's human log, including `клієнт бібліотеки повернув: " + result`, which is the whole response `toString()` and can be large for bulky endpoints. I ran `invoke` with `CLI=/usr/bin/true` and a 1.1 MB brief: it returned "агента не вдалося запустити: [Errno 7] Argument list too long" (macOS ARG_MAX is 1048576). On Linux one argv string is capped at 128 KiB. Nothing crashes, but every iteration then skips the agent and the method ends "цикл не зійшовся". The only explanation is inside the iteration logs.
- **Пропозиція:** Cap the verify output in the brief, for example the last N KB with a note that it was cut. Add the absolute path of the full `iteration-N.log` under `runs/`, which the agent can already read through `--add-dir`. Keep the iteration log itself complete, as FR-64 requires.

### B-02 [minor, correctness] On timeout only the direct child is killed; processes it started keep running

- **Місце:** `src/method_sync/agent.py:180`
- **Доказ:** `subprocess.run(..., timeout=...)` on POSIX kills only the direct child's pid. I pointed `agent.CLI` at a script that runs `sleep 47 &` and then `sleep 100`, with `timeout=1`. `invoke` returned "агент не вклався в 1 с і зупинений" after 1.0 s, but `pgrep` still showed both sleeps running. For real `claude`, a `verify_cmd` (`mvn ... test-compile`) started by its Bash tool outlives the timeout. It then writes `lib/target` while the next check's `verify_cmd` and `dependency:build-classpath` run in the same library, so a verdict can fail at random. Stray processes also remain after the CLI exits. `verify._step` (line 452) behaves the same for a `verify_cmd` that forks instead of exec'ing.
- **Пропозиція:** Write one shared helper that starts the process with `Popen(..., start_new_session=True)` and, on timeout, calls `os.killpg(proc.pid, signal.SIGKILL)` and then collects the remaining output. Use it in both `agent.invoke` and `verify._step`.

### B-03 [minor, correctness] A few unexpected errors still end in a traceback and stop the remaining methods (FR-15)

- **Місце:** `src/method_sync/__main__.py:129`
- **Доказ:** `reference = library.reference_model(...)` runs outside any try. `reference_model` calls `candidate.read_text()` on every `response/*.java` (library.py:70), so an unreadable file raises OSError out of `main` with a traceback. `verify.classpath` calls `output.read_text(encoding='utf-8')` (verify.py:500) unguarded, even though `verify.run` says "Не кидає". A UnicodeDecodeError there is a ValueError, and `main` catches only `(OutsideBoundary, OSError)` around `run_loop`, so the run dies with a traceback. An OSError from that read is reported as "лог ітерації не записано", which names the wrong failure. Unlikely in practice, but it breaks both the "no traceback" rule and FR-15.
- **Пропозиція:** Wrap the classpath file read in `StageFailed("classpath", ...)` for OSError and UnicodeDecodeError. In `reference_model`, skip unreadable candidates or return None. Keep the `run_loop` catch limited to log-write errors so its message stays accurate.

### B-04 [minor, correctness] `--add-dir runs` with acceptEdits lets the agent edit the tool's own runs/, not only read the fixture

- **Місце:** `src/method_sync/__main__.py:146`
- **Доказ:** `agent(brief, cwd=lib, add_dirs=[runs], ...)` adds the whole `runs/` as a working directory. Per the Claude Code docs, added directories follow the session permission mode, and `acceptEdits` auto-approves edits there. So besides `verify_cmd`, the agent can write fixtures, earlier `iteration-N.log` files and other methods' `report.md`. Those are the files the human uses to decide on the diff, and "Пиши лише всередині {lib}" is only a line in the brief. The verdict itself is safe, because the runner fetches raw JSON on its own. I did not probe this against real `claude`, since that costs a paid run.
- **Пропозиція:** Pass the narrowest directory, `runs/<slug>`, or put a read-only copy of the fixture in the per-run temp directory and add that instead. Note the choice in FR-66 so the extra write scope is a stated decision rather than a side effect.

### B-05 [minor, correctness] `_seconds` and `_decoded` in agent.py duplicate the helpers in verify.py

- **Місце:** `src/method_sync/agent.py:163`
- **Доказ:** `agent._seconds` and `agent._decoded` are copies of `verify.seconds` (verify.py:329) and `verify._decoded` (verify.py:438). report.py already imports `seconds` from verify. Two copies of the limit formatting can drift apart, and the NFR-3 log text "агент не вклався в N с" depends on it.
- **Пропозиція:** Import `seconds` from verify, or move both helpers into one small shared module used by verify, agent and report. That module could also hold the process-group helper from the timeout finding.

### B-06 [minor, security] Сесія агента успадковує налаштування, хуки і CLAUDE.md користувача та бібліотеки

- **Місце:** `src/method_sync/agent.py:155`
- **Доказ:** Рядок запуску ніяк не обмежує джерела налаштувань. Під час тієї ж проби в headless-виводі агента з'явився чек-лист зі Stop-хука `checklist-on-stop.py` з `~/.claude/settings.json`. Отже в кожній ітерації працюють хуки користувача і глобальний CLAUDE.md, які суперечать брифу («Зроби правку і зупинись»), а Stop-хук повертає агента на доробку до 3 разів. Будь-яке `permissions.allow` у `~/.claude/settings.json` чи `<lib>/.claude/settings*.json`, скажімо `Bash(git add:*)`, непомітно розширить права агента понад verify_cmd. Зараз таких правил немає: перевірено в ~/.claude/settings.json, у .sandbox/binancefutures/.claude і в /Users/akutil/humex/binancefutures/.claude. Тож розширення прав поки лише умовне.
- **Пропозиція:** Обмежити джерела налаштувань агента (`--setting-sources`, щоб не вантажити user-хуки), а перед викликом агента перевіряти `<lib>/.claude/settings.json` і `settings.local.json`. Якщо там є `permissions.allow` чи `defaultMode`, метод зупиняти з поясненням. Результат перевірити тією самою пробою: Stop-хук не спрацьовує, `git add` відхилено.

### B-07 [minor, security] Таймаут агента вбиває лише процес claude, його дочірні процеси продовжують працювати

- **Місце:** `src/method_sync/agent.py:180`
- **Доказ:** `subprocess.run(timeout=…)` на POSIX надсилає kill лише прямому нащадку. Перевірено: фальшивий `claude` у PATH запускав фоновий `sleep 47`. `invoke(timeout=1)` повернув «агент не вклався в 1 с і зупинений», а `sleep 47` після цього працював далі. У реальному прогоні це `mvn`, запущений Bash-інструментом агента: він продовжує писати в `<lib>/target` одночасно з verify_cmd і javac наступної ітерації. Звідси можуть братися хибні стадії compile/javac.
- **Пропозиція:** Запускати агента через `Popen(..., start_new_session=True)`, а на таймауті робити `os.killpg(proc.pid, SIGKILL)` і тоді дочитувати вивід. Те саме застосувати в `verify._step` до verify_cmd, яка сама не робить exec.

### B-08 [minor, security] Бриф передається одним аргументом argv і несе повний вивід перевірки, тож може впертися в ARG_MAX

- **Місце:** `src/method_sync/agent.py:137`
- **Доказ:** У бриф повністю йде `verify_output`, зокрема рядок раннера «клієнт бібліотеки повернув: <toString результату>», а весь бриф — один елемент argv. На цьому macOS `getconf ARG_MAX` = 1048576. Проба `subprocess.run(['true', 'x'*1100000])` дала `OSError [Errno 7] Argument list too long`. Для методів, що повертають великі списки, `invoke` щоітерації повертатиме «агента не вдалося запустити», і метод не зійдеться. Traceback не буде, але причина губиться в лозі. Для трьох методів поточного registry.toml вивід малий.
- **Пропозиція:** Обрізати вивід перевірки в брифі до розумної межі й давати шлях до повного `iteration-N.log`, або класти бриф файлом у runs/<slug>/ і передавати коротке посилання на нього.

### B-09 [minor, spec-compliance] Coverage summary (informational, not a defect): 131 scenarios — 118 implemented (7 of them still need the e2e evidence from open task 4.4), 13 partial, 0 missing, 0 contradicted

- **Місце:** `openspec/changes/add-core/specs:`
- **Доказ:** By capability: field-verification 31 (25 implemented, 6 partial), enum-verification 23 (18 implemented, 2 of them waiting on e2e, 3 partial), sync-loop 28 (25 implemented, 2 waiting on e2e, 1 partial: the agent's permissions), run-report 23 (all implemented), run-cli 26 (21 implemented, 3 waiting on e2e, 2 partial). I re-ran what the ticked tasks claim and it holds. `npm run lint` and `npm run build` pass; `openspec validate --all --strict` gives 3/3; unit tests give 221 OK with 17 gated skips; runner integration with METHOD_SYNC_LIVE=1 on .sandbox/binancefutures against the live exchange gives 14/14 OK and leaves the clone's `git status` clean; `check:trace` passes with 0 failures. The tests were not changed between the red commit 5974e3e and the green commit db8018e. registry.toml exists. Every ticked task has its artifact. Tasks 4.3, 4.4 and 4.5 are correctly left open.
- **Пропозиція:** No action. This item carries the one-line coverage summary the output contract asks for.

### B-10 [minor, spec-compliance] Several scenario variants are covered only by source-text checks or not at all (behaviour confirmed by probes)

- **Місце:** `tests/verify_test.py:`
- **Доказ:** Scenarios with no real-process test:
- FR-37 'Модель-нащадок конверта': only a test that the envelope strings appear in the source.
- FR-43 'Виняток раннера поза викликом клієнта': only `parse_result` on a hard-coded string.
- FR-33 'Класпас не зібрався'.
- FR-34 'Значення, якого Java не приймає'.
- NFR-5: the javac time-limit variant.
- FR-43: missing javac/java (only missing mvn is tested).
- FR-50 '@JsonProperty і @JsonValue'.
- FR-55: the `;` becomes `,` rule (enum `Side`).
- FR-14: duplicate entries with the same slug.
- FR-92: the audit-hook scenario for secret files.
- FR-93: the audit-hook scenario for direct child processes.
- NFR-2: the human-log line surviving a runner timeout.
My probes on a disposable copy of the clone:
- args with 1727654400000 give stage javac, and the output contains 'integer number too large'.
- javac_timeout=0.01 gives stage javac with limit_s 0.01.
- A model with setX(Integer)/setX(Long) gives stage runner, and the reason quotes 'java.lang.IllegalArgumentException: Conflicting setter definitions for property "x"'.
- Enums with @JsonProperty("foo") and @JsonValue give declared ["BAR","foo"] and ["alpha","beta"], missing ["FOO"] and ["A"]. The ordinal string "0" is correctly reported missing.
- **Пропозиція:** Add these as integration tests (the modified-copy fixture in runner_integration_test.py already supports test models), plus CLI tests for duplicates and audit-hook tests for FR-92 and FR-93.

### B-11 [minor, spec-compliance] The workdir check calls tempfile.gettempdir(), which writes and deletes a probe file inside lib when TMPDIR is inside it

- **Місце:** `src/method_sync/verify.py:341`
- **Доказ:** Spec FR-32: "Місце MUST перевірятися… до створення каталогу раннера: якщо корінь тимчасових каталогів… лежить у ньому… під lib не з'являється нічого (FR-32, FR-44)". Code: `root = pathlib.Path(tempfile.gettempdir()).resolve()`. On its first call, CPython's `_get_default_tempdir` creates and removes a probe file in the candidate directory. Audit-hook probe with TMPDIR=<lib>/tmp: `open ('<lib>/tmp/kpk7pv_6', None, 16780034)`, then `os.remove` of the same path, then verdict stage `workdir`. The existing test only compares the file listing after the run, so it cannot see this.
- **Пропозиція:** Resolve the root without probing: go through TMPDIR/TEMP/TMP in tempfile's order, check the first set one against lib, and only then call mkdtemp. Or amend FR-32/FR-44 to allow the transient stdlib probe.

### B-12 [minor, spec-compliance] On a timeout, only the direct child is killed; the agent's and verify_cmd's own children keep running into the next iteration

- **Місце:** `src/method_sync/agent.py:180`
- **Доказ:** NFR-3: "На ліміті процес агента зупиняють". agent.invoke and verify._step call `subprocess.run(..., timeout=...)` without a new session and without killing the process group. Probe: a fake `claude` that runs `sleep 41 &; wait`. `invoke(timeout=1)` returned "агент не вклався в 1 с і зупинений", but `pgrep` still showed `33255 sleep 41` afterwards. With the real agent, a verify_cmd (`mvn … test-compile`) started by its Bash tool survives the kill and races the next iteration's verify_cmd in the same target/.
- **Пропозиція:** Use `start_new_session=True` and `os.killpg` on TimeoutExpired, for both the agent and the verify steps. Reuse `kill_group` from tests/e2e/evidence.py rather than writing a new helper.

### B-13 [minor, spec-compliance] A few error paths outside the guarded sections can end the whole run with a traceback

- **Місце:** `src/method_sync/__main__.py:129`
- **Доказ:** FR-15 counts an internal tool error in a method as a failure that must not stop the rest of the list. `_sync_one` only guards `run_loop` (OutsideBoundary, OSError) and `write_report`. Two paths are unguarded:
- `library.reference_model(...)` at __main__.py:129 reads every response/*.java; an unreadable file raises PermissionError.
- `verify.classpath` reads cp.txt with `read_text(encoding='utf-8')` at verify.py:500. A UnicodeDecodeError there is a ValueError: `run()` does not turn it into a stage verdict and `_sync_one` does not catch it.
I did not probe either; both need an unusual environment.
- **Пропозиція:** Catch OSError around reference_model and return code 1 with a line for the method. In `classpath`, catch (OSError, UnicodeDecodeError) and raise StageFailed('classpath').

### B-14 [minor, spec-compliance] CLI messages still leak English argparse text in edge cases (NFR-13)

- **Місце:** `src/method_sync/__main__.py:65`
- **Доказ:** Spec run-cli: the explanation must be in Cyrillic, "без англомовного тексту argparse". Probes:
- `--dry-run=1` prints "прапорець --dry-run задано хибно: ignored explicit argument '1'".
- `-h` prints English `usage: method_sync [-h] …` and exits 0; help is not in the spec.
- `--max-iterations 2 --max-iterations` prints "невідомий аргумент командного рядка: --max-iterations 2 --max-iterations", which misnames the problem.
The four cases in the scenario (--bogus, --only with no value, abc, 0) are handled correctly.
- **Пропозиція:** Translate the fallback branch of `_explain`. Either set add_help=False or give a Ukrainian help text, and put the -h behaviour in the spec.

### B-15 [minor, spec-compliance] The brief has behaviour the spec does not describe (stage advice, a client_error line, and a fallback when no reference file exists)

- **Місце:** `src/method_sync/agent.py:89`
- **Доказ:** - `_STAGE_ADVICE` adds advice text for the compile, javac and timeout stages.
- `_mismatch_block` adds "Клієнт бібліотеки кинув виняток: …".
- __main__.py:139 passes "(у response/ модуля немає self-contained файлу)" when there is no reference file, while FR-72 says "Бриф MUST давати абсолютний шлях еталона".
None of these is covered by FR-71 or FR-72. They are harmless, but the code and the spec have drifted apart.
- **Пропозиція:** Amend FR-71 to cover the stage advice and the client_error line. Amend FR-72 to cover the case with no self-contained reference file (for example: stop the method, or keep the placeholder deliberately).

### B-16 [minor, spec-compliance] The proposal's FR range includes FR-59, which the enum spec lists as out of scope

- **Місце:** `openspec/changes/add-core/proposal.md:`
- **Доказ:** Proposal: "FR-14…FR-22, FR-31…FR-44, FR-46…FR-84, FR-90…FR-93". That range is 66 FRs and includes FR-59. The enum-verification spec says 'Поза обсягом: Енамні поля вкладених об'єктів і масивів (FR-59…)'. docs/mvp-capability-plan.md gives the enum FRs as FR-47…FR-58, 65 MVP FRs in total.
- **Пропозиція:** Change the proposal to "FR-46…FR-58, FR-60…FR-84".

### B-17 [minor, security] Код виходу раннера відкидається, тож вердикт перекриває будь-який рядок, надрукований після нього

- **Місце:** `src/method_sync/verify.py:530`
- **Доказ:** `_run_runner` повертає лише `step.stdout`, а `parse_result` бере останній непорожній рядок. Спека каже, що раннер виходить з кодом 0 лише після зеленого вердикту, але інструмент цього не звіряє. У бібліотеці є `target/classes/log4j2.xml` з Console-апендером `SYSTEM_OUT` на рівні INFO. Рядок, який потік бібліотеки чи shutdown-hook надрукує після вердикту, дає хибну стадію `runner`. Зворотний випадок — рядок зеленого вердикту, надрукований shutdown-hook'ом з коду моделі, яку правив агент: він буде прийнятий, хоча раннер вийшов з кодом 1. Це чиста теорія з коду, пробою не перевірено.
- **Пропозиція:** Повертати з `_run_runner` і код виходу. Зелений вердикт при ненульовому коді (і червоний при коді 0) звертати на стадію `runner` з reason, що називає обидва.

### B-18 [minor, security] Покриття чек-листа (не дефект): що переглянуто і виявилось чистим

- **Місце:** `src/method_sync/__main__.py:187`
- **Доказ:** 1) Authz/IDOR/tenant і 2) auth/сесії — не застосовні: немає маршрутів, ролей і сесій. Аналог authz, межа прав агента, винесено в окремі знахідки. 3) Ін'єкції: шел ніде не використовується (shlex.split, списки argv); URL у раннер іде повністю екранованим (`_java_string`); slug прибирає `/`, тож обходу шляху немає. Запис інструмента — лише fixture, iteration-N.log і report.md під runs/ з `assert_writable`/`_require_inside`, раннер — у tmp з rmtree. `java_literal`/`call`/`model` підставляються в Java без екранування, але за дизайном (FR-8/FR-34) це вхід людини з реєстру. 4) Секрети: у src/ немає ключів і паролів, `credentials` в інструмент не потрапляють, .sandbox/ ігнорується git. 5) Залежності: лише stdlib, аудиту нема чого робити. 6) Коди виходу: SEVERITY 0<1<3<2<4, усі гілки `_sync_one` повертають код зі шкали, CLI-помилки дають код 2. Traceback на звичайних шляхах немає. 221 unit-тест зелений (17 skipped: live-шар).
- **Пропозиція:** Дій не потрібно.

