"""Smoke слайсу add-input на справжніх входах (tasks.md 5.7).

Драйвер оркестратора, а не тест: ганяє справжні registry.load і live.capture проти реєстру method-sync v1,
одноразової копії бібліотеки і живої біржі; виходить із ненульовим кодом на першій розбіжності.
Запуск: cd /tmp && PYTHONPATH=<корінь репо>/src python3 <корінь репо>/docs/qa/smoke/add-input/driver.py
"""
import hashlib
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[4]
SANDBOX = REPO / ".sandbox" / "binancefutures"
V1_REGISTRY = REPO.parent / "method-sync" / "registry.toml"
HERE = pathlib.Path(__file__).resolve().parent

from method_sync import live, registry  # noqa: E402


def check(ok, what):
    print(("OK    " if ok else "FAIL  ") + what)
    if not ok:
        sys.exit(1)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


print(f"repo={REPO}\ncwd={pathlib.Path.cwd()}")
runs_existed = live.RUNS_DIR.exists()

# 1. Копія бібліотеки — git-репозиторій; стан до smoke.
git_dir = subprocess.run(["git", "-C", str(SANDBOX), "rev-parse", "--git-dir"], capture_output=True, text=True)
check(git_dir.returncode == 0, f"1. {SANDBOX} — git-репозиторій")
status_before = subprocess.run(["git", "-C", str(SANDBOX), "status", "--porcelain"], capture_output=True,
                               text=True).stdout

# 2. Реєстр v1 з lib, переведеним на копію.
with tempfile.TemporaryDirectory() as tmp:
    text = V1_REGISTRY.read_text(encoding="utf-8")
    lines = [f'lib = "{SANDBOX}"' if line.startswith("lib = ") else line for line in text.splitlines()]
    reg_file = pathlib.Path(tmp, "registry.toml")
    reg_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    reg = registry.load(reg_file)
check(reg.verify_cmd == "mvn -q -DskipTests test-compile", "2. verify_cmd з реєстру v1")
check(reg.base_url == "https://fapi.binance.com", "2. base_url")
check(reg.status == "active" and reg.credentials is None, "2. status=active, credentials=None")
paths = [m.path for m in reg.methods]
check(paths == ["/fapi/v1/premiumIndex", "/fapi/v1/fundingRate"], f"2. методи {paths}")
check(reg.methods[0].args == {"symbol": "BTCUSDT"} and reg.methods[0].call is None, "2. premiumIndex args, без call")
check(reg.methods[1].args == {"symbol": "BTCUSDT", "limit": 3}
      and reg.methods[1].call == '"BTCUSDT", 3, null, null', "2. fundingRate args і call")

# 3. Недосяжна адреса: LiveUnavailable, фікстури немає.
fixture = live.RUNS_DIR / "fapi-v1-premiumIndex" / "fixture.json"
check(not fixture.exists(), f"3. {fixture} до smoke немає")
try:
    live.capture("http://127.0.0.1:9", "/fapi/v1/premiumIndex", {"symbol": "BTCUSDT"})
    check(False, "3. недосяжна адреса мала кинути LiveUnavailable")
except live.LiveUnavailable as error:
    message = str(error)
    print(f"      {message}")
    check("жива відповідь недоступна" in message
          and "http://127.0.0.1:9/fapi/v1/premiumIndex?symbol=BTCUSDT" in message, "3. повідомлення з URL і причиною")
check(not fixture.exists(), "3. фікстури після недоступного виклику немає")

# 4. Жива біржа: фікстура з 8 ключами.
written = live.capture(reg.base_url, "/fapi/v1/premiumIndex", {"symbol": "BTCUSDT"})
check(pathlib.Path(written) == fixture and fixture.is_file(), f"4. фікстуру записано: {written}")
import json  # noqa: E402

data = json.loads(fixture.read_text(encoding="utf-8"))
keys = sorted(data["body"])
print(f"      keys={keys}")
check(data["http_status"] == 200 and data["path"] == "/fapi/v1/premiumIndex"
      and data["args"] == {"symbol": "BTCUSDT"}, "4. http_status, path, args")
check(keys == ["estimatedSettlePrice", "indexPrice", "interestRate", "lastFundingRate", "markPrice",
               "nextFundingTime", "symbol", "time"], "4. рівно 8 ключів premiumIndex")
digest = sha(fixture)

# 5. Два невдалі виклики не чіпають наявної фікстури.
for base, args, marker in (("http://127.0.0.1:9", {"symbol": "BTCUSDT"}, "недоступна"),
                           (reg.base_url, {"symbol": "NOSUCHSYMBOL"}, "400")):
    try:
        live.capture(base, "/fapi/v1/premiumIndex", args)
        check(False, f"5. {base} {args} мав кинути LiveUnavailable")
    except live.LiveUnavailable as error:
        print(f"      {error}")
        check(marker in str(error), f"5. {args['symbol']}: у повідомленні «{marker}»")
check(sha(fixture) == digest, "5. SHA-256 фікстури не змінився")

# 6. Порожній масив від біржі — недоступна відповідь, фікстури fundingRate немає.
funding_fixture = live.RUNS_DIR / "fapi-v1-fundingRate" / "fixture.json"
try:
    live.capture(reg.base_url, "/fapi/v1/fundingRate", {"symbol": "NOSUCHSYMBOL", "limit": 3})
    check(False, "6. [] мав дати LiveUnavailable")
except live.LiveUnavailable as error:
    print(f"      {error}")
    check("немає жодного ключа" in str(error), "6. «немає жодного ключа»")
check(not funding_fixture.exists(), "6. фікстури fundingRate немає")

# 7. Копія бібліотеки не змінилась.
status_after = subprocess.run(["git", "-C", str(SANDBOX), "status", "--porcelain"], capture_output=True,
                              text=True).stdout
check(status_after == status_before, "7. git status копії бібліотеки той самий")

# 8. Доказ — у docs/qa/smoke, runs/ прибрати за собою.
shutil.copyfile(fixture, HERE / "fixture.json")
shutil.rmtree(fixture.parent)
if not runs_existed and live.RUNS_DIR.exists() and not any(live.RUNS_DIR.iterdir()):
    live.RUNS_DIR.rmdir()
check((HERE / "fixture.json").is_file(), "8. фікстура скопійована в docs/qa/smoke/add-input/")
print("SMOKE PASS")
