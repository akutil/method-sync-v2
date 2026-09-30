# Missing gate candidate: e2e

> AUTO-DRAFTED by check-acceptance-methods --mode=existence. A requirement
> declares this acceptance method but no real mechanism exists. Implement the
> mechanism (or obtain a human waiver under docs/qa/waivers/) before Phase 4.

- Method: e2e
- Declared by: FR-15, FR-18, FR-23, FR-26, FR-27, FR-33, FR-34, FR-36, FR-39, FR-42, FR-44, FR-46, FR-51, FR-53, FR-56, FR-57, FR-58, FR-63, FR-69, FR-70, FR-73, FR-77, FR-79, FR-81, FR-93, NFR-6, NFR-8, NFR-9, NFR-10, NFR-15
- Threshold: n/a (default — none parsed from text)
- Reference URL: https://fapi.binance.com , https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=3 , https://fapi.binance.com/fapi/v1/tradingSchedule , http:// , https:// , https://fapi.binance.invalid , http://127.0.0.1:9 , https://fapi.binance.com/fapi/v1/fundingRate?symbol=NOSUCHSYMBOL&limit=3 , https://fapi.binance.invalid/fapi/v1/premiumIndex?symbol=BTCUSDT , https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT , https://nonexistent.invalid
- Breakpoints: TODO (e.g. 1440x900, 390x844)
- Masks: TODO (dynamic regions to exclude)
- Expected mechanism: npm script one of [test:e2e] or file matching [playwright.config.ts, playwright.config.js, playwright.config.mjs]
- Expected artifact: docs/qa/e2e-report.md
