# 01 架构摸底

审查基线：`main` @ 58c59fb（2026-11-03）。仓库是扁平结构：根目录 13 个 `.py` 模块（约 2900 行），
`tests/`（18 个脚本，约 2500 行），`docs/review/`。CLAUDE.md 里不进 git 的目录（`dist/`、`build/`、
`backup/`、`tools/svcl/`）本来就不在仓库里，审查不涉及。

## 1. 模块划分

| 层 | 模块 | 行数 | 职责 | 运行在哪个线程 |
|---|---|---|---|---|
| 入口 / 编排 | `main.py` | 609 | 参数解析、提权重启、单实例、日志；`App`（状态机、托盘菜单、自动退出、学键、添加/移除游戏）；`CaptureWorker`（截图线程）；`emulator_game` / `default_game_name` | 主线程（托盘消息循环）+ 多个 |
| 配置 | `config.py` | 83 | `Config`：读 `%APPDATA%\GameSnap\config.json`（覆盖到 `DEFAULTS` 上，浅合并），`set()` 写回（临时文件 + `os.replace`） | 任意线程 |
| 进程检测 | `watcher.py` | 153 | `ProcessScanner`（EnumProcesses 拿 pid，出现新 pid 才做 Toolhelp 快照）；`GameWatcher` 线程定时回调 `App.on_poll`；`foreground` / `window_title` / `process_name` | GameWatcher |
| 输入 | `hotkey.py` | 293 | `InputListener` 线程：WH_KEYBOARD_LL 键盘钩子、Raw Input 鼠标侧键、前台切换 WinEvent、学习新键 | InputListener（每次需要时新建一个） |
| 抓帧 | `capture.py` | 329 | `Capturer`：WGC 会话 / 帧池、等「按键后第一帧」、黑帧检测、GDI（mss）兜底 | CaptureWorker |
| 抓帧 | `d3d.py` | 188 | 纯 ctypes 的 D3D11 / DXGI：按显示器找显卡 LUID、建设备、暂存纹理读回 | CaptureWorker |
| 输出 | `output.py` | 80 | `save_png`（按游戏分文件夹、写元数据、`.part` 改名）、`copy_to_clipboard`（CF_DIB）、`shots_root`、`_safe_name` | Saver（单线程池） |
| 界面 | `toast.py` | 258 | 分层窗口提示浮层：不抢焦点、穿透、不进截图；PIL 画卡片 | Toast |
| 界面 | `winapi.py` | 87 | toast / hotkey 共用的 Win32 声明、`create_window`、`message_loop` | — |
| 外设 | `dualsense.py` | 263 | 读注册表核对 DualSense 扬声器配置，不对就跑 `tools\svcl\svcl.exe` 改；注册表变化通知驱动 | DualSense |
| 进程间 | `instance.py` | 120 | 命名互斥体 / 事件实现单实例与「管理员实例接管」 | 主线程 + InstanceQuit |
| 数据 | `not_games.py` | 31 | 「添加游戏」黑名单（仓库里是精简版） | — |
| 打包 | `build.py` | 77 | PyInstaller 文件夹版命令 | — |
| 测试 | `tests/` | — | `run_tests.py` 调度；quick（进程内、桩）和 slow（真起 GameSnap / 打包版） | — |

依赖关系（箭头 = import）：

```
main ──► capture ──► d3d
  │        ▲
  │        └──────── hotkey ──► watcher
  ├──► config            └────► winapi ◄── toast
  ├──► dualsense
  ├──► instance
  ├──► not_games
  ├──► output
  ├──► toast
  └──► watcher
build ──► main（只为 make_icon）
```

## 2. 入口

- `main.py: main()`（也是 PyInstaller 的入口）。参数：`--launch`、`--launch-args`、`--no-elevate`、`--console`、`--config`。
- `build.py: main()`：打包。
- `tests/run_tests.py`：测试调度；`tests/bench_startup.py`：打包版启动耗时。

## 3. 核心数据流

### 3.1 启动

```
main() ─ 不是管理员且没 --no-elevate ─► ShellExecute("runas") 重启自己，本进程返回
       ─ setup_logging / enable_crash_log（faulthandler → crash.log）
       ─ --launch ─► ShellExecute 启动启动器 / 链接
       ─ Instance(is_admin)：CreateMutex("Local\GameSnap_SingleInstance")
            ├ 已有实例且本实例提权、对方没提权 ─► SetEvent(Quit) 等对方放开互斥体后接管
            └ 已有实例（其他情况）─► 本实例退出
       ─ App(Config(...)) ─ inst.serve(on_quit=自动退出) ─ app.run()（托盘消息循环，阻塞）
       ─ os._exit(0)（跳过解释器收尾：释放 WGC 会话会触发系统里的崩溃）
```

### 3.2 进程检测与生命周期（GameWatcher 线程，默认每 2 秒）

```
ProcessScanner.scan(cfg.games_lower(), cfg.launchers_lower())
  EnumProcesses → pid 集合；有新 pid 或满 30 秒 → Toolhelp 快照刷新 {pid: 小写进程名}
  → ({游戏 pid: 显示名}, 启动器是否在运行)
App.on_poll(games, launcher)
  ├ games 变了 → _on_games_changed：有游戏 → _ensure_listener() + post("warmup"/"fg")；
  │                                 没游戏 → _stop_listener()（学键 / 添加中除外）
  ├ 有游戏 → _seen_game=True，_idle_since=now
  ├ 学键 / 添加中 → 不判断退出
  ├ 启动器在 → _idle_since=now（一直等）
  ├ 否则 now-_idle_since ≥ exit_grace_sec（玩过）/ wait_no_launcher_sec（没玩过）→ _auto_quit
  └ 每 60 秒 EmptyWorkingSet（只在等待时）
```

### 3.3 截图（延迟敏感的主路径）

```
键盘钩子回调（InputListener 线程）
  qpc_now() → _handle_key：绑定键 + should_capture(前台 pid) → 吞键 → App._on_key
App._on_key → worker.post("shot", t_key, hwnd, pid)
CaptureWorker 线程：
  emulator_game(hwnd) or games[pid] → 游戏名
  Capturer.grab：没有会话就开；wait_frame(t_key, 150ms) 等按键后第一帧
     → to_image：CopyResource 到暂存纹理 → Map → PIL BGRX→RGB 解码
     → _is_black ? GDI(mss) 兜底
  saver.submit(App.finish_shot)
Saver 线程：
  save_png（PNG 压缩级别 6，.part → 改名）→ copy_to_clipboard（转 BMP 去头 = CF_DIB）
  → log → toast.show（Toast 线程里 render_card 画卡片、UpdateLayeredWindow）→ refresh_tray（重画托盘图标）
```

前台切换（WinEvent）→ `post("fg")` → `Capturer.open`：游戏第一次到前台时开会话并预热，之后只换新帧。

### 3.4 托盘交互

- 「更换截图键…」：`start_learning` → listener 进入学习模式 → 钩子 / Raw Input 收到第一个键 → `_on_learned`
  → 新线程 `_finish_learning` → `cfg.set("hotkey")` + `listener.set_binding`；10 秒超时由 Timer 取消。
- 「添加游戏…」：`start_adding` → `adding=True`（任何非本进程窗口里按截图键都吞下）→ `_on_key` 起线程
  `_finish_adding`：`process_name(pid)` → 黑名单 / 启动器拒收，否则 `cfg.set("games", 新 dict)`；15 秒超时。
- 「游戏名单」子菜单：每次刷新按当前名单生成，点一项 `confirm()` 后 `cfg.set("games", 新 dict)`。
- 开关项：`cfg.set(key, not cfg[key])`。

### 3.5 DualSense 守护（DualSense 线程）

`RegNotifyChangeKeyValue(HKLM\...\MMDevices\Audio\Render)` + 手动 recheck 事件 → `find_dualsense()` 读注册表
→ 不是四声道就 `subprocess.run([svcl.exe, /SetSpeakersConfig, ...])`，再读注册表核对；每次插入最多 3 次。

### 3.6 单实例接管（instance.py）

命名对象都用 `D:(A;;GA;;;WD)S:(ML;;NW;;;LW)`（所有人可访问、低完整性），普通 / 管理员实例才能互相打开。
`Local\GameSnap_Elevated` 互斥体标明正在运行的实例已提权；`Local\GameSnap_Quit` 自动复位事件让旧实例退出。

## 4. 外部依赖

| 依赖 | 用途 | 备注 |
|---|---|---|
| winrt-*（≥3.2） | Windows.Graphics.Capture | 只在第一次抓帧时导入 |
| mss（≥10） | GDI 兜底截图 | |
| pillow（≥10.1） | 图像转换、PNG 编码、托盘图标、提示卡片 | 主要 CPU 消耗都在它里面 |
| pystray（≥0.19） | 托盘图标与菜单（win32 后端） | 非线程安全的第三方 UI 库，被多个线程调用 `refresh_tray` |
| pywin32（≥306） | 只用了 `win32clipboard` | |
| pyinstaller（≥6） | 打包 | |
| NirSoft svcl.exe v1.28 | 改扬声器配置 | 不进 git，本地自备，打包时带上 |
| Win32 / D3D11 / DXGI（ctypes） | 钩子、窗口、进程枚举、显卡、注册表通知 | 大量手写 argtypes 和 COM 虚表序号 |

没有网络访问、没有数据库、没有对外 API；唯一的持久化是 config.json、gamesnap.log、crash.log 和截图文件。

## 5. 高风险区域

1. **ctypes 回调与窗口生命周期**（`hotkey.py`、`winapi.py`、`toast.py`）：WNDPROC / HOOKPROC 的引用管理、
   窗口类注册、跨线程投递消息。出错就是原生崩溃，Python 层拦不住，crash.log 才看得到。
2. **手写 COM / D3D11 调用**（`d3d.py`、`capture.py`）：按虚表序号调用、HRESULT 大多不检查、
   空指针一旦传进驱动就是访问违例；会话「开了不关」是为绕开系统里的崩溃。
3. **多线程共享状态**（`main.py` 的 `App`）：主线程（托盘）、GameWatcher、InputListener、CaptureWorker、Saver、
   Toast、DualSense、InstanceQuit 加上若干 Timer / 临时线程，共享 `games`、`learning`、`adding`、`listener`、
   `_idle_since`，只有 listener 和「添加」两处加了锁。
4. **用户配置的读写**（`config.py`）：配置是用户的数据（游戏名单、截图键），README 鼓励手改；读失败、写失败、
   类型不对时的行为。
5. **进程检测与自动退出**（`watcher.py` + `App.on_poll`）：误判「游戏都退出了」会让 GameSnap 中途退出或摘掉钩子。
6. **文件输出**（`output.py`）：文件夹名来自窗口标题（yuzu、新加的游戏），路径清洗。
7. **提权与外部程序**（`main.launch` / `relaunch_as_admin`、`dualsense.set_quad`、`instance.py`）：以管理员身份
   运行的进程启动外部程序、读用户可写的配置。
8. 低风险：`not_games.py`（数据）、`build.py`（开发工具）、`tests/`。

## 6. 审查顺序（风险从高到低）

仓库只有根目录一层源码，按文件排；括号里是第 5 节对应的风险编号。

1. `/hotkey.py` + `/winapi.py`（1）
2. `/d3d.py` + `/capture.py`（2）
3. `/main.py`（3、5、7）
4. `/config.py`（4）
5. `/watcher.py`（5）
6. `/toast.py`（1）
7. `/output.py`（6）
8. `/instance.py`、`/dualsense.py`（7）
9. `/build.py`、`/not_games.py`（8）
10. `/tests/`（只看与上面发现相关的覆盖情况）

## 7. 云端环境能验证什么

- 能跑：`tests/test_not_games.py`；任何只用 PIL / 纯 Python 的逻辑（需要把 `ctypes.WinDLL`、`winsound`、`winreg`
  换成桩才能 import 项目模块）。
- 不能跑：所有 Win32 / WinRT / D3D 调用、托盘、钩子、真实截图、打包、`bench_startup.py`。这些改动只能读代码推断，
  要回 Windows 用 gamesnap-build 跑 `tests\run_tests.py all` 验证。
