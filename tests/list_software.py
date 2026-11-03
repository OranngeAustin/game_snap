"""List the software installed on this computer, for GameSnap's not-a-game list. Read-only.
Sources:
- uninstall entries in the registry (HKLM 64/32-bit, HKCU): name, publisher, folder, the exe its icon
  points at, and the .exe files at the top of its folder;
- Start Menu and desktop shortcuts (all users and this user): target exe (Squirrel apps: the exe after
  --processStart);
- packaged apps (Get-AppxPackage, not frameworks or system packages): Application Executable from each
  AppxManifest.xml, plus Get-StartApps names;
- process names of the programs with a visible window right now (names only, no window titles);
- game libraries, so games can be told apart: Steam libraries (steamapps\\common), Epic manifests, and
  the .exe names found up to 4 levels under known game folders.
Writes <out>.json (everything) and <out>.txt (readable).
Run it outside the Claude app's container (the Start Menu folder is under %APPDATA%), and write the output
outside the project, e.g. under %TEMP%: it lists the names of the user's own programs and shortcuts.

usage: python -X utf8 tests\\list_software.py <out path without extension>
"""
import ctypes
import ctypes.wintypes as wt
import json
import re
import subprocess
import sys
import winreg
from pathlib import Path

import win32com.client

OUT = Path(sys.argv[1])
shell = win32com.client.Dispatch("WScript.Shell")
NO_WINDOW = subprocess.CREATE_NO_WINDOW
UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
GAME_ROOTS = [r"D:\games", r"D:\miHoYo Launcher", r"C:\XboxGames", r"D:\XboxGames", r"C:\Program Files\Epic Games",
              r"D:\Epic Games", r"C:\Riot Games", r"D:\Riot Games", r"D:\WeGameApps", r"C:\WeGameApps",
              r"C:\Program Files\HoYoPlay", r"D:\HoYoPlay"]


def exe_of(value: str) -> str | None:
    """'"C:\\x\\y.exe",0' -> 'C:\\x\\y.exe'; None when it is not an .exe."""
    v = (value or "").strip()
    if v.startswith('"'):
        v = v[1:].split('"', 1)[0]
    else:
        v = v.split(",", 1)[0].strip()
    return v if v.lower().endswith(".exe") else None


def exes_under(folder: Path, depth: int) -> list[str]:
    found: list[str] = []
    try:
        for p in folder.iterdir():
            if p.is_file() and p.suffix.lower() == ".exe":
                found.append(str(p))
            elif p.is_dir() and depth > 1:
                found.extend(exes_under(p, depth - 1))
    except OSError:
        pass
    return found


def uninstall_entries() -> list[dict]:
    rows = []
    views = [(winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY, "HKLM64"),
             (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY, "HKLM32"), (winreg.HKEY_CURRENT_USER, 0, "HKCU")]
    for hive, view, label in views:
        try:
            root = winreg.OpenKey(hive, UNINSTALL, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        with root:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                vals: dict = {}
                try:
                    with winreg.OpenKey(root, sub) as k:
                        for name in ("DisplayName", "Publisher", "InstallLocation", "DisplayIcon",
                                     "SystemComponent", "ParentKeyName", "ReleaseType"):
                            try:
                                vals[name] = winreg.QueryValueEx(k, name)[0]
                            except OSError:
                                pass
                except OSError:
                    continue
                if (not vals.get("DisplayName") or vals.get("SystemComponent") == 1 or vals.get("ParentKeyName")
                        or vals.get("ReleaseType") in ("Update", "Hotfix", "Security Update")):
                    continue
                loc = (vals.get("InstallLocation") or "").strip().strip('"')
                top = [Path(p).name for p in exes_under(Path(loc), 1)] if loc and Path(loc).is_dir() else []
                rows.append({"view": label, "key": sub, "name": vals["DisplayName"],
                             "publisher": vals.get("Publisher", ""), "location": loc,
                             "icon_exe": exe_of(vals.get("DisplayIcon", "")), "top_exes": sorted(top)})
    return rows


def shortcuts() -> list[dict]:
    rows = []
    for special in ("AllUsersPrograms", "Programs", "Desktop", "AllUsersDesktop"):
        root = Path(str(shell.SpecialFolders(special)))
        if not root.is_dir():
            continue
        for p in root.rglob("*.lnk"):
            try:
                lnk = shell.CreateShortcut(str(p))
                target, args = str(lnk.TargetPath), str(lnk.Arguments)
            except Exception as e:
                target, args = f"(error {e})", ""
            m = re.search(r'--processStart\s+"?([^"\s]+\.exe)', args, re.I)
            rows.append({"where": special, "lnk": str(p.relative_to(root)), "target": target, "args": args,
                         "squirrel_exe": m.group(1) if m else None})
    return rows


def powershell_json(command: str):
    res = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + command],
                         capture_output=True, creationflags=NO_WINDOW)
    text = res.stdout.decode("utf-8", "replace").strip()
    data = json.loads(text) if text else []
    return data if isinstance(data, list) else [data]


def packaged_apps() -> list[dict]:
    rows = []
    pkgs = powershell_json("Get-AppxPackage | Where-Object { -not $_.IsFramework -and $_.SignatureKind -ne 'System' }"
                           " | Select-Object Name, InstallLocation, SignatureKind | ConvertTo-Json")
    for pkg in pkgs:
        exes: list[str] = []
        try:
            text = (Path(pkg.get("InstallLocation") or "") / "AppxManifest.xml").read_text(encoding="utf-8")
            exes = re.findall(r'<Application\b[^>]*?\bExecutable="([^"]+)"', text)
        except OSError:
            pass
        rows.append({"name": pkg.get("Name"), "signature": pkg.get("SignatureKind"),
                     "location": pkg.get("InstallLocation"), "exes": exes})
    return rows


def start_apps() -> list[dict]:
    return powershell_json("Get-StartApps | Select-Object Name, AppID | ConvertTo-Json")


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                ("szExeFile", wt.WCHAR * 260)]


def windowed_processes() -> list[str]:
    k32, u32 = ctypes.WinDLL("kernel32"), ctypes.WinDLL("user32")
    k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    k32.Process32FirstW.argtypes = k32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.CloseHandle.argtypes = [wt.HANDLE]
    u32.IsWindowVisible.argtypes = u32.GetWindowTextLengthW.argtypes = [wt.HWND]
    u32.GetWindow.argtypes, u32.GetWindow.restype = [wt.HWND, wt.UINT], wt.HWND
    u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    names: dict[int, str] = {}
    snap = k32.CreateToolhelp32Snapshot(2, 0)
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    ok = k32.Process32FirstW(snap, ctypes.byref(entry))
    while ok:
        names[entry.th32ProcessID] = entry.szExeFile
        ok = k32.Process32NextW(snap, ctypes.byref(entry))
    k32.CloseHandle(snap)
    found: set[str] = set()
    proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def visit(hwnd, _):
        if u32.IsWindowVisible(hwnd) and not u32.GetWindow(hwnd, 4) and u32.GetWindowTextLengthW(hwnd) > 0:
            pid = wt.DWORD()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in names:
                found.add(names[pid.value])
        return True

    u32.EnumWindows(proc(visit), 0)
    return sorted(found, key=str.lower)


def game_libraries() -> dict:
    steam_games: list[dict] = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            steam = Path(winreg.QueryValueEx(k, "SteamPath")[0])
        vdf = (steam / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="replace")
        libs = {Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', vdf)} | {steam}
        for lib in libs:
            common = lib / "steamapps" / "common"
            if common.is_dir():
                for game in common.iterdir():
                    if game.is_dir():
                        steam_games.append({"library": str(lib), "folder": game.name,
                                            "exes": sorted({Path(e).name for e in exes_under(game, 4)})})
    except OSError as e:
        steam_games.append({"error": str(e)})
    epic: list[dict] = []
    for item in Path(r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests").glob("*.item"):
        try:
            d = json.loads(item.read_text(encoding="utf-8", errors="replace"))
            epic.append({"name": d.get("DisplayName"), "location": d.get("InstallLocation"),
                         "exe": d.get("LaunchExecutable")})
        except (OSError, ValueError):
            pass
    roots = {r: sorted({Path(e).name for e in exes_under(Path(r), 4)}) for r in GAME_ROOTS if Path(r).is_dir()}
    return {"steam": steam_games, "epic": epic, "game_roots": roots}


data = {"uninstall": uninstall_entries(), "shortcuts": shortcuts(), "packaged": packaged_apps(),
        "start_apps": start_apps(), "windowed_now": windowed_processes(), "games": game_libraries()}
OUT.with_suffix(".json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

lines: list[str] = []
lines.append(f"== uninstall entries ({len(data['uninstall'])})")
for r in sorted(data["uninstall"], key=lambda r: r["name"].lower()):
    exe = Path(r["icon_exe"]).name if r["icon_exe"] else "-"
    lines.append(f"{r['name']} | {r['publisher']} | icon:{exe} | {r['location']} | top:{','.join(r['top_exes'][:12])}")
lines.append(f"\n== shortcuts ({len(data['shortcuts'])})")
for r in sorted(data["shortcuts"], key=lambda r: r["lnk"].lower()):
    target = r["squirrel_exe"] or r["target"]
    lines.append(f"[{r['where']}] {r['lnk']} -> {target}" + (f"  args:{r['args'][:80]}" if r["args"] else ""))
lines.append(f"\n== packaged apps ({len(data['packaged'])})")
for r in sorted(data["packaged"], key=lambda r: (r["name"] or "").lower()):
    lines.append(f"{r['name']} | {r['signature']} | {','.join(r['exes'])}")
lines.append(f"\n== start apps ({len(data['start_apps'])})")
for r in data["start_apps"]:
    lines.append(f"{r.get('Name')} | {r.get('AppID')}")
lines.append("\n== windowed processes now: " + ", ".join(data["windowed_now"]))
g = data["games"]
lines.append(f"\n== steam games ({len(g['steam'])})")
for r in g["steam"]:
    lines.append(f"{r.get('folder')} | {','.join(r.get('exes', []))}" if "folder" in r else str(r))
lines.append(f"\n== epic games ({len(g['epic'])})")
for r in g["epic"]:
    lines.append(f"{r['name']} | {r['exe']} | {r['location']}")
lines.append("\n== exes under game folders")
for root, exes in g["game_roots"].items():
    lines.append(f"{root}: {', '.join(exes)}")
OUT.with_suffix(".txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
