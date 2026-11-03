"""Print not_games.py as a grouped Markdown list (group = the comment line above each run of names).

usage: python -X utf8 tests\\list_not_games.py
"""
import re
from pathlib import Path

lines = (Path(__file__).resolve().parent.parent / "not_games.py").read_text(encoding="utf-8").splitlines()
current_set, groups = None, []
for line in lines:
    m = re.match(r"(\w+) = \{", line)
    if m:
        current_set = m.group(1)
        continue
    if line.startswith("}"):
        current_set = None
        continue
    if current_set is None:
        continue
    s = line.strip()
    if s.startswith("#"):
        title = s.lstrip("# ")
        if groups and groups[-1][0] == current_set and not groups[-1][2]:
            groups[-1][1] += title   # a comment that continues on the next line
        else:
            groups.append([current_set, title, []])
    else:
        groups[-1][2].extend(re.findall(r'"([^"]+)"', s))

total = 0
for set_name in ("GENERAL", "THIS_PC"):
    mine = [g for g in groups if g[0] == set_name]
    n = sum(len(g[2]) for g in mine)
    total += n
    print(f"\n**{set_name}（{n} 个）**\n")
    for _, title, names in mine:
        print(f"- {title}（{len(names)}）：" + "、".join(x.removesuffix(".exe") for x in names))
print(f"\ntotal {total}")
