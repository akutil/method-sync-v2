# review-gate, раунд 3 — add-input (2026-09-30)

Workflow `review-gate` на диф `949d74b..fbe69d2`. 37 агентів. 15 підтверджено, 1 спірна, 0 відхилено.
Прогін ішов за старою логікою воркфлоу (назва резолвиться на скрипт, завантажений на старті сесії, а не на форк з
диска), тож `clean` у доказі порахований без ADR-0003. Вручну за ADR-0003: блокує 1 (major, спірна) — форк не
застосовував `severityAdjustment` верифікаторів; виправлено в тому ж коміті, що й цей запис. Решта — minor,
перенесено в `docs/qa/review-backlog.md`; U+202E і шляхи скретчпаду в записі раунду 2 та ім'я в ADR-0003 виправлено.

## R3-01 [confirmed, minor, correctness] review-round-2.md adds 8 raw U+202E characters, the same Trojan Source defect that 7.3 removed from design.md

- **Місце:** `openspec/changes/add-input/review-round-2.md:18`
- **Доказ:** A byte scan finds 8 raw RIGHT-TO-LEFT OVERRIDE characters (E2 80 AE), none closed by U+202C, on lines 18, 21, 22, 42, 45, 46, 66 and 67. Each one sits where the reviewers meant the six-character escape `\u202e`. The file was added in 21dc0f5, the same commit that ticks 7.3 ('у design.md D9 буквальний U+202E замінено текстом'). `git grep` now finds this file as the only tracked file with the character, so the defect moved from the spec into the record of the finding, where it reverses the rest of each line in viewers that handle bidi text.
- **Пропозиція:** Replace each raw U+202E with the literal text `\u202e`. The JSON evidence already has it escaped. Add the lint step that R2-03/R2-09 proposed: reject Cf/Cc characters other than tab and newline in src/, tests/, openspec/ and docs/. Then a verbatim paste cannot bring it back.

## R3-02 [confirmed, minor, correctness] For 2xx statuses other than 200, _status_reason decodes and splits the whole capped body: a 32 MiB body reached 760 MiB RSS

- **Місце:** `src/method_sync/live.py:435`
- **Доказ:** Statuses 201, 202 and 206 arrive as normal responses, not as HTTPError. So `fetch` passes the whole body, up to MAX_BODY_BYTES+1, to `_status_reason` (line 221) before the size check on line 222. Line 435 then does `_server_text(raw.decode(...))`, which runs `" ".join(text.split())` over all of it before cutting to 200 characters. Probe against a real local http.server: status 201 with 32 MiB of "ab " gave LiveUnavailable after 0.42 s at 760 MiB peak RSS, against 127 MiB for a 32 MiB single-token body. The HTTPError path already reads only EXCERPT_BYTES (4096), so this is a residual of R2-08 that fix 7.6 did not cover.
- **Пропозиція:** Pass `raw[:EXCERPT_BYTES]` to `_status_reason`, the same bound the HTTPError path uses, and/or make `_server_text` lazy: iterate `re.finditer(r"\S+", text)` and stop once EXCERPT_CHARS is exceeded. Add a regression test: a 201 body of many short tokens, well above EXCERPT_BYTES, with an assertion on reason length.

## R3-03 [confirmed, minor, correctness] The stated rationale for MAX_BODY_BYTES is wrong: real Binance REST bodies reach 16.9 MiB, not kilobytes

- **Місце:** `src/method_sync/live.py:42`
- **Доказ:** live.py:42 says 'Тіло REST Binance важить кілобайти, тож 32 МБ у тисячі разів більше за будь-яке', and design.md:123 and tasks.md:194 repeat it. Measured live on 2026-09-30: /fapi/v1/exchangeInfo has Content-Length 1,141,820 B, so the cap is about 29x that. /api/v3/exchangeInfo has 17,679,403 B, only 1.9x under the cap; through live.capture it became a 31.0 MiB fixture at 301 MiB RSS. A body over the cap is reported as 'тіло більше за 32 МБ' with code 3, which matters once FR-108 brings in /api/ (FR-21 already maps /api/ to binanceSpot). The cap does not bound memory to anything near 32 MB either: 32 MiB of `[],` went through capture at 1071 MiB peak RSS.
- **Пропозиція:** Replace the rationale with the measured sizes (date, endpoint, bytes) and choose the cap with both sides in view: the largest real body in scope, and the memory multiplication from parsing and serialising. For example, keep 32 MB for the /fapi/ MVP but record the 1.9x spot margin as a Risk to revisit before FR-108. Fix the same sentence in design.md D8 and tasks 7.6.

## R3-04 [confirmed, minor, correctness] The review-gate fork decides blocking from the finder's own severity and drops the verifiers' severityAdjustment

- **Місце:** `.claude/workflows/review-gate.js:125`
- **Доказ:** `blocking = [...confirmed, ...contested].filter((f) => blockingSeverities.includes(f.severity))` uses only the severity the finder assigned. VERDICT_SCHEMA (line 42) still asks each verifier for `severityAdjustment`, but line 116 keeps only `reasoning`, so even two 'upgrade' votes cannot make a finding block. Round 2 shows the risk: the same containment defect came in as R2-01 [major] and R2-10 [minor], and R2-06 (a raw MemoryError/OverflowError that ends in a traceback) was rated minor. Under ADR-0003, R2-06 would have gone to the backlog without blocking.
- **Пропозиція:** Compute an effective severity from the votes, for example: raise it one level if any non-refuting verifier says upgrade, lower it only if all say downgrade. Block on that effective severity, and write both the original and effective severity to review-findings.json and backlogTitles. Alternatively, have the verifier prompt re-rate severity against the critical/major/minor rubric. Record the rule in ADR-0003.

## R3-05 [confirmed, minor, correctness] blockingSeverities accepts any array, and check-trajectory never checks which policy produced clean:true

- **Місце:** `.claude/workflows/review-gate.js:52`
- **Доказ:** `Array.isArray(args?.blockingSeverities) ? args.blockingSeverities : ['critical','major']` accepts [], ['critical'], or a misspelled value such as 'Major'. Each of these yields `clean: true` for a run that has confirmed majors. scripts/check-trajectory.mjs:80 allows archiving on `JSON.parse(rf).clean === true` alone and never reads `blockingSeverities`, so a clean flag produced under a weaker policy than ADR-0003 passes the deterministic gate. The weaker policy is visible only to someone who reads the evidence file.
- **Пропозиція:** In check-trajectory, count review evidence as clean only when `blockingSeverities` includes 'critical' and 'major', or when a waiver file names the exception. In the workflow, reject values outside the severity enum instead of silently matching nothing.

## R3-06 [confirmed, minor, correctness] Committed review record adds scratchpad paths that carry the company name and the owner's username

- **Місце:** `openspec/changes/add-input/review-round-2.md:27`
- **Доказ:** Lines 27, 33 and 39 cite probe scripts at `<скретчпад сесії>`, a path that contains the company name and the owner's username. AGENTS.md Boundaries (added in 69d5df3, before this commit) forbids adding company or people names to new texts beyond what the target library code requires. The paths also point into a scratchpad that exists only for this session, so the evidence they cite will disappear. ADR-0003:5 likewise adds the owner's full name, following the precedent in ADR-0001.
- **Пропозиція:** Replace the paths with a neutral note (e.g. 'probe script in the session scratchpad, not kept'), or copy the probes into a tracked, anonymised location under docs/qa/. Decide once whether ADR 'Deciders' may name people, and write that into AGENTS.md so new ADRs follow the boundary consistently.

## R3-07 [confirmed, minor, security] Body cap does not bound memory for chunked responses: chunk size -1 reads to EOF, and 2-byte chunks turn the 32 MB cap into a 1.7 GB peak (R2-06/R2-08 fix incomplete)

- **Місце:** `src/method_sync/live.py:416`
- **Доказ:** Attack: whoever answers for base_url replies with Transfer-Encoding: chunked. That can be a hostile or compromised endpoint, an on-path attacker for http://, or the http_proxy for http:// URLs. `response.read(MAX_BODY_BYTES + 1)` bounds only the non-chunked path. In Python 3.14.0, `HTTPResponse._read_chunked(amt)` calls `_safe_read(chunk_left)` whenever amt > chunk_left. `_read_next_chunk_size` is `int(line, 16)`, so it accepts '-1', and `_safe_read(-1)` is `fp.read(-1)`, which reads to EOF. The non-200 branch hits the same code through `error.read(EXCERPT_BYTES)` (line 424). A second, independent problem: `_read_chunked` keeps one bytes object per chunk until amt is reached, so 32 MB of 2-byte chunks costs about 1.7 GB even though the cap holds. Probes ran through live.fetch against a raw local server, with the repo untouched (<scratchpad>/r3sec/probe_negchunk.py, probe_tinychunks.py):
- chunk size -1, then 160 MB: all of it read ('IncompleteRead(167772160 bytes read)'), peak RSS 370 MB;
- the same with status 500: 'статус HTTP 500, а не 200', peak RSS 530 MB;
- a paced endless -1 stream with timeout 0.5 s: 73 MB sent before the verdict, peak RSS 186 MB, so at the real 15 s only bandwidth limits growth;
- 2-byte chunks at the real 15 s limit: 114 MB of traffic, 'тіло більше за 32 МБ' after 14.1 s, peak RSS 1726 MB.
Controls on the same harness stop at the cap with peak RSS 63 MB: a non-chunked endless body, and chunk size ffffffffffffffff. Every probe still ended in a typed LiveUnavailable. A raw MemoryError on a machine with less memory is the likely next step, but I did not verify it. So the claim in design D8 and the MAX_BODY_BYTES comment, that a server cannot make the client pull the body into memory before the verdict, holds only for non-chunked bodies. Task 7.6 is ticked on that claim.
- **Пропозиція:** (1) Refuse negative chunk sizes before http.client acts on them. Add `class _Response(http.client.HTTPResponse)` whose `_read_next_chunk_size` closes the connection and raises ValueError when the size is below 0; `_get_chunk_left` already turns that ValueError into IncompleteRead. Set `response_class = _Response` on `_Connection`. `_SecureConnection` inherits it through the MRO, and it covers the 200 path, the HTTPError branch and the proxy CONNECT reply. (2) Read the body in bounded steps into a bytearray: `while len(buf) <= MAX_BODY_BYTES: piece = response.read(min(64 * 1024, MAX_BODY_BYTES + 1 - len(buf)))`, stop on an empty piece, then keep the existing length/IncompleteRead check. Both changes were checked by monkeypatching in a throwaway process (<scratchpad>/r3sec/probe_remedy.py, run_suite_with_remedy.py):
- chunk -1: 'IncompleteRead(0 bytes read)' at peak 31 MB;
- status 500: peak 31 MB;
- 2-byte chunks: 'тіло більше за 32 МБ' at peak 89 MB;
- non-chunked controls: unchanged;
- tests/live_test.py: 58 tests OK.
Add regression tests on a raw local server with a lowered cap. First, chunked '-1' followed by more than the cap, for status 200 and for 500; assert the client hung up before the server delivered much more than the cap. Second, 2-byte chunks with a tracemalloc peak bound. Extend the memory claim in D8 to chunked responses.

## R3-08 [confirmed, minor, security] review-round-2.md reintroduces 8 raw U+202E RIGHT-TO-LEFT OVERRIDE characters: the transcription decoded the reviewers' escape into the character that R2-03/R2-07/R2-09 removed from design.md

- **Місце:** `openspec/changes/add-input/review-round-2.md:18`
- **Доказ:** I scanned the code points of every file changed in 949d74b..HEAD. U+202E appears in review-round-2.md on lines 18, 21, 22, 42, 45 and 46, and twice more further down the file (at 66 and 67). It appears nowhere else; design.md is clean now. The round-2 reviewers wrote a six-character escape. It reached the findings as a JSON unicode escape, and copying the findings 'дослівно' decoded it into the real character. As a result the recorded R2-03 proposal now reads 'replace the character with the text <RLO>'. Bidi-aware editors, diff viewers and rendered Markdown reorder the rest of each affected line or paragraph. This is the same Trojan Source class (CVE-2021-42574) that round 2 rated minor, and task 7.3 marks it fixed in the same commit. The file is archived together with the change.
- **Пропозиція:** Replace each U+202E in review-round-2.md with the plain text 'U+202E'. Change the transcription step so escapes stay as text and are not decoded. Add the lint step that R2-03/R2-07/R2-09 proposed: `npm run lint` fails on U+202A–U+202E and U+2066–U+2069 in tracked text under src/, tests/, openspec/ and docs/. The same problem came back in the diff that fixed it by hand.

## R3-09 [confirmed, minor, security] review-gate fork makes severity decide 'clean' but discards the verifiers' severityAdjustment, so an under-rated confirmed finding never blocks

- **Місце:** `.claude/workflows/review-gate.js:125`
- **Доказ:** VERDICT_SCHEMA asks each verifier for severityAdjustment (keep, upgrade or downgrade; line 42). The Verify phase returns `{ ...f, verdict, verifierNotes }` (line 116) and drops it. Line 125 then decides blocking from the finder's own `f.severity`. Before ADR-0003, severity did not affect `clean`; now it is the gate criterion, and it is the one attribute nobody verifies. Scenario: a finder rates a real defect 'minor', as happened with R2-06 and R2-08, and both verifiers vote 'upgrade'. The finding still goes to the backlog, `clean` becomes true, and scripts/check-trajectory.mjs:80 lets the slice archive because it reads only `clean === true`. check-trajectory also ignores the recorded `blockingSeverities`, so a run with `args.blockingSeverities = ['critical']` or `[]` produces an archivable `clean: true` as well.
- **Пропозиція:** Keep the verifier votes in the result, e.g. as `severityVotes`. Compute an effective severity from them: an 'upgrade' from a non-refuting verifier raises it one step, or at least makes an upgraded minor finding count as blocking. Use that severity in the blocking/backlog split and in `backlogTitles`. Make check-trajectory fail when review-findings.json lacks 'critical' and 'major' in `blockingSeverities`, so ADR-0003's default cannot be lowered per run without a visible failure.

## R3-10 [confirmed, minor, security] review-round-2.md adds the owner's local username and the company name through scratchpad paths, against the 2026-09-30 AGENTS.md boundary rule

- **Місце:** `openspec/changes/add-input/review-round-2.md:27`
- **Доказ:** Lines 27, 33 and 39 cite 'Probe script: <скретчпад сесії>' with the real username and company name. The AGENTS.md Boundaries section (owner decision, 2026-09-30) says new texts must not add the company name or people's names beyond what the target library's code requires. The reason given is that the repo carries company-sensitive data and is published only as a de-personalized export that the owner reviews. review-round-1.md has no such paths. The paths also point into a session scratchpad that no later reader can open, so they do not work as evidence pointers. Nothing is pushed, so the impact is extra work for the export review.
- **Пропозиція:** Replace the three paths with a neutral '<scratchpad>/r2sec/<script>.py'. If the probe scripts count as evidence, commit them under docs/qa/ and cite the repo path instead. Scrub the round-3 transcript the same way before committing it.

## R3-11 [confirmed, minor, spec-compliance] Fix 7.3 is incomplete: review-round-2.md, added in the same commit, contains 8 raw U+202E RIGHT-TO-LEFT OVERRIDE characters (the R2-03/R2-07/R2-09 Trojan-Source pattern again)

- **Місце:** `openspec/changes/add-input/review-round-2.md:18`
- **Доказ:** Decision 7.3 ("у design.md D9 буквальний U+202E замінено текстом `\u202e`") fixed design.md. A code-point scan of design.md, live.py, tasks.md, the ADR and the backlog finds no Cf/Cc characters.

But commit 21dc0f5 also added review-round-2.md with 8 raw U+202E characters: bytes E2 80 AE, count 8, no closing U+202C. They are on lines 18, 21, 22, 42, 45, 46, 66 and 67, e.g. "Replace the raw character with the literal text `<U+202E>` (backslash, u, 202e)". The transcript decoded the `\u202e` JSON escapes from review-findings.json into the raw character.

This file sits in the change folder that `openspec archive` keeps. All three round-2 findings suggested a lint step against Cf/bidi characters; it was not adopted, so nothing stops this from recurring.
- **Пропозиція:** Replace each raw U+202E in review-round-2.md with the six-character text `\u202e`, and keep escapes when transcribing findings. Add a check to `npm run lint`, e.g. a stdlib python pass over `git ls-files src tests openspec docs` that fails on Unicode Cf/Cc characters other than tab and newline.

## R3-12 [confirmed, minor, spec-compliance] R2-08 is only partly fixed: MAX_BODY_BYTES caps the bytes read, not memory. A stream of tiny chunks reached 949 MB, and a 206 reply with a 32 MB body reached 760 MB

- **Місце:** `src/method_sync/live.py:416`
- **Доказ:** The claims: live.py:41-44 says a server cannot make the client "тягнути в неї тіло до вердикту ліміту", and D8 quotes "піковий RSS процесу 66 МБ". That holds only for a 200 body sent without chunking. Probe 2026-09-30 (raw-socket server on 127.0.0.1, `live.fetch`, peak RSS from getrusage): an endless plain body was refused after 0.02 s at 62 MB.

Two paths still use about 20x the memory:

(a) A chunked stream of 2-byte chunks. `response.read(MAX_BODY_BYTES + 1)` gives http.client `_read_chunked` a 32 MB `amt`, and `_read_chunked` keeps one bytes object per chunk. Peak RSS was 563 MB with a 3 s limit and 949 MB with the real 15 s limit. The cap was never reached, so the call ended with «перевищено ліміт 15 с».

(b) A 2xx status other than 200, e.g. 206 with 32 MB of "ab ab …". `_open_and_read` reads up to the cap. `_status_reason` (line 435) then runs `_server_text` → `" ".join(text.split())` over the whole decoded body before cutting it to 200 characters: 760 MB in 0.43 s. The HTTPError branch reads only EXCERPT_BYTES. This path existed before the fix and was unbounded then.

The peak is bounded near 1 GB and needs a hostile server, so this is minor. On a small machine the resulting MemoryError would still leave `_within_limit` as a fourth exception class.
- **Пропозиція:** Read the body in fixed-size pieces: `buf = bytearray(); limit = MAX_BODY_BYTES + 1 if response.status == 200 else EXCERPT_BYTES; while len(buf) < limit: piece = response.read(min(65536, limit - len(buf))); if not piece: break; buf += piece`. Keep the IncompleteRead check for status 200.

I patched this into a probe process only, not the repo:
- 15 s tiny-chunk stream: 101 MB, refused with «тіло більше за 32 МБ» after 12 s;
- 206 case: 94 MB;
- Content-Length 100 with a 20-byte body: still IncompleteRead.

Add a regression test that streams tiny chunks against a lowered cap, and change D8's 66 MB claim to say which encoding it applies to.

## R3-13 [confirmed, minor, spec-compliance] The stated reason for the 32 MB cap is wrong: Binance REST bodies reach megabytes, so 32 MB is about 29x the largest one, not "thousands of times"

- **Місце:** `src/method_sync/live.py:42`
- **Доказ:** live.py:42 says "Тіло REST Binance важить кілобайти, тож 32 МБ у тисячі разів більше за будь-яке". design.md:122-123 and tasks.md:194 (7.6) say "у тисячі разів більше за будь-яку відповідь REST Binance".

Measured with curl on public endpoints, 2026-09-30:
- /fapi/v1/exchangeInfo: 1,141,820 bytes;
- /fapi/v1/ticker/24hr: 292,469 bytes;
- /fapi/v1/premiumIndex without symbol: 204,573 bytes.

`live.capture` on exchangeInfo wrote a 2,030,005-byte fixture. So 32 MiB is about 29x the largest known body. The cap still works, but the reasoning is off by two orders of magnitude.
- **Пропозиція:** Reword the three places with the measured number, e.g. "≈30× найбільшої відомої відповіді (`/fapi/v1/exchangeInfo`, 1,1 МБ, проба 2026-09-30)".

## R3-14 [confirmed, minor, spec-compliance] ADR-0003 was not carried into the slice's process files: tasks 5.6 still says fix every confirmed finding, current-state.md is stale, and the backlog has no dates

- **Місце:** `openspec/changes/add-input/tasks.md:99`
- **Доказ:** Coverage (module level, unchanged by this diff): 34 scenarios: 28 implemented, 4 partial, 2 missing, 0 contradicted.
- The 2 missing are registry "Без --registry прогін не починається" and live "Недоступна відповідь не чіпає бібліотеку" (FR-27).
- The 4 partial are stderr without a traceback, exit code 1 on a failed fixture write, the runner request for FR-30, and the brief text for FR-30.
- design.md «Покриття сценаріїв» and tasks 6.10, 6.11 and 6.13 hand all six to add-run-cli, add-field-verification and add-sync-loop-and-report.

Ticked tasks 7.1-7.6 all have artifacts: ContainmentR2, SerializationDepthR2, ProxyConnectR2, BodySizeCapR2, and D9 without the raw character. Checks run: 86 tests OK (3 skipped), METHOD_SYNC_LIVE=1 LiveExchange OK, `openspec validate add-input --strict` valid, check:trace PASS, and a mini smoke against fapi.binance.com (premiumIndex fixture with 8 keys, NOSUCHSYMBOL gives 400, fundingRate [] leaves no fixture).

The drift from ADR-0003 (accepted in fbe69d2):
1. tasks.md 5.6 (line 99) must be ticked before archive, yet it says "Виправити кожну підтверджену знахідку, а також спірну…". That contradicts 7.7 and ADR-0003, which send minor findings to the backlog.
2. AGENTS.md says "Онови docs/current-state.md при кожній віхі (… ADR прийнято)". docs/current-state.md still shows 2026-09-30 10:46, Phase 3, "Active change: none" and "Current test expectation: 12 tests".
3. ADR-0003:20 wants backlog rows "з місцем і датою". docs/qa/review-backlog.md has no date column and names files without line numbers.
- **Пропозиція:** 1. Reword 5.6 to the ADR-0003 rule: fix confirmed and contested critical/major findings, move the rest to docs/qa/review-backlog.md, and read `clean: true` as "no blocking findings".
2. Update docs/current-state.md (Phase 4, active change add-input, ADR-0003, review round 3 pending), with evidence pointers.
3. Add date and line columns to review-backlog.md.

## R3-15 [confirmed, minor, spec-compliance] New texts written after the 2026-09-30 naming rule add a person's name and company-bearing paths

- **Місце:** `docs/adr/ADR-0003-review-gate-blocking-severity.md:5`
- **Доказ:** The AGENTS.md Boundaries rule (commit 69d5df3, 2026-09-30 13:10) says: "У нових текстах не додавати назв компанії, її внутрішніх систем і людей понад те, що вимагає код цільової бібліотеки".

Two texts in this diff were written after that rule:
- ADR-0003:5 reads "Deciders: власник (Andrii Kutil)".
- review-round-2.md:27, :33 and :39 cite probe scripts at `<скретчпад сесії>`. These paths carry the user and company names and point into a session scratchpad that later readers cannot open, so they are dead evidence links.

Neither is required by target-library code.
- **Пропозиція:** Write "власник" without the name in ADR-0003. In review-round-2.md, replace the scratchpad paths with a neutral note ("probe scripts not kept"), or commit the probes under docs/qa/ if they are meant as evidence.

## R3-16 [contested, major, spec-compliance] review-gate fork decides blocking from the finder's unverified severity; the verifiers' severityAdjustment is collected but thrown away, so a critical or major filed as minor goes to the backlog

- **Місце:** `.claude/workflows/review-gate.js:125`
- **Доказ:** ADR-0003 defines clean as "немає підтверджених чи спірних знахідок блокуючої серйозності". Its chosen option also claims "критичне все одно блокує".

What the code does:
- VERDICT_SCHEMA (line 42) asks each verifier for `severityAdjustment: keep|upgrade|downgrade`.
- The vote reducer (line 116) keeps only `refuted` and `reasoning`. `grep severityAdjustment` finds no other use.
- Lines 125-126 split blocking from backlog on `f.severity`, the label of the single finder.
- Dedup (line 94) keeps whichever duplicate arrived first, together with its severity.

This slice's own record shows the label is noisy. The same containment bypass was filed as R2-01 [major, correctness] and R2-10 [minor, visual/security] (review-round-2.md). Under this fork, if only the R2-10 finder had seen it, a confirmed write outside runs/ (principle VII) would have gone to the backlog, and a verifier upgrade vote could not have stopped that. The reverse also holds: a nit the verifiers downgrade still blocks and costs a review round, which is the cost ADR-0003 set out to avoid.

The second weakness: `blockingSeverities` comes straight from args (line 52) with no validation. `[]` or a typo like `['Major']` makes every review `clean: true`. check-trajectory.mjs:80 and check-process-ratchet.mjs:286 read only `clean`, so this weakening passes the hard-locked gates unseen. Only the evidence file records it.
- **Пропозиція:** 1. Compute an effective severity per finding: the finder's severity moved by the verifiers' majority severityAdjustment, or at least the max of the finder's severity and any verifier upgrade.
2. Use the effective severity for the blocking/backlog split, and persist it with the votes in review-findings.json.
3. On dedup, keep the highest severity.
4. Validate `blockingSeverities`: it must be a non-empty subset of the schema enum that contains 'critical'. Otherwise fall back to the default and log it.
5. Amend ADR-0003 to say whose severity decides blocking.

