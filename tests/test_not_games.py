"""Sanity checks for not_games.py: every name well-formed, and no game, emulator or runtime of this PC
blocked. Given the software.txt that list_software.py writes, it also lists the THIS_PC names that do not
appear there verbatim (typos, or names inferred from a product rather than seen as a file).

usage: python -X utf8 tests\\test_not_games.py [software.txt]
"""
import re
import sys
from pathlib import Path

project = Path(__file__).resolve().parent.parent
software = Path(sys.argv[1]) if len(sys.argv) > 1 else None
sys.path.insert(0, str(project))
import config  # noqa: E402
import not_games  # noqa: E402

fails = 0


def check(ok, msg):
    global fails
    print(("PASS " if ok else "FAIL ") + msg)
    fails += not ok


ng = not_games.NOT_GAMES
check(ng == not_games.GENERAL | not_games.THIS_PC, "NOT_GAMES is GENERAL | THIS_PC")
bad_form = sorted(n for n in ng if n != n.lower() or not n.endswith(".exe") or n != n.strip() or "\\" in n)
check(not bad_form, f"all lowercase, *.exe, no paths/whitespace {bad_form}")
dup = sorted(not_games.GENERAL & not_games.THIS_PC)
check(not dup, f"no name in both GENERAL and THIS_PC {dup}")

# 游戏、模拟器、运行环境：一个都不能拦
games_here = {
    # Steam
    "3dmark.exe", "a bird story.exe", "amtrucks.exe", "olivia.exe", "cities.exe", "dontstarve_steam.exe",
    "dontstarve_steam_x64.exe", "dspgame.exe", "eurotrucks2.exe", "finding paradise.exe", "frostpunk.exe",
    "ittakestwo.exe", "ittakestwo_trial.exe", "littlenightmares.exe", "oriwotw.exe", "oride.exe",
    "overcooked.exe", "overcooked2.exe", "rail route.exe", "railwayempire.exe", "terraria.exe",
    "to the moon.exe", "sigcorp minisode 2.exe", "siggy - holiday special.exe",
    "to the moon - sigmund minisode 1.exe", "to the moon - sigmund minisode 2.exe", "transportfever2.exe",
    "gaiaswentry.exe",
    # Xbox / 商店
    "forzahorizon4.exe", "minecraft.exe", "gamelaunchhelper.exe", "solitairecasualgamesstub.exe",
    # 模拟器、米哈游
    "yuzu.exe", "yuzu-cmd.exe", "yuanshen.exe", "genshinimpact.exe", "genshin impact cloud game.exe",
    "starrail.exe", "zenlesszonezero.exe", "bh3.exe",
}
games_here |= {k.lower() for k in config.DEFAULTS["games"]}
runtimes = {
    "python.exe", "pythonw.exe", "java.exe", "javaw.exe", "node.exe", "dotnet.exe", "mono.exe", "nw.exe",
    "electron.exe", "game.exe", "start.exe", "main.exe", "qtwebengineprocess.exe", "unitycrashhandler64.exe",
    "crashreport.exe", "dock.exe", "ui32.exe", "rundll32.exe", "dllhost.exe",
}
check(not (ng & games_here), f"no game/emulator blocked {sorted(ng & games_here)}")
check(not (ng & runtimes), f"no runtime/generic name blocked {sorted(ng & runtimes)}")
launchers = {x.lower() for x in config.DEFAULTS.get("launchers", [])}
print(f"info: default launchers also blocked by name: {sorted(ng & launchers)}")

# THIS_PC 里的名字应该都能在本机软件清单里找到（防止手误）
if software:
    text = software.read_text(encoding="utf-8").lower()
    missing = sorted(n for n in not_games.THIS_PC
                     if not re.search(r"(?<![\w.+-])" + re.escape(n) + r"(?![\w.-])", text))
    print(f"info: THIS_PC names not found verbatim in software.txt ({len(missing)}): {missing}")
print(f"info: sizes GENERAL={len(not_games.GENERAL)} THIS_PC={len(not_games.THIS_PC)} total={len(ng)}")
print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
