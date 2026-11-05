# GameSnap（game_snap）

Windows 托盘小工具：玩游戏时按一个键（默认 `` ` ``）立即全屏截图，按游戏分文件夹保存。随游戏启停，不常驻。
面向用户的完整说明在 README.md（托盘菜单、加别的游戏、工作方式、配置、旧版备份），改功能时 README 一起改。

Python 解释器、文件变更三级制、编码、MSIX 重定向这些通用规则见 `~\.claude\CLAUDE.md` 和工作区根的 CLAUDE.md，这里只写本项目的。

## 环境

- 本项目的依赖只装在 `D:\anaconda3\envs\gamesnap-build\python.exe`（Python 3.12，按 requirements.txt 装），跑源码、测试、打包都用它，用户已同意；不往 py312-clean 装本项目依赖。不 import 项目代码的独立小脚本仍用 py312-clean。
- 从源码运行：`gamesnap-build\python.exe main.py --no-elevate --console`（不加 `--no-elevate` 会弹 UAC 重新以管理员身份启动）。
- 打包：`gamesnap-build\python.exe build.py` → `dist\GameSnap\`（PyInstaller 文件夹版，约 92 个文件、40MB）。打包前先 `Get-Process GameSnap`，在运行就不打：文件被占用，而且所有快捷方式都指向 `dist\GameSnap\GameSnap.exe`，打包就是直接换掉用户在用的版本。
- 源码在 git 里（GitHub：OranngeAustin/game_snap）；dist、build、backup、tools\svcl 不进 git（见 .gitignore）。not_games.py 本机是完整黑名单，用 `git update-index --skip-worktree` 挡住不提交，仓库里是精简版。大改前把 dist 和源码备份到 `backup\vN_<说明>\`；改用户配置、快捷方式前备份到 `backup\before_<说明>\`；都在 README「旧版备份」里记一笔。
- 本机：笔记本，显示器由 AMD 核显驱动（另有 NVIDIA 独显，截图不用它）。「图片」文件夹是 `D:\00AustinDocuments\图片`，截图在 `GameShots\<游戏名>\` 下。

## 云端会话（Linux 容器）

在 claude.ai/code 的云端会话里是 Ubuntu，不是 Windows，大部分东西跑不了：

- winrt-*、pywin32 只有 Windows 版，装不上；代码 import 时就要 `winsound`、`winreg`、`ctypes.WinDLL`（Windows 版 Python 才有）。所以 main.py、build.py 跑不了，托盘、浮层、按键、截图这些真实行为也看不到。
- 能跑的是 quick 里的纯逻辑测试：`PYSTRAY_BACKEND=dummy ~/.venvs/gamesnap/bin/python -X utf8 tests/run_tests.py`（环境安装脚本建的 venv，Python 3.12 + mss、pillow、pystray；不设 dummy 时 `import pystray` 会去连 X 显示器而报错）。`tests/winstubs.py` 在非 Windows 上把 `ctypes.WinDLL`、`winsound`、`winreg` 换成桩（Windows 上什么都不做），所以大部分 quick 测试这里也能跑（2026-11-04：当时 31 个里 27 个通过；之后 quick 增加到 33 个、改过一批测试，云端没重跑）；add_game、blocklist_remove、yuzu_naming、dualsense 要 Windows 模块和真进程，在这里失败是环境原因；listener_restart 打印 SKIP；all 跑不了。仓库里的 not_games.py 是精简版，这里过了不代表本机那份也过。
- 在这里改了代码，要说清楚只在 Linux 上跑了 quick 的哪些（用了桩，测的是逻辑），其他得回 Windows 用 gamesnap-build 跑 quick / all。

## 用户的真实数据

- `C:\Users\azhao\AppData\Roaming\GameSnap\` 里的 config.json、gamesnap.log、crash.log。Claude 的工具直接读写这里会被 MSIX 重定向到包副本，看到的不是真文件。读真实日志和配置、改配置、建快捷方式，都在容器外起进程做：`Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine=...; CurrentDirectory=<项目目录>}`，结果写到 `%LOCALAPPDATA%\Temp` 下（不重定向），`Wait-Process` 等它结束，再 `Get-Content -Encoding UTF8` 读。
- 改真实 config.json：先确认 GameSnap 没在运行（开着时它下次保存会用内存里的配置覆盖文件），先备份，先 dry-run 再 `--apply`。
- 快捷方式共 7 个（开始菜单也在 Roaming 下，同样要在容器外建、改）。桌面和开始菜单各有这三个：
  - 「米哈游启动器 + 截图」：`--launch "D:\miHoYo Launcher\launcher.exe"`，勾了「以管理员身份运行」；
  - 「云·原神 + 截图」「yuzu + 截图」：带 `--no-elevate`。
  - 开始菜单另有一个不带参数的 `GameSnap.lnk`。
- 米哈游启动器的 `launcher.exe` 只是个壳，真正的启动器进程是 `HYP.exe`，`launchers` 里配的是它。

## 代码地图

| 文件 | 作用 |
|---|---|
| main.py | App：托盘菜单、状态、自动退出规则、更换截图键、添加 / 移除游戏；CaptureWorker（截图线程）；emulator_game（yuzu 按窗口标题分文件夹）；launch()；start_exit_watchdog()；命令行参数；提权重启 |
| config.py | Config：读写 config.json，`DEFAULTS`、`games_lower()` / `launchers_lower()`；`set()` 把整份配置写回文件；读完逐键校验，读不出来 / 有不合法值时先另存原文件；`update(key, change)` 在锁里读改写；读取和 `save()` 被占用时都重试，保存仍失败只提示、不抛异常；读不出来也另存不了时 `read_only`，这次运行不写回 |
| watcher.py | GameWatcher 定时扫进程：ProcessScanner 平时只用 EnumProcesses 拿 pid 列表，出现新 pid 才做一次 Toolhelp 快照查进程名，不用 OpenProcess；process_name、window_title、foreground |
| hotkey.py | InputListener：WH_KEYBOARD_LL 键盘钩子、Raw Input 鼠标侧键、前台切换事件；学习新截图键；key_name 显示名（系统给不出能用的名字的键写在 `_FIXED_NAMES`） |
| capture.py、d3d.py | WGC 抓帧，D3D 设备只建在驱动该显示器的显卡上，GDI（mss）兜底；D3D11 用纯 ctypes |
| toast.py | 提示浮层：不抢焦点、鼠标穿透、不进截图 |
| output.py | 存 PNG（元数据里记按键到上屏的时间差）、剪贴板、截图根目录、文件名清洗 `_safe_name` |
| dualsense.py | DualSense 四声道守护：读注册表核对，不对就用 `tools\svcl\svcl.exe` 改 |
| instance.py | 单实例：新实例有管理员权限而旧的没有时，旧的退出、新的接管；否则新的只拉起游戏就退出 |
| not_games.py | 「添加游戏…」的黑名单：GENERAL（常用软件）+ THIS_PC（2026-10-31 整理的本机非游戏软件）；要更新 THIS_PC，用 tests\list_software.py 重新列本机软件 |
| winapi.py | toast.py、hotkey.py 共用的 ctypes 声明 |
| build.py | PyInstaller 命令：winrt 的 hidden import、排除 numpy 等、带上 svcl |

## 设计约定（改代码时别破坏）

- 不碰游戏进程：不读写内存、不注入、不开进程句柄。
- 键盘钩子只在名单里的游戏运行时挂上（更换截图键、添加游戏等按键的那十几秒除外）；平时只有「绑定的键 + 前台是游戏」才吞键，其他一律放行；添加游戏时任何程序里的绑定键都吞，学键时任何键都吞。钩子回调要快，只往队列里放东西。挂 / 摘按键监听一律走 `App._sync_listener()`：它在 `_listener_lock` 里按 games / learning / adding 决定，改了这三个状态之后调它一次；只有退出时直接调 `_stop_listener()`。
- 截图会话开了就不关：v2 关会话偶尔崩溃，v3 起不关。Capturer 的方法只能在 CaptureWorker 线程里调用。
- 自动退出：启动器开着就一直等；玩过游戏后游戏和启动器全关掉，再等 `exit_grace_sec`；开头既没游戏也没启动器，等 `wait_no_launcher_sec`。更换截图键、添加游戏期间不自动退出。宽限从「最后一次还看到游戏的那次轮询」算起，实际可能比设定值少最多一个轮询间隔，计时类测试的下限要留出这一段。
- 退出看门狗：退出时托盘菜单开着，pystray 的 `WM_QUIT` 会被菜单的模态循环吃掉，主线程关掉菜单后一直等在 `GetMessage`，进程不结束、占着单实例（05 文档 P7）。所以 `_quit` 在 `icon.stop()` 之前调 `on_quitting`，main() 把它设成 `start_exit_watchdog`：`EXIT_WATCHDOG_SEC`（3 秒）后消息循环还没退出，就去掉托盘图标、直接结束进程。只在 main() 里挂，单元测试里建的 App 不开。
- 配置只在启动时读一次。改游戏名单用 `cfg.update("games", lambda games: {...新 dict...})`：在锁里读改写，添加和移除同时发生也不丢；不要原地改（GameWatcher 线程在读）。
- 托盘菜单用 pystray 的 win32 后端：`Menu(函数)` 每次刷新都重新生成；菜单文字里的 `&` 要写成 `&&`；item 的 ID 是它在回调列表里的序号 + 1（子菜单项也算在内）。菜单开着时别的线程刷新托盘会 `DestroyMenu` 正在显示的菜单：实测（05 文档 Q1）旧菜单和子菜单照常能点、回调照常执行、句柄不漏，下次打开才是新内容，不用特殊处理。
- 黑名单只在「添加游戏…」时查，手写进 config.json 的游戏不受它限制。不要加 python、javaw、dotnet、mono 这类也用来跑游戏的运行环境，也不要加 game、start、main 这类通用名；WeChatAppEx 特意没拦（微信小游戏在里面）。用户 2026-10-31 审过现在这份名单。它是哈希集合，再长也不影响性能。
- 米哈游的游戏以管理员身份运行，GameSnap 要有管理员权限才收得到按键；不需要管理员权限的游戏（云原神、yuzu、大多数 Steam 游戏）的快捷方式用 `--no-elevate`。
- 注释、日志、托盘菜单、提示文字、README 都用中文。

## 测试

测试在 `tests\`，每个测什么、怎么跑见 tests\README.md。改完代码至少跑 quick；动了托盘、进程检测、自动退出、按键、打包，就跑 all：

- `gamesnap-build\python.exe -X utf8 tests\run_tests.py`：quick，约半分钟，不启动 GameSnap，容器里也能跑。
- `gamesnap-build\python.exe -X utf8 tests\run_tests.py all --out build\test_runs\<名字>`：约 2 分半，会真的启动 GameSnap。先退出正在运行的 GameSnap，测打包版前先重新打包，并且要用 Invoke-CimMethod 在容器外启动（命令在 tests\README.md 里），再读 `<out>\summary.txt`。

结果都在 `build\test_runs\` 下，清理旧输出前先问用户。加了功能就照现有的测试补一个，登记进 run_tests.py 的 QUICK / SLOW 和 tests\README.md 的表。写新测试的套路：

- 单元级：import 之前先把 `os.environ["APPDATA"]` 指到测试目录（`config.APP_DIR` 在 import 时就定了），用测试配置建真的 `main.App`，把 toast、托盘 icon、`worker.post`、`main.InputListener` 换成桩；按键直接调 `App._on_key(...)`。假游戏用改了名的 ping.exe 副本（如 FakeGame.exe），或子进程里的隐藏窗口。托盘菜单可以用 `icon._create_menu(icon.menu, callbacks)` 建出真的 Win32 菜单，再调 `callbacks[id - 1](icon)` 模拟点击。
- 同一进程里建多个 App 时，把换下来的 `app.icon` 存进列表留着：pystray 的窗口类名里有 `id(icon)`，用完也不注销，旧图标被回收后地址给了新图标就报 WinError 1410「类已存在」（偶发）。
- 计时断言留出时钟精度：这个 Python 的 `time.monotonic` 是 `GetTickCount64`，精度约 15.6 ms，两次调用可能完全相等。
- 想让云端也能跑的纯逻辑测试：import 项目模块之前 `import winstubs; winstubs.install()`，用到的 Win32 函数在测试里换成假的（例子见 tests\test_listener_sync.py、test_toast_gdi.py）；Windows 上 winstubs 什么都不做，测的是真模块。
- 实机（源码）：写个 inner 脚本（例子见 tests\add_live_inner.py），import main 后打补丁再调 `main.main()`：`dualsense.set_quad` 换成一调用就报错的绊线，`toast.Toast.show` 改成写日志，需要时 `main.confirm` 自动答「是」。截图键用 F24（打字不会误触），参数 `--no-elevate --config <测试配置>`，APPDATA 指到测试目录。外层脚本用上面的 Invoke-CimMethod 在容器外启动，读 gamesnap.log 断言。
- 打包版：`dist\GameSnap\GameSnap.exe --no-elevate --config <测试配置>`，用 ping.exe 副本当游戏和启动器，测「启动 → 检测到游戏 → 关游戏 → 自动退出」，以及几个游戏和启动器按不同顺序关闭。
- 跑测试、打包前先 `Get-Process GameSnap`：单实例互斥，测试实例会自己退出，或者把用户正在用的那个顶掉。
- 测试里绝不真的改 DualSense 声音设置（svcl 的写操作）；不发真实按键（SendInput），不启动用户的游戏和软件，除非用户同意。

## 排错线索

- 先看 gamesnap.log（真实的那份要在容器外读）。每张截图记一行：后端、「帧上屏-按键」时间差、按键到抓到的耗时。
- crash.log：faulthandler 记下各线程的调用栈。驱动自己处理掉的访问违例也会记一笔，要对照 gamesnap.log 看进程是否真的退出了。
- 日志有「消息循环 3 秒内没有退出」：退出时托盘菜单开着，看门狗结束了进程，不是问题；别的情况下出现才要查。
- 在游戏里按键没反应：多半是游戏以管理员身份运行而 GameSnap 没有（日志第一行「管理员权限：False」）。
- 截出黑屏：个别游戏禁止截屏；看日志里截图那一行的后端。
