"""gamesnap.log、crash.log 打不开、删不掉、轮转不了时的处理（05-windows-verification P3、P4）。

以前：crash.log 超过 1 MB 时第二个实例删不掉它就崩溃；日志被别的程序禁写时同样崩溃（--launch 不执行，打包版弹模态框）；
日志被另一个进程开着时轮转失败，那一条日志丢掉，旧的 .log.1 也被先删了。现在检查：
1. gamesnap.log 打不开：setup_logging 不抛异常，这次不写文件；--console 时还输出到控制台；
2. crash.log 打不开：enable_crash_log 不抛异常，返回 None；
3. crash.log 太大：删得掉照旧删，删不掉接着往里写；
4. 两个日志都打不开时 main() 走完：--launch 执行，单实例检查照常；
5. 轮转失败：一行不丢，旧的 .log.1 还在；放开后下一条就轮转成功；
6. 只在 Windows 上：用真实的占用（CreateFileW 共享模式 0、1、3；另一个句柄开着日志）再跑一遍。
「打不开」用同名文件夹模拟，打开时真的抛 OSError。只在 <run dir> 里读写。纯 Python，Windows 和 Linux（tests/winstubs.py 桩）都能跑。
Exit code 1 if anything failed.

usage: python -X utf8 tests/test_log_fail.py <run dir>
"""
import faulthandler
import logging
import os
import sys
import types
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT, RUN = HERE.parent, Path(sys.argv[1])
RUN.mkdir(parents=True, exist_ok=False)
os.environ["APPDATA"] = str(RUN / "appdata")
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PROJECT))
import winstubs  # noqa: E402

winstubs.install()
import main  # noqa: E402

failures: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {got!r}" + ("" if ok else f"  (want {want!r})"))
    if not ok:
        failures.append(label)


def use_dir(name: str) -> None:
    """main 的日志路径指到 <run dir>\\<name>，日志配置清空：basicConfig 只有在没有 handler 时才生效。"""
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
        h.close()
    d = RUN / name
    d.mkdir()
    main.APP_DIR, main.LOG_PATH, main.CRASH_LOG = d, d / "gamesnap.log", d / "crash.log"


def close_crash(f) -> None:
    faulthandler.disable()
    if f is not None:
        f.close()


def attempt(fn, *a):
    """返回 (结果, 异常名)。"""
    try:
        return fn(*a), None
    except Exception as e:   # noqa: BLE001
        return None, type(e).__name__


def text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


log = logging.getLogger("gamesnap")
print("== 1. gamesnap.log 打不开")
use_dir("log_blocked")
main.LOG_PATH.mkdir()
_, error = attempt(main.setup_logging, False)
check("不抛异常", error, None)
check("没有写文件的 handler", [type(h).__name__ for h in logging.getLogger().handlers], ["NullHandler"])
log.info("这一条哪也不去")
use_dir("log_blocked_console")
main.LOG_PATH.mkdir()
_, error = attempt(main.setup_logging, True)
check("--console：不抛异常", error, None)
check("--console：还有控制台", [type(h).__name__ for h in logging.getLogger().handlers], ["StreamHandler"])

print("== 2. crash.log 打不开")
use_dir("crash_blocked")
main.CRASH_LOG.mkdir()
f, error = attempt(main.enable_crash_log)
check("不抛异常", error, None)
check("返回 None", f, None)

print("== 3. crash.log 太大")
use_dir("crash_big")
main.CRASH_LOG.write_bytes(b"x" * 1_000_001)
f, error = attempt(main.enable_crash_log)
close_crash(f)
check("删得掉：不抛异常", error, None)
check("删得掉：旧内容没了，从头写", main.CRASH_LOG.stat().st_size < 1000, True)

use_dir("crash_big_busy")
main.CRASH_LOG.write_bytes(b"x" * 1_000_001)
real_unlink = Path.unlink


def no_unlink(self, missing_ok=False):
    raise PermissionError(32, "另一个程序正在使用此文件（假）")


Path.unlink = no_unlink
f, error = attempt(main.enable_crash_log)
Path.unlink = real_unlink
close_crash(f)
check("删不掉：不抛异常", error, None)
check("删不掉：接着往里写", text(main.CRASH_LOG).endswith(f"GameSnap 启动 pid {os.getpid()}\n"), True)
check("删不掉：旧内容还在", main.CRASH_LOG.stat().st_size > 1_000_001, True)

print("== 4. 两个日志都打不开时 main() 走完")
use_dir("main_blocked")
main.LOG_PATH.mkdir()
main.CRASH_LOG.mkdir()
launched: list[str] = []
boxes: list[str] = []
real_argv = sys.argv
sys.argv = ["main.py", "--no-elevate", "--launch", "fake.exe"]
main.launch = lambda path, params: launched.append(path)
main.message_box = boxes.append
main.is_admin = lambda: False
main.Instance = lambda elevated: types.SimpleNamespace(elevated=elevated, already_running=True,
                                                       should_take_over=lambda: False)
_, error = attempt(main.main)
sys.argv = real_argv
check("不抛异常", error, None)
check("--launch 执行了", launched, ["fake.exe"])
check("没有弹窗", boxes, [])

print("== 5. 轮转失败")


def fill(n: int, tag: str) -> list[str]:
    lines = [f"{tag} 第 {i} 行" for i in range(n)]
    for line in lines:
        log.info(line)
    return lines


use_dir("rollover")
backup = Path(f"{main.LOG_PATH}.1")
backup.write_text("旧的备份\n", encoding="utf-8")
main.setup_logging(False)
handler = logging.getLogger().handlers[0]
check("用的是不丢行的 handler", type(handler).__name__, "AppendingLogHandler")
handler.maxBytes = 300   # 不用真写 1 MB
real_replace = os.replace


def busy_replace(src, dst):
    raise PermissionError(32, "另一个程序正在使用此文件（假）")


os.replace = busy_replace
lines = fill(20, "轮转失败")
os.replace = real_replace
content = text(main.LOG_PATH)
check("20 行一行不丢", [s for s in lines if s not in content], [])
check("旧的 .log.1 还在", text(backup), "旧的备份\n")
log.info("放开后的一条")
check("放开后轮转成功：旧日志进了 .log.1", [s for s in lines if s not in text(backup)], [])
check("放开后轮转成功：新日志从头写", "放开后的一条" in text(main.LOG_PATH) and "轮转失败" not in text(main.LOG_PATH), True)

if sys.platform == "win32":
    print("== 6. 真实的占用")
    import ctypes
    import ctypes.wintypes as wt
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wt.HANDLE
    k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
    k32.CloseHandle.argtypes = [wt.HANDLE]
    GENERIC_READ, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL = 0x80000000, 3, 0x80

    @contextmanager
    def held(path: Path, share: int):
        h = k32.CreateFileW(str(path), GENERIC_READ, share, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
        assert h not in (None, wt.HANDLE(-1).value), ctypes.get_last_error()
        try:
            yield
        finally:
            k32.CloseHandle(h)

    for share, writes in ((0, False), (1, False), (3, True)):
        use_dir(f"held_log_{share}")
        main.LOG_PATH.write_text("旧的一行\n", encoding="utf-8")
        with held(main.LOG_PATH, share):
            _, error = attempt(main.setup_logging, False)
            log.info("占用时的一条")
            for h in logging.getLogger().handlers:
                h.flush()
        check(f"gamesnap.log 共享模式 {share}：不抛异常", error, None)
        check(f"gamesnap.log 共享模式 {share}：写进去了吗", "占用时的一条" in text(main.LOG_PATH), writes)

        use_dir(f"held_crash_{share}")
        main.CRASH_LOG.write_text("旧的一行\n", encoding="utf-8")
        with held(main.CRASH_LOG, share):
            f, error = attempt(main.enable_crash_log)
        check(f"crash.log 共享模式 {share}：不抛异常", error, None)
        check(f"crash.log 共享模式 {share}：打开了吗", f is not None, writes)
        close_crash(f)

    use_dir("real_crash_big")
    main.CRASH_LOG.write_bytes(b"x" * 1_000_001)
    other = open(main.CRASH_LOG, "ab")   # 第一个实例开着它
    f, error = attempt(main.enable_crash_log)
    close_crash(f)
    other.close()
    check("第一个实例开着太大的 crash.log：不抛异常", error, None)
    check("第一个实例开着太大的 crash.log：接着写", main.CRASH_LOG.stat().st_size > 1_000_001, True)

    use_dir("real_rollover")
    backup = Path(f"{main.LOG_PATH}.1")
    backup.write_text("旧的备份\n", encoding="utf-8")
    main.setup_logging(False)
    logging.getLogger().handlers[0].maxBytes = 300
    other = open(main.LOG_PATH, "ab")   # 另一个 GameSnap 开着日志
    lines = fill(20, "真占用")
    content = text(main.LOG_PATH)
    check("真占用：20 行一行不丢", [s for s in lines if s not in content], [])
    check("真占用：旧的 .log.1 还在", text(backup), "旧的备份\n")
    other.close()
    log.info("放开后的一条")
    check("放开后轮转成功", [s for s in lines if s not in text(backup)], [])
else:
    print("SKIP  真实的占用：只在 Windows 上跑")

print("\n" + ("ALL PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
logging.shutdown()
sys.exit(1 if failures else 0)
