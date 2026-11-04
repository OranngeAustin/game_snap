"""单实例的「请退出」信号和退出流程（02-findings M8）。

以前 Quit 事件和 Elevated 标记要等 App 建好、serve() 时才建：管理员新实例在这之前到达，OpenEventW 失败就放弃接管，
留下没有管理员权限的旧实例；信号在托盘进入消息循环之前到达时，icon.stop() 什么都不做、worker.join 对没启动的线程抛
RuntimeError，而 _quitting 已是 True：托盘照常出现，但不检测进程、不自动退出，托盘「退出」也点不动。现在检查：
1. 第一个实例一拿到互斥体就建好 Quit 事件（有管理员权限时还有 Elevated 标记），不等 serve()；
2. serve() 之前收到的退出信号不会丢，serve() 开始等时立即送到；
3. 接管时旧实例的 Quit 事件晚一点才出现：take_over 会重试几秒，而不是马上放弃；接管成功后本实例也建好自己的信号，
   旧信号残留的「已触发」状态被清掉（否则本实例一开始等就会把自己关掉）；
4. App：托盘就绪之后才通知外面（main 在这时才开始等退出信号）；_quit 中途出错（例如截图线程还没启动）也照样让托盘退出。
kernel32 换成按名字记命名对象的假实现，不建真的互斥体和事件，不影响正在运行的 GameSnap。
纯 Python，Windows 和 Linux（tests/winstubs.py 桩）都能跑。只在 <run dir> 里读写。Exit code 1 if anything failed.

usage: python -X utf8 tests/test_instance_quit.py <run dir>
"""
import ctypes
import json
import os
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT, RUN = HERE.parent, Path(sys.argv[1])
RUN.mkdir(parents=True, exist_ok=False)
os.environ["APPDATA"] = str(RUN / "appdata")   # config.APP_DIR 在 import 时就定了
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PROJECT))
import winstubs  # noqa: E402

winstubs.install()
import instance  # noqa: E402

failures: list[str] = []
WAIT_TIMEOUT = 0x102


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {got!r}" + ("" if ok else f"  (want {want!r})"))
    if not ok:
        failures.append(label)


# instance.py 用 ctypes.set_last_error / get_last_error 判断「已存在」：换成假 kernel32 自己记的值
LAST_ERROR = [0]
ctypes.set_last_error = lambda value: LAST_ERROR.__setitem__(0, value) or 0
ctypes.get_last_error = lambda: LAST_ERROR[0]


class FakeKernel32:
    """按名字记命名对象，只实现 instance.py 用到的函数。事件是自动复位的，和 instance.py 建的一样。"""

    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}
        self.handles: dict[int, dict] = {}
        self.calls: list[tuple[str, str]] = []
        self._next = 100

    def _handle(self, obj: dict) -> int:
        self._next += 4
        self.handles[self._next] = obj
        return self._next

    def _create(self, kind: str, name: str) -> int:
        self.calls.append((f"Create{kind}", name))
        if name in self.objects:
            LAST_ERROR[0] = instance.ERROR_ALREADY_EXISTS
        else:
            self.objects[name] = {"kind": kind, "name": name, "set": threading.Event(), "wait": instance.WAIT_OBJECT_0}
        return self._handle(self.objects[name])

    def CreateMutexW(self, sa, owner, name) -> int:
        return self._create("Mutex", name)

    def CreateEventW(self, sa, manual_reset, initial, name) -> int:
        return self._create("Event", name)

    def _open(self, kind: str, name: str) -> int:
        self.calls.append((f"Open{kind}", name))
        obj = self.objects.get(name)
        return self._handle(obj) if obj and obj["kind"] == kind else 0

    def OpenMutexW(self, access, inherit, name) -> int:
        return self._open("Mutex", name)

    def OpenEventW(self, access, inherit, name) -> int:
        return self._open("Event", name)

    def SetEvent(self, h) -> int:
        self.handles[h]["set"].set()
        return 1

    def ResetEvent(self, h) -> int:
        self.handles[h]["set"].clear()
        return 1

    def WaitForSingleObject(self, h, ms) -> int:
        obj = self.handles[h]
        if obj["kind"] == "Mutex":
            return obj["wait"]
        if obj["set"].wait(None if ms == instance.INFINITE else ms / 1000):
            obj["set"].clear()   # 自动复位
            return instance.WAIT_OBJECT_0
        return WAIT_TIMEOUT

    def CloseHandle(self, h) -> int:
        return 1

    def created(self, name: str) -> bool:
        return any(c[0].startswith("Create") and c[1] == name for c in self.calls)


print("== 1. 第一个实例一拿到互斥体就建好信号")
k = instance._k32 = FakeKernel32()
LAST_ERROR[0] = 0
first = instance.Instance(elevated=True)
check("是第一个实例", first.already_running, False)
check("还没 serve()，Quit 事件已经建好", k.created(instance.QUIT_EVENT_NAME), True)
check("还没 serve()，Elevated 标记已经建好", k.created(instance.ELEVATED_NAME), True)

print("== 2. serve() 之前收到的退出信号不会丢")
got_quit = threading.Event()
h = k.OpenEventW(instance.EVENT_MODIFY_STATE, False, instance.QUIT_EVENT_NAME)
check("新实例能打开 Quit 事件", bool(h), True)
if h:
    k.SetEvent(h)
first.serve(on_quit=got_quit.set)
check("serve() 后立即收到", got_quit.wait(2), True)

k = instance._k32 = FakeKernel32()
LAST_ERROR[0] = 0
plain = instance.Instance(elevated=False)
check("普通权限：建了 Quit 事件", k.created(instance.QUIT_EVENT_NAME), True)
check("普通权限：不建 Elevated 标记", k.created(instance.ELEVATED_NAME), False)

print("== 3. 接管：旧实例的 Quit 事件晚 0.5 秒才出现")
k = instance._k32 = FakeKernel32()
LAST_ERROR[0] = 0
k.CreateMutexW(None, True, instance.MUTEX_NAME)   # 旧实例（普通权限）已拿着互斥体，还没建 Quit 事件
LAST_ERROR[0] = 0
new = instance.Instance(elevated=True)
check("新实例看到已有实例在运行", new.already_running, True)
check("新实例不建 Quit 事件（那是旧实例的）", k.created(instance.QUIT_EVENT_NAME), False)
check("应该接管", new.should_take_over(), True)
late = threading.Timer(0.5, lambda: k.CreateEventW(None, False, False, instance.QUIT_EVENT_NAME))
late.start()
ok = new.take_over()
late.join()
check("重试后接管成功", ok, True)
check("接管后不再是「已在运行」", new.already_running, False)
quit_obj = k.objects.get(instance.QUIT_EVENT_NAME)
check("新实例建了自己的 Elevated 标记", k.created(instance.ELEVATED_NAME), True)
check("Quit 事件上残留的信号清掉了", quit_obj is not None and not quit_obj["set"].is_set(), True)
if quit_obj is not None:
    mine = threading.Event()
    new.serve(on_quit=mine.set)
    check("新实例 serve() 后不会把自己关掉", mine.wait(0.3), False)

print("== 4. App：托盘就绪后才通知外面；_quit 出错也让托盘退出")
import main  # noqa: E402
from config import Config  # noqa: E402

cfg_path = RUN / "config.json"
cfg_path.write_text(json.dumps({"games": {"FakeGame.exe": "假游戏"}, "toast": False, "sound": False,
                                "dualsense_quad": False, "save_dir": str(RUN / "shots")},
                               ensure_ascii=False), encoding="utf-8")
app = main.App(Config(cfg_path))


class StubIcon:
    icon = None
    title = ""
    visible = False

    def __init__(self) -> None:
        self.stopped = 0

    def update_menu(self) -> None:
        pass

    def stop(self) -> None:
        self.stopped += 1


class StubToast:
    def show(self, *a, **k) -> None:
        pass

    def stop(self) -> None:
        pass


icon = app.icon = StubIcon()
app.toast = StubToast()
app.watcher.start = lambda: None     # 不真的开进程检测、DualSense 线程
app.dualsense.start = lambda: None
ready_calls: list[int] = []
app.on_tray_ready = lambda: ready_calls.append(1)
check("建 App 时还没通知", ready_calls, [])
app._on_tray_ready(icon)
check("托盘就绪后通知了一次", ready_calls, [1])
try:
    app._quit(icon, None)   # 截图线程还没启动：worker.join 会抛 RuntimeError
    error = None
except Exception as e:   # noqa: BLE001
    error = f"{type(e).__name__}: {e}"
check("_quit 不把异常抛出去", error, None)
check("托盘照样退出了", icon.stopped, 1)

print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
