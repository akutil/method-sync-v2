## 1. Залежності

- [x] 1.1 Нових залежностей немає (stdlib).

## 2. Тести першими (червоні)

- [x] 2.1 `test-engineer` пише тести з п'яти дельта-специфікацій (з опорою на тести v1) до коду; кожен файл має `@trace`;
  прогін червоний з правильної причини.

## 3. Реалізація (зелена)

- [x] 3.1 `capability-implementer` переносить модулі v1 з відмінностями design.md до зеленого без правки тестів.
- [x] 3.2 Приклад `registry.toml` у корені.

## 4. Перевірка й архів

- [x] 4.1 `npm run lint`, `npm run test:run`, `npm run build`, `OPENSPEC_TELEMETRY=0 npx openspec validate --all --strict`.
- [x] 4.2 `npm run test:integration` (раннер проти `.sandbox/binancefutures` і живої біржі).
- [x] 4.3 Один `review-gate` (форк, ADR-0003) на весь новий код разом із кодом слайсу 1; виправити блокуючі.
- [x] 4.4 `npm run test:e2e` — доказовий прогін зі справжнім агентом; `docs/qa/e2e-report.md` → `Result: PASS`.
- [x] 4.5 `docs/current-state.md`; `OPENSPEC_TELEMETRY=0 npx openspec archive add-core --yes`; відновити базові специфікації;
  `validate --all --strict` і `check:trace` зелені.
