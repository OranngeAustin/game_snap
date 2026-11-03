"""Tests for game_snap\\dualsense.py. Never changes any system setting:
- part 1 reads the real registry (read-only) and prints what it finds;
- part 2 replaces find/read/set with fakes and checks the decision logic;
- part 3 runs the real guard thread against the real registry, with set_quad replaced by a tripwire.
Parts 1 and 3 look at the real controller; with no DualSense plugged in they check the not-plugged-in
path instead. Exit code 1 if anything failed.

usage: python -X utf8 tests\\test_dualsense.py
"""
import importlib
import logging
import sys
import time
from pathlib import Path

proj = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(proj))
import dualsense as ds  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(name)


# ---------------------------------------------------------------- part 1: real registry, read-only
t0 = time.perf_counter()
eps = ds.find_dualsense()
ms = (time.perf_counter() - t0) * 1000
print(f"real: {len(eps)} DualSense endpoint(s), scan took {ms:.1f} ms")
for ep in eps:
    print("   ", ep.item_id, "|", ep.describe(), "| is_quad =", ep.is_quad)
if eps:
    check("real controller found and already quad", len(eps) == 1 and eps[0].is_quad)
else:
    print("SKIP no DualSense plugged in (part 3 checks the not-plugged-in path)")
check("svcl path resolves to tools\\svcl\\svcl.exe",
      ds.SVCL == proj / "tools" / "svcl" / "svcl.exe" and ds.SVCL.is_file(), str(ds.SVCL))

# ---------------------------------------------------------------- part 2: fakes
REAL_BLOB = bytes.fromhex("41000000 01000000 FEFF0400 80BB0000 00DC0500 08001000 "
                          "16001000 33000000 01000000 00001000 800000AA 00389B71".replace(" ", ""))
PCM_STEREO = bytes.fromhex("41000000 01000000 01000200 80BB0000 00EE0200 04001000 0000".replace(" ", ""))
check("channel mask from the real DeviceFormat blob", ds._channel_mask(REAL_BLOB) == 0x33)
check("channel mask from a plain PCM stereo blob", ds._channel_mask(PCM_STEREO) == 0x3)
check("channel mask from a short blob", ds._channel_mask(b"\x41\x00") is None)
check("describe()", ds.Endpoint("{g}", 0x33, 0x3, None).describe() == "声道 0x33 / 扬声器 0x3 / 全音域 ?",
      ds.Endpoint("{g}", 0x33, 0x3, None).describe())
check("is_quad ignores an unreadable channel mask", ds.Endpoint("{g}", None, 0x33, 0x33).is_quad)
check("is_quad needs all four speakers full range", not ds.Endpoint("{g}", 0x33, 0x33, 0x3).is_quad)


class Fake:
    def __init__(self):
        self.state = {}       # guid -> (channel mask, speakers, full range)
        self.calls = []
        self.mode = "works"   # works | ignored | raises

    def find(self):
        return [ds.Endpoint(g, *v) for g, v in self.state.items()]

    def read(self, guid):
        v = self.state.get(guid)
        return ds.Endpoint(guid, *v) if v else None

    def set_quad(self, ep):
        self.calls.append(ep.item_id)
        if self.mode == "raises":
            raise OSError("fake failure")
        if self.mode == "works":
            self.state[ep.guid] = (0x33, 0x33, 0x33)
        return "fake svcl output\r\r\n"


fake = Fake()
ds.find_dualsense, ds.read_endpoint, ds.set_quad = fake.find, fake.read, fake.set_quad
ds.VERIFY_SEC = 0.3
QUAD3, STEREO = (0x33, 0x33, 0x33), (0x3, 0x3, 0x3)
real_svcl, missing_svcl = ds.SVCL, proj / "tools" / "svcl" / "missing.exe"

fake.state = {"{a}": QUAD3}
st, _ = ds.ensure_quad(fake.read("{a}"))
check("ensure: already quad -> OK, svcl not run", st == ds.OK and not fake.calls)

fake.state = {"{a}": STEREO}
st, now = ds.ensure_quad(fake.read("{a}"))
check("ensure: stereo -> FIXED", st == ds.FIXED and now.is_quad and fake.calls == ["{0.0.0.00000000}.{a}"])

fake.calls.clear(); fake.state = {"{a}": STEREO}; fake.mode = "ignored"
st, now = ds.ensure_quad(fake.read("{a}"))
check("ensure: svcl ran but nothing changed -> UNVERIFIED", st == ds.UNVERIFIED and not now.is_quad)

fake.mode = "raises"
st, _ = ds.ensure_quad(fake.read("{a}"))
check("ensure: svcl could not run -> FAILED", st == ds.FAILED)

ds.SVCL = missing_svcl
fake.calls.clear(); fake.mode = "works"
st, _ = ds.ensure_quad(fake.read("{a}"))
check("ensure: no svcl -> NO_TOOL, nothing run", st == ds.NO_TOOL and not fake.calls)
ds.SVCL = real_svcl

results, enabled = [], [True]
g = ds.DualSenseGuard(lambda: enabled[0], results.append)

fake.calls.clear(); fake.mode = "works"
fake.state = {"{a}": QUAD3, "{b}": STEREO}
retry = g._check(True)
check("guard: two controllers, fixes only the stereo one, reports once",
      fake.calls == ["{0.0.0.00000000}.{b}"] and results == [ds.FIXED] and not retry, f"{fake.calls} {results}")
fake.calls.clear(); results.clear()
g._check(False)
check("guard: next pass does nothing", not fake.calls and not results)

fake.state["{b}"] = STEREO   # something switched it back while still plugged in
g._check(False)
check("guard: switched back -> fixed again", fake.calls == ["{0.0.0.00000000}.{b}"] and results == [ds.FIXED])

fake.calls.clear(); results.clear(); fake.mode = "ignored"
fake.state = {"{c}": STEREO}
retries = [g._check(False) for _ in range(ds.MAX_TRIES + 2)]
check("guard: never takes -> gives up after MAX_TRIES, reports once",
      len(fake.calls) == ds.MAX_TRIES and results == [ds.UNVERIFIED]
      and retries == [True] * (ds.MAX_TRIES - 1) + [False] * 3, f"{len(fake.calls)} {results} {retries}")

fake.state = {}
g._check(False)   # unplugged
fake.calls.clear(); results.clear(); fake.mode = "works"
fake.state = {"{c}": STEREO}
g._check(False)   # plugged in again
check("guard: unplug + plug in again starts over", fake.calls == ["{0.0.0.00000000}.{c}"] and results == [ds.FIXED])

fake.calls.clear(); results.clear()
enabled[0] = False
fake.state = {"{d}": STEREO}
g._check(True)
check("guard: switched off in the tray -> nothing changed", not fake.calls and not results)
enabled[0] = True

ds.SVCL = missing_svcl
fake.state = {"{e}": STEREO}
g._check(False)
g._check(False)
check("guard: no svcl -> one reminder per plug-in", results == [ds.NO_TOOL] and not fake.calls, f"{results}")
ds.SVCL = real_svcl

# ---------------------------------------------------------------- part 3: real thread + tripwire
ds = importlib.reload(ds)   # real find/read again
tripped = []


def tripwire(ep):
    tripped.append(ep.item_id)
    raise AssertionError("set_quad must not run in this test")


ds.set_quad = tripwire
records = []


class Capture(logging.Handler):
    def emit(self, record):
        records.append(record.getMessage())


logging.getLogger("dualsense").addHandler(Capture())
logging.getLogger("dualsense").setLevel(logging.INFO)
results3 = []
g3 = ds.DualSenseGuard(lambda: True, results3.append)
g3.start()
time.sleep(2.5)
ok_text = "正常" if eps else "没有插着 DualSense"
first = [m for m in records if ok_text in m]
g3.recheck()
time.sleep(2.5)
second = [m for m in records if ok_text in m]
check(f"thread: startup check logs {ok_text!r}", len(first) == 1, first[0] if first else "no log")
check("thread: recheck() wakes the loop and checks again", len(second) == 2, f"{len(second)} lines")
check("thread: never tried to change anything", not tripped and not results3)
check("thread: change notification registered", not any("登记失败" in m for m in records))
print("thread log:", *records, sep="\n  ")
print("\nFAILED: " + ", ".join(failures) if failures else "\nALL PASSED")
sys.exit(1 if failures else 0)
