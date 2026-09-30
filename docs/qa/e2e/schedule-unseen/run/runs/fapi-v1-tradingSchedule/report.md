# Звіт прогону — fapi-v1-tradingSchedule

- **Режим** (`mode`): refresh
- **Джерело параметрів запиту** (`request_source`): registry
- **Джерело моделі відповіді** (`response_source`): /Users/akutil/humex/method-sync-v2/runs/fapi-v1-tradingSchedule/fixture.json
- **Розходження до правки** (`mismatch`): зайві в моделі: —; бракує в моделі: —
- **Видалені поля** (`removed`): нічого не видалено
- **Команда перевірки** (`verify_cmd`): mvn -q -DskipTests test-compile
- **Результат перевірки** (`verify_result`): green
- **Ітерацій циклу** (`iterations`): 2
- **Висновок рецензента** (`reviewer`): не викликався — рецензію запускає окрема сесія (принцип V)
- **Лишилось на людину** (`left_to_human`): —
- **Значення енамів, яких бракувало (до правки)** (`enum_mismatch`): marketSchedules (com.example.binanceFutures.response.MarketType): FX
- **Оголошені константи, яких не було в живій відповіді (не видалено)** (`enum_unseen`): marketSchedules (com.example.binanceFutures.response.MarketType): ZZ_INVENTED — не видалено

Правка лишена некомічена в робочій копії цільової бібліотеки. Рішення про історію
репозиторію належить людині (принцип VI конституції).
