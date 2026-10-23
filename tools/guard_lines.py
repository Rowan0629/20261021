"""列出程式裡四段防護各自的開始與結束行號，並檢查成對、編號齊全。

用法：uv run python tools/guard_lines.py
行號會隨程式修改而移動；改完程式後重跑一次，再更新 README.md 裡的表格。
"""

import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "troupe_bot"
START = re.compile(r"# ==== 防護 (\d)：(.+?)　開始 ====")
END = re.compile(r"# ==== 防護 (\d) 結束 ====")


def scan() -> dict[int, dict]:
    found: dict[int, dict] = {}
    for path in sorted(SRC.glob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if m := START.search(line):
                found.setdefault(int(m[1]), {})["name"] = m[2]
                found[int(m[1])].update(file=path.name, start=number)
            elif m := END.search(line):
                found.setdefault(int(m[1]), {})["end"] = number
    return found


def main() -> int:
    found = scan()
    problems = []
    for n in range(1, 5):
        g = found.get(n)
        if not g or "start" not in g or "end" not in g:
            problems.append(f"防護 {n} 缺少開始或結束標記")
        elif g["end"] <= g["start"]:
            problems.append(f"防護 {n} 的結束在開始之前")
        else:
            print(f"防護 {n}：{g['name']}　{g['file']} 第 {g['start']}–{g['end']} 行")
    extra = sorted(set(found) - {1, 2, 3, 4})
    if extra:
        problems.append(f"出現多餘的防護編號：{extra}")
    for p in problems:
        print("問題：", p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
