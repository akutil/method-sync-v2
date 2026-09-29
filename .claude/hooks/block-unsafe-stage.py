#!/usr/bin/env python3
"""Claude Code PreToolUse hook (Bash) — принцип VII конституції як гейт, а не як побажання.

Стейдж дозволено лише поіменними шляхами до файлів. Блокується:
  git add . | -A | --all | -u        -> гуртовий стейдж
  git add <каталог>                  -> те саме, лише written інакше
  git add <будь-що з секретом у назві>
  git commit -a / -am                -> стейдж в обхід поіменних шляхів

Чому саме так: `.gitignore` бібліотек-конекторів має негації, тому гуртовий стейдж затягує
свідомо untracked файли з реальними ключами акаунтів. AGENTS.md про це лише просить; хук —
забороняє, і працює в будь-якому режимі дозволів.

Помилка розбору входу -> тиша (exit 0): хук не має ламати роботу, а справжній стейдж секрету
ловиться ще й `permissions.deny` у settings.json.
"""
import json
import os
import re
import shlex
import sys

SECRET = re.compile(r"(config\.properties|\.env(\..+)?$|secret|credential|\.pem$|\.p12$|id_[rd]sa)", re.I)
BULK = {".", "-A", "--all", "-u", "--update", "*"}
COMMIT_ALL = re.compile(r"^-[a-zA-Z]*a[a-zA-Z]*$")
GIT_OPT_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}


def emit(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))


def segments(command):
    """Команду з && ; | розбити на окремі виклики, кожен — список слів."""
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
    out, cur = [], []
    for w in words:
        if w in ("&&", "||", ";", "|"):
            out.append(cur)
            cur = []
        else:
            cur.append(w)
    out.append(cur)
    return [s for s in out if s]


def split_git(words):
    """Слова після `git` -> (підкоманда, її аргументи, робочий каталог з -C).

    Глобальні опції git ідуть ДО підкоманди, і частина з них має власне значення
    (`git -C <шлях> add .`), яке не можна сплутати з підкомандою.
    """
    if "git" not in words:
        return None, [], None
    tail = words[words.index("git") + 1:]
    workdir, i = None, 0
    while i < len(tail):
        w = tail[i]
        if w in GIT_OPT_WITH_VALUE:
            if w == "-C" and i + 1 < len(tail):
                workdir = tail[i + 1]
            i += 2
            continue
        if w.startswith("-"):
            i += 1
            continue
        return w, tail[i + 1:], workdir
    return None, [], workdir


def verdict(words, cwd):
    sub, tail, workdir = split_git(words)
    if sub is None:
        return None
    cwd = workdir or cwd
    args = [w for w in tail if not w.startswith("-") or w in BULK or COMMIT_ALL.match(w)]

    if sub == "commit":
        if any(COMMIT_ALL.match(w) for w in tail if w.startswith("-") and not w.startswith("--")):
            return ("git commit -a стейдить усе відстежуване в обхід поіменних шляхів. "
                    "Додай потрібні файли `git add <шлях>` і закоміть без -a.")
        return None
    if sub != "add":
        return None

    paths = list(args)
    if not paths:
        return None
    for p in paths:
        if p in BULK:
            return (f"`git add {p}` — гуртовий стейдж. Принцип VII конституції: стейдж лише поіменними "
                    "шляхами до файлів, бо .gitignore бібліотек має негації і затягує untracked секрети.")
        if SECRET.search(p):
            return (f"`{p}` схожий на файл із секретами. Принцип VII: такі файли не читаються в контекст "
                    "і ніколи не стейдяться. Якщо це хибне спрацювання — стейдж робить людина.")
        if os.path.isdir(os.path.join(cwd, p)):
            return (f"`git add {p}` стейдить цілий каталог. Принцип VII: лише поіменні шляхи до файлів — "
                    f"перелічи їх (`git status --short {p}` покаже, що саме там нового).")
    return None


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    if payload.get("tool_name") != "Bash":
        return
    command = (payload.get("tool_input") or {}).get("command", "")
    cwd = payload.get("cwd") or os.getcwd()
    for words in segments(command):
        reason = verdict(words, cwd)
        if reason:
            emit(f"СТЕЙДЖ-ГЕЙТ: команда «{command}» спинена. {reason}")
            return


if __name__ == "__main__":
    main()
