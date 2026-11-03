"""Tests for naming yuzu screenshots after the game in its window title (main.emulator_game):
1. parsing, with window_title stubbed: EA titles with and without a version, the idle title, other games;
2. reading a real title across processes: a child holds a hidden window with a yuzu-style title and
   never pumps messages, so the read must not wait on it;
3. CaptureWorker._shot on such windows (running a game / idle in the game list): the name handed on
   to finish_shot, with the Capturer stubbed;
4. output.save_png with a name containing ':' (characters Windows forbids become '_').
Writes PNGs only into <run dir>. Exit code 1 if anything failed.

usage: python -X utf8 tests\\test_yuzu_naming.py <run dir>
"""
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT, RUN, FAKE = HERE.parent, Path(sys.argv[1]), HERE / "fake_window.py"
RUN.mkdir(parents=True, exist_ok=False)
sys.path.insert(0, str(PROJECT))
import main  # noqa: E402
import output  # noqa: E402
import watcher  # noqa: E402
from PIL import Image  # noqa: E402

failures: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {got!r}" + ("" if ok else f"  (want {want!r})"))
    if not ok:
        failures.append(label)


def fake_window(title: str) -> tuple[subprocess.Popen, int]:
    child = subprocess.Popen([sys.executable, str(FAKE), title, "20"], stdout=subprocess.PIPE,
                             text=True, encoding="utf-8")
    return child, int(child.stdout.readline())


print("== 1. parsing")
CASES = [
    ("yuzu Early Access 4167 | 塞尔达传说 王国之泪 | 1.2.1 | NVIDIA", "塞尔达传说 王国之泪"),
    ("yuzu Early Access 4167 | Mario Kart 8 Deluxe | AMD", "Mario Kart 8 Deluxe"),
    ("yuzu Early Access 4167", None),
    ("原神", None),
    ("", None),
    ("Other App | Some | Thing", None),
]
real_window_title = main.window_title
for title, want in CASES:
    main.window_title = lambda hwnd, t=title: t
    check(f"emulator_game({title!r})", main.emulator_game(1), want)
main.window_title = real_window_title

print("== 2. real window in another process")
ZELDA = "The Legend of Zelda: Tears of the Kingdom"
TITLE = f"yuzu Early Access 4167 | {ZELDA} | 1.2.1 | NVIDIA"
playing, playing_hwnd = fake_window(TITLE)
idle, idle_hwnd = fake_window("yuzu Early Access 4167")
check("child windows created", bool(playing_hwnd and idle_hwnd), True)
result: dict = {}


def read() -> None:
    t0 = time.perf_counter()
    result["title"] = watcher.window_title(playing_hwnd)
    result["ms"] = 1000 * (time.perf_counter() - t0)


reader = threading.Thread(target=read, daemon=True)
reader.start()
reader.join(5)
check("read returned within 5 s", "title" in result, True)
check("title read across processes", result.get("title"), TITLE)
print(f"      the read took {result.get('ms', -1):.3f} ms")
check("emulator_game(real window)", main.emulator_game(playing_hwnd), ZELDA)

print("== 3. CaptureWorker._shot")


class StubApp:
    def __init__(self, games: dict[int, str]) -> None:
        self.games, self.names = games, []

    def notify(self, *args, **kwargs) -> None:
        failures.append(f"notify{args}")

    def finish_shot(self, shot, game, when, t_key, rect) -> None:
        self.names.append(game)


class StubCapturer:
    def grab(self, hwnd: int, t_key: int) -> str:
        return "shot"


app = StubApp({playing.pid: "yuzu", idle.pid: "yuzu"})
worker = main.CaptureWorker(app)
worker._shot(StubCapturer(), 0, playing_hwnd, playing.pid)
worker._shot(StubCapturer(), 0, idle_hwnd, idle.pid)
worker.saver.shutdown(wait=True)
check("names passed to finish_shot (playing, idle)", app.names, [ZELDA, "yuzu"])
for child in (playing, idle):
    child.kill()
    child.wait()

print("== 4. save_png")
path = output.save_png(Image.new("RGB", (8, 8), (40, 120, 200)), RUN / "shots", ZELDA,
                       datetime(2026, 10, 31, 21, 30, 5), {"Software": "GameSnap test"})
check("folder", path.parent.name, "The Legend of Zelda_ Tears of the Kingdom")
check("file", path.name, "The Legend of Zelda_ Tears of the Kingdom_2026-10-31_21-30-05.png")
check("file exists", path.exists(), True)

print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
