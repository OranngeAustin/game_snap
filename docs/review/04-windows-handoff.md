# 04 Windows 交接：在本机验证三轮修复

2026-11-04 写于 claude.ai 云端会话（Linux 容器）。三轮修复（高危、中危、低危）加上阶段 6 的三项性能优化，**全部只在 Linux 上跑过测试**：
Windows 专属的测试、打包、托盘 / 浮层 / 按键 / 截图这些真实行为一样都没验证过。本文给在本机 Windows 上用 Claude Code 接手的人（或你自己）用。

分支（2026-11-04 更新）：PR #2–#6 都已按你的要求、按顺序合并（low → medium → review-fixes），只剩 PR #1 没合并，main 仍是 58c59fb。

```
main ← PR #1（未合并）← claude/review-fixes ← claude/medium-fixes（PR #5，已合并）← claude/low-fixes（PR #6，已合并）
                        （PR #2、#3、#4 也已合进 claude/review-fixes）
```

`claude/review-fixes` 包含全部改动，**在它上面验证**。都通过后再决定是否合并 #1 到 main（合并前按 CLAUDE.md 备份，见第 4 节第 4 步）。
每条发现的详情在 [02-findings.md](02-findings.md)，每个决定的理由在 [PROGRESS.md](PROGRESS.md) 的 D1–D25。

## 1. 三轮修改总览（按模块）

| 模块 | 改了什么 | 发现编号 | commit | PR |
|---|---|---|---|---|
| config.py | 用 `utf-8-sig` 读（带 BOM 也能读）；读不出来时先另存 `config.unreadable_<时间>.json` | H2 | 93f99bf | #1 |
| | 读完后逐键校验类型和范围，不合法的回退默认值并记日志，有改动先另存 `config.invalid_<时间>.json` | M5 | 5b9dc22 | #5 |
| | 新增 `Config.update(key, change)`：在锁里读改写 | L17 | c7ff386 | #6 |
| | `save()` 被占用时隔 0.2 秒重试 5 次，仍失败记日志、调 `on_save_error`、返回 False，不抛异常；`set()` 返回是否存上 | L18 | a06cd72 | #6 |
| winapi.py | `unique_class_name()`：每个窗口一个类名；`create_window` 注册失败就抛错，建窗口失败就注销类；新增 `unregister_class` | H1 | d7b4f29 | #1 |
| hotkey.py | 监听窗口用自己的类名，消息循环结束后注销 | H1 | d7b4f29 | #1 |
| | 启动失败记 `_failed`、拆掉挂了一半的钩子，`wait_ready()` 返回 False | M4 | f479e05 | #5 |
| | 「按住」状态：距上次按下超过 1.5 秒当新按下（`HELD_STALE_SEC`）；`set_binding` / `start_learning` 清掉按住状态 | L1 | 31873dc | #6 |
| | `SetWinEventHook` 失败记警告 | L3 | 199aecc | #6 |
| | `key_name` 用 `MAPVK_VK_TO_VSC_EX`，扩展键置 lParam 第 24 位 | L4 | 7564bf4 | #6 |
| toast.py | 浮层窗口用自己的类名 | H1 | d7b4f29 | #1 |
| | 同样的参数只画一次卡片（`lru_cache(maxsize=4)`，返回拷贝） | P3 / L13 | 453ecde | #4 |
| | `GetDC` / `CreateCompatibleDC` / `CreateDIBSection` 失败不写 0 地址、不显示；`ReleaseDC` 放进 finally | M3 | f23c5d5 | #5 |
| main.py | 托盘图标按状态缓存（`lru_cache`，返回拷贝） | P2 / L14 | ee9823e | #3 |
| | `_sync_listener()`：该挂还是该摘监听在一把锁里判断；`_learn_timeout` 不再要求监听还在 | M7 | eec846a | #5 |
| | `refresh_tray` 整体加锁，图标状态没变不重设 | M6 / L14 | 2e32e53 | #5 |
| | 监听启动失败时不留死对象、提示、下次需要时重建；学键 / 添加游戏立即复位 | M4 | f479e05、471f99d（测试） | #5 |
| | 新增 `App.on_tray_ready`：托盘就绪后才开始等单实例退出信号；`_quit` 出错也调 `icon.stop()` | M8 | 2335f3f | #5 |
| | `_finish_learning` 加 `_learn_lock` | L2 | b213929 | #6 |
| | 学键 / 添加结束时先设 `_idle_since` 再清标志 | L16 | bb167cf | #6 |
| | 添加 / 移除游戏改用 `cfg.update` | L17 | c7ff386 | #6 |
| | `cfg.on_save_error` 提示「设置没保存上」 | L18 | a06cd72 | #6 |
| instance.py | 拿到互斥体就 `_announce()` 建 Quit 事件和 Elevated 标记；`take_over` 对 `OpenEventW` 重试 3 秒；接管后 `ResetEvent` 清残留信号；`serve()` 只启动等待线程 | M8 | 2335f3f | #5 |
| capture.py | 重建帧池前先存下 `content_size`，不在 `close()` 之后读 | M1 | 4f5d1b0 | #5 |
| | 会话建到一半失败时放进 `_half_built` 留着引用，不让 GC 关掉 | L9 | 8533002 | #6 |
| d3d.py | 换暂存纹理时 release 后立即清零 | L5 | 88f6eca | #6 |
| | `find_adapter`、`Device.__init__` 的异常路径上释放显卡 / device / context | L6 | 598b848 | #6 |
| output.py | `copy_to_clipboard`：图已是 RGB 就不 convert | P1 / L12 | 5878a8b | #2 |
| | `_safe_name`：只有点的名字、控制字符、Windows 保留名、超过 80 个字符 | M2 | 0808667 | #5 |
| | 写剪贴板出错返回 False，不再报「截图失败」 | L10 | b51adab | #6 |
| | `save_png` 失败时删掉 `.png.part` | L11 | a5777d4 | #6 |
| watcher.py | `EnumProcesses` 失败 / 返回 0 个、快照为空时抛异常，GameWatcher 跳过这一轮 | L15 | 18bf92e | #6 |
| README.md | 「配置」补读不出来时的另存、不合法值的处理；「截图存在哪」补文件名规则 | H2、M5、M2 | 93f99bf、5b9dc22、0808667 | #1、#5 |
| tests/ | 新增 26 个测试（下表）、`winstubs.py`（非 Windows 上装桩）、`bench_logic.py`（基准）；都登记进 run_tests.py 和 tests/README.md | — | 各 commit | #1–#6 |
| docs/review/ | 01 架构、02 发现、03 性能计划、00 总结、PROGRESS、本文件 | — | — | #1、#5、#6 |

新增测试（全部在 QUICK 里，Windows 上测的是真模块，Linux 上靠 winstubs 桩）：

| 轮次 | 测试 |
|---|---|
| 高危（#1） | config、listener_restart（只能在 Windows 上跑） |
| 性能（#2–#4） | clipboard、tray_icon、toast_card |
| 中危（#5） | listener_sync、config_values、tray_refresh、capture_resize、listener_start_fail、instance_quit、safe_name、toast_gdi |
| 低危（#6） | clipboard_error、save_png_fail、scan_fail、idle_order、learn_race、games_update、config_save_fail、held_key、key_name、win_event_hook、d3d_staging、d3d_release、session_init_fail |

## 2. 云端没能验证的内容

**测试**

| 项 | 云端结果 | 原因 |
|---|---|---|
| quick 里的 add_game、blocklist_remove、yuzu_naming、dualsense | 失败（每轮都一样） | 一 import 就要 `winsound` / `winreg` / `ctypes.WinDLL`；add_game 等还要 ping.exe 副本和子进程窗口 |
| listener_restart | 打印 SKIP | 要真的挂键盘钩子、建窗口 |
| all 的 lifecycle_source、add_live、remove_live、lifecycle_exe、multi_exit | 准备阶段就失败，没执行到项目代码 | 找不到 `D:\anaconda3\envs\gamesnap-build\python.exe`、`C:\Windows\System32\PING.EXE`、`dist\GameSnap\GameSnap.exe`；`run_tests.py all` 本身一开头 import watcher 就失败 |
| `tests\bench_startup.py`、`build.py` 打包 | 没跑 | 要 PyInstaller 和打包版 |
| 26 个新测试在 Windows 上的表现 | **从没在 Windows 上跑过** | 它们在 Linux 上用的是 MagicMock 桩。几个测试在进程内替换了 Windows 的东西，Windows 上第一次跑时可能因为桩的写法和真模块不一致而失败，要先分清是测试的问题还是代码的问题：instance_quit 全局替换了 `ctypes.get_last_error` / `set_last_error`；toast_gdi 替换了 `toast.user32` / `gdi32` 和 `ctypes.memmove`；win_event_hook、key_name 替换了 `hotkey.user32`；listener_start_fail 用真的 InputListener、只把 `create_window` 换成报错；held_key 在 Windows 上用真的 `QPC_FREQ` |

**真实行为（只能实机看）**

- 托盘：图标、菜单、开关、「游戏名单」子菜单（pystray win32 后端，M6、P2）。
- 提示浮层：显示位置、清晰度、淡出、不进截图（M3、P3、高 DPI）。
- 按键：低级键盘钩子、Raw Input 鼠标侧键、学键、前台切换事件（H1、M4、M7、L1、L2、L3、L4）。
- 截图：WGC 抓帧、改分辨率后重建帧池、D3D 读回、GDI 兜底（M1、L5、L6、L9）。
- 单实例接管和 UAC 提权（M8）。
- 剪贴板真实写入、被其他程序占用时（P1、L10）。
- 文件被占用：config.json 保存重试（L18）、`.png.part` 清理（L11）。
- 中文路径、OneDrive 迁移过的「图片」文件夹。
- 打包版：PyInstaller 有没有漏模块（这几轮没加新模块，只加了 `functools`、`itertools`、`math` 等标准库）。

**.bat 启动脚本**：仓库里没有 .bat / .cmd / .ps1。启动靠桌面和开始菜单的 6 个 .lnk 快捷方式（CLAUDE.md「快捷方式」），参数 `--launch`、`--no-elevate` 这几轮没改，但要在重新打包后各点一次确认（见手动测试 M-25）。

## 3. Windows 风险清单

「本轮」= 这三轮改到的代码；「原有」= 没改、但在 Windows 上值得验证的地方。行号以 `claude/review-fixes` 为准（代码和 `claude/low-fixes` @ 0bc5178 完全相同）。

| 编号 | 风险 | 位置 | 说明 | 验证方法 |
|---|---|---|---|---|
| R-01 | 中文文件夹 / 文件名 | `output.py:42`（`_safe_name`）、`output.py:57`（`save_png`） | 游戏名（「原神」、yuzu 的 ROM 标题）直接做文件夹名和文件名开头。pathlib 走 Windows 的宽字符 API，本身没问题；本轮加了保留名、控制字符、80 字符截断 | 手动 M-13、M-22；quick 的 safe_name、yuzu_naming |
| R-02 | 路径超过 260 个字符 | `output.py:39`（`MAX_NAME = 80`） | 按「截图根目录不超过约 60 个字符」估的。`save_dir` 很深时，长游戏名仍可能超 260（打包版是否启用长路径取决于 PyInstaller 清单） | 把 `save_dir` 设成一个约 100 个字符的中文路径，用名字约 80 个字符的游戏截图，看能否保存 |
| R-03 | 「图片」文件夹被迁移 / OneDrive | `output.py:21`（`pictures_dir`）、`output.py:33` | 用 `SHGetKnownFolderPath` 找真实位置（本机是 `D:\00AustinDocuments\图片`） | `save_dir` 留空时截一张，确认在 `D:\00AustinDocuments\图片\GameShots\<游戏名>\` |
| R-04 | PNG 元数据里的中文 | `output.py:69`（`info.add_text`） | Pillow 遇到非 latin-1 的文字会改写成 iTXt。元数据里有 `game=原神` | `& $py -c "from PIL import Image; print(Image.open(r'<截图路径>').text)"`，看到完整中文 |
| R-05 | config.json 的编码 | `config.py:111`（读 utf-8-sig）、`config.py:172-173`（写 utf-8） | 记事本「ANSI」（GBK）存的中文配置会解码失败，走 H2 的另存流程；带 BOM 的 UTF-8 现在能读 | 手动 M-01、M-02；**额外**：用记事本把配置另存为 ANSI，启动后应有 `config.unreadable_*.json` 和日志，游戏名单回到默认 |
| R-06 | 日志、崩溃日志的编码 | `main.py:580`（RotatingFileHandler utf-8）、`main.py:593`（crash.log utf-8） | 用 PowerShell 读时要指定编码 | `Get-Content -Encoding UTF8 $env:APPDATA\GameSnap\gamesnap.log` 中文正常 |
| R-07 | svcl.exe 输出的编码 | `dualsense.py:149`（按 `mbcs` 解码） | 中文 Windows 是 936 代码页。本轮没改 | dualsense 测试照旧通过即可；不要手动触发改设置 |
| R-08 | 文件被占用时保存配置 | `config.py:163-182`（`save`）、`main.py:142`（`on_save_error`） | 杀毒软件、同步盘短暂占用时 `os.replace` 抛 PermissionError；现在重试 5 次（约 1 秒），仍失败只提示 | 手动 M-15（用 PowerShell 独占打开 config.json） |
| R-09 | `os.replace` 原子写入 | `config.py:174`、`output.py:74`（`Path.replace`） | Windows 上是 `MoveFileExW(MOVEFILE_REPLACE_EXISTING)`：同一个卷上原子；目标被别的进程不带 FILE_SHARE_DELETE 打开时失败。`.tmp` / `.png.part` 和目标总在同一文件夹，不会跨卷 | M-15；再把 `save_dir` 放到 OneDrive 同步的文件夹里连拍 10 张，确认没有残留 `.png.part`、没有「截图失败」 |
| R-10 | 删 `.png.part` 时它也被占用 | `output.py:75-77`（本轮 L11） | `unlink(missing_ok=True)` 只忽略「不存在」，被占用会抛 PermissionError，盖掉原来的异常（finish_shot 照样提示「截图失败」，日志里的异常换成了删除失败的那个） | 只能人为制造：截图过程中用 PowerShell 独占打开 `.png.part`，难度大，可以只看代码确认 |
| R-11 | **原有：第二个实例启动时删 crash.log** | `main.py:591-592`，在 `main.py:642` 的单实例检查之前执行 | crash.log 超过 1 MB 时，新启动的实例会先 `unlink` 它；旧实例正开着这个文件（faulthandler），Windows 上删不掉，抛 PermissionError，新实例还没检查单实例就崩了（打包版没有控制台，看不到报错）。影响接管（M8）和「已经在运行了」提示 | 退出 GameSnap，把 `crash.log` 补到 1 MB 以上（先备份），启动一个实例，再点另一个快捷方式：看第二个是否无声消失、`gamesnap.log` 里有没有它的记录。见「已知问题」 |
| R-12 | **原有：两个进程同时写日志、日志轮转** | `main.py:580`（`RotatingFileHandler`，1 MB 轮转） | 接管或「已在运行」时两个进程短暂同开 gamesnap.log；轮转要改名，另一个进程开着时会失败，这段时间的日志会丢 | 日志接近 1 MB 时做一次接管（M-10），看日志是否连续 |
| R-13 | 多进程 / 子进程 | `main.py:567-573`（`relaunch_as_admin`，ShellExecute runas）、`main.py:611`（`launch`）、`dualsense.py:145`（svcl，CREATE_NO_WINDOW）、`main.py:97`（Saver 是线程池，不是进程） | 项目没用 multiprocessing，所以打包版不需要 `freeze_support`。提权是重新启动自己，参数用 `list2cmdline` 拼接 | 手动 M-25（从带「以管理员身份运行」的快捷方式启动，日志第一行「管理员权限：True」，任务管理器里只有一个 GameSnap） |
| R-14 | 单实例接管（本轮 M8） | `instance.py:88`（`_announce`）、`instance.py:113-125`（`take_over` 重试）、`instance.py:134`（`serve`）、`main.py:187`、`main.py:658` | 命名对象在 `Local\` 下、用「所有人、低完整性」的安全描述符（L19）；接管靠 Quit 事件 + 等互斥体 | 手动 M-10；quick 的 instance_quit 只用了假 kernel32 |
| R-15 | 删除方式 | `output.py:76`（`.png.part`）、`main.py:592`（crash.log） | 程序只直接删除自己的临时文件和超大的 crash.log，不进回收站；从不删截图。「移除游戏」只改 config.json | 手动 M-19：移除游戏后，它的截图文件夹还在 |
| R-16 | .bat 编码 | 仓库里没有 | 如果你自己写 .bat 跑测试：中文路径和输出在 936 代码页下会乱码。建议直接用 PowerShell（第 4 节），或在 .bat 开头 `chcp 65001` 并存成 UTF-8；Python 一律加 `-X utf8` | — |
| R-17 | 高 DPI 缩放 | `main.py:34`（`SetProcessDpiAwareness(2)`，每个显示器单独感知）、`toast.py:80`（`_dpi_scale`）、`toast.py:225-228`、`capture.py:74`（`monitor_of_window`） | 浮层按游戏所在显示器的 DPI 放大；卡片缓存的键里带 scale（P3），不同 DPI 的显示器各画各的 | 手动 M-21（100% / 150% 缩放、两块不同缩放的显示器） |
| R-18 | 低级键盘钩子 | `hotkey.py:226`（`_kb_proc`）、`hotkey.py:237`（`_handle_key`） | 回调超时会被系统静默摘掉（`LowLevelHooksTimeout`，Q2）；管理员权限的游戏要 GameSnap 也是管理员才收得到 | 手动 M-04、M-06；日志里不应出现「键盘钩子出错」 |
| R-19 | 按住 / 自动重复（本轮 L1） | `hotkey.py:43`（`HELD_STALE_SEC = 1.5`）、`hotkey.py:254`、`hotkey.py:148`、`hotkey.py:153` | 系统按键重复延迟最长 1 秒，所以 1.5 秒的阈值不会把真按住误判成新按下；依赖 `QPC_FREQ`（capture.py） | 手动 M-06：控制面板把「重复延迟」调到最长，按住截图键 5 秒只截一张 |
| R-20 | 扩展键显示名（本轮 L4） | `hotkey.py:102`（`key_name`）、`hotkey.py:111` | `MAPVK_VK_TO_VSC_EX` 需要 Vista 以上，本机没问题 | 手动 M-07 |
| R-21 | 鼠标侧键（Raw Input） | `hotkey.py:270`（`_refresh_raw`）、`hotkey.py:273`（`_set_raw`）、`hotkey.py:283` | H1 修复前，监听重建后 Raw Input 的登记会按旧对象的状态做 | 手动 M-04 最后一步；quick 的 listener_restart |
| R-22 | 前台切换事件（本轮 L3） | `hotkey.py:183-187` | 失败时只记警告，截图键照样能用 | 日志里正常不应有「SetWinEventHook 失败」 |
| R-23 | 监听启动失败（本轮 M4） | `hotkey.py:166`（`wait_ready`）、`hotkey.py:192`、`main.py:239`（`_sync_listener`） | 失败时提示「按键监听没启动起来」；只是启动慢（超过 2 秒）的照旧留着 | 实机很难触发；quick 的 listener_start_fail 用的是真 InputListener |
| R-24 | WGC / D3D 显卡（本轮 M1、L5、L6、L9） | `capture.py:167`、`capture.py:133`、`capture.py:154`、`d3d.py:113`、`d3d.py:177` | 本机是 AMD 核显驱动显示器 + NVIDIA 独显；设备只建在核显上 | 手动 M-09；日志里每张截图的后端应是 `wgc`，不应有「换下这个会话」 |
| R-25 | 剪贴板 | `output.py:81-104`（本轮 P1、L10） | 剪贴板管理器（Ditto 等）或远程桌面可能占着剪贴板 | 手动 M-17 |
| R-26 | 托盘线程安全（本轮 M6，Q1 未解决） | `main.py:462`（`refresh_tray`）、`main.py:162` | 菜单开着时别的线程 `update_menu` 会 DestroyMenu 正在显示的菜单（Q1） | 手动 M-11 |
| R-27 | 提示浮层的字体 | `toast.py:92-93`（`_font`，msyh.ttc → msyhbd → simhei → segoeui） | Windows 自带微软雅黑，一般没问题 | 浮层中文显示正常、不是方块 |
| R-28 | 进程检测失败（本轮 L15） | `watcher.py:81-92`（`_pids`）、`watcher.py:95-103`（`scan`） | 失败时跳过这一轮；如果某台机器上 EnumProcesses 一直失败，会每 2 秒记一条「进程检测出错」 | 正常运行时日志里不应有「进程检测出错」 |

## 4. 本地自动测试步骤（Windows PowerShell）

**必须用 `D:\anaconda3\envs\gamesnap-build` 这个 conda 环境**：test_add_live.py:25、test_lifecycle.py:19、test_remove_live.py:21
把这个解释器路径写死了，另建的 venv 跑不了这 3 个测试；run_tests.py 也按这个环境检查。

```powershell
# ---- 0. 取代码 ----
$proj = "D:\0_my_projects\anthropic_claude_code\game_snap"
Set-Location $proj
git status                      # 确认没有未提交的改动（not_games.py 是 skip-worktree，三轮都没改它，切分支不受影响）
git fetch origin
git switch claude/review-fixes  # 本地还没有这个分支时，git 会自动跟踪 origin/claude/review-fixes
git pull origin claude/review-fixes
git log --oneline -5            # 应能看到「合并 claude/medium-fixes 到 claude/review-fixes」

# ---- 1. 环境（已有 gamesnap-build 就跳过 create） ----
D:\anaconda3\Scripts\conda.exe env list
D:\anaconda3\Scripts\conda.exe create -y -p D:\anaconda3\envs\gamesnap-build python=3.12
$py = "D:\anaconda3\envs\gamesnap-build\python.exe"
& $py --version                 # 3.12.x

# ---- 2. 依赖 ----
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt
& $py -m pip show pillow        # 记下版本（02-findings M9：10.1–12.3 有已知漏洞）
& $py -m pip check

# ---- 3. quick（不启动 GameSnap，约半分钟） ----
Get-Process GameSnap -ErrorAction SilentlyContinue      # 有输出就先从托盘退出
& $py -X utf8 tests\run_tests.py --out build\test_runs\handoff_quick
Get-Content -Encoding UTF8 build\test_runs\handoff_quick\summary.txt
# 预期：31 passed。DualSense 插着但不是四声道时 dualsense 会失败（绊线拦下了一次改设置，不是程序坏了，见 tests\README.md）

# ---- 4. 打包前备份当前 dist（CLAUDE.md：大改前备份，并在 README「旧版备份」记一笔） ----
Get-Process GameSnap -ErrorAction SilentlyContinue      # 必须没在运行，否则打包会失败或换掉正在用的版本
$bk = "backup\v5_review_fixes"
New-Item -ItemType Directory -Force $bk | Out-Null
Copy-Item -Recurse dist\GameSnap "$bk\GameSnap"
git archive --format=zip -o "$bk\source_main.zip" origin/main   # 改动前的源码

# ---- 5. 打包 ----
& $py build.py
Test-Path dist\GameSnap\GameSnap.exe                    # True

# ---- 6. all（约 3 分钟，会真的启动 GameSnap） ----
& $py -X utf8 tests\run_tests.py all --out build\test_runs\handoff_all
Get-Content -Encoding UTF8 build\test_runs\handoff_all\summary.txt
# 预期：36 passed（31 个 quick + 5 个 SLOW）
```

**从 Claude 桌面应用里让 Claude 跑 all** 时，要在 MSIX 容器外启动（否则 %APPDATA% 会被重定向），用 tests\README.md 里的写法：

```powershell
$proj = "D:\0_my_projects\anthropic_claude_code\game_snap"
$out = "$proj\build\test_runs\handoff_all"
$cmd = "`"D:\anaconda3\envs\gamesnap-build\python.exe`" -X utf8 `"$proj\tests\run_tests.py`" all --out `"$out`""
$p = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine=$cmd; CurrentDirectory=$proj}
Wait-Process -Id $p.ProcessId -Timeout 600
Get-Content -Encoding UTF8 "$out\summary.txt"
```

**可选：确认 H1 真的存在过**（listener_restart 在修复前的 main 上，第二个监听那一项应该失败）：

```powershell
git worktree add ..\game_snap_main origin/main
Copy-Item tests\test_listener_restart.py ..\game_snap_main\tests\
& $py -X utf8 ..\game_snap_main\tests\test_listener_restart.py build\test_runs\h1_before
git worktree remove ..\game_snap_main
```

**可选：基准**（只测量，不判对错）：`& $py -X utf8 tests\bench_logic.py 5`、`& $py -X utf8 tests\bench_startup.py build\test_runs\bench_startup`。

某个测试失败时，看 `build\test_runs\<out>\<测试名>.txt`。如果是新加的测试，先判断是**测试的桩在 Windows 上不适用**（见第 2 节）还是**代码真的有问题**，不要为了通过去改已有测试的断言。

## 5. 手动测试清单

**准备**

1. 从托盘退出 GameSnap。按 CLAUDE.md 在容器外把真实配置备份到 `backup\before_handoff\config.json`。
2. 涉及配置的测试（M-01–M-03、M-15）用测试目录，不碰真实的 `%APPDATA%\GameSnap`：

   ```powershell
   $env:APPDATA = "D:\0_my_projects\anthropic_claude_code\game_snap\build\test_runs\manual\appdata"
   New-Item -ItemType Directory -Force "$env:APPDATA\GameSnap" | Out-Null
   # 测试配置：把记事本当游戏，截图键用默认的 `
   '{"games": {"Notepad.exe": "记事本测试"}, "launchers": [], "save_dir": "D:\\0_my_projects\\anthropic_claude_code\\game_snap\\build\\test_runs\\manual\\shots", "dualsense_quad": false}' |
     Set-Content -Encoding utf8 "$env:APPDATA\GameSnap\config.json"
   & $py main.py --no-elevate --console
   ```

   这个 PowerShell 窗口里的 `$env:APPDATA` 只影响从它启动的进程，关掉窗口就恢复。没开记事本时，GameSnap 60 秒后会按规则自动退出
   （`wait_no_launcher_sec`），测完一项重新运行最后一行即可。
3. 涉及真实游戏的测试（M-06、M-09、M-10）用打包版和真实配置。

| 编号 | 对应 | 操作 | 预期结果 |
|---|---|---|---|
| M-01 | H2 | 在测试配置的 `games` 里多加一个逗号，启动 | 日志有「配置文件读取失败」和「读不出来的配置文件另存为 …config.unreadable_<时间>.json」；切一下托盘「截图声音」后 config.json 变回默认，备份里还有 `Notepad.exe` |
| M-02 | H2 | 用记事本把测试配置另存为「UTF-8 带 BOM」，启动，打开记事本 | 托盘变成「工作中：记事本测试」，没有任何备份文件 |
| M-03 | M5 | 测试配置里写 `"poll_interval_sec": 0, "sound": "yes"`，启动 | 日志有两条「配置项 … 不合法」，有 `config.invalid_<时间>.json`；任务管理器里 GameSnap 的 CPU 接近 0（不忙等）；其余设置照常生效 |
| M-04 | H1 | 不开记事本，托盘「添加游戏…」，等 15 秒超时；然后打开记事本，按 `；再托盘「更换截图键…」，按鼠标侧键 | 截到一张记事本；提示「截图键已设为 鼠标侧键（…）」；之后在记事本里按侧键能截图，日志没有「监听窗口消息处理出错」 |
| M-05 | M7 | 不开记事本，托盘「更换截图键…」，什么都不按 | 10 秒后提示「已取消更换截图键」；之后再过 `wait_no_launcher_sec`（默认 60 秒）GameSnap 自动退出 |
| M-06 | L1 | 在游戏（或记事本）里：①按住截图键 5 秒；②按住截图键时按 Ctrl+Alt+Del，取消回来，松开，再按一次 | ①只截一张；②回来后那一下照样截图（以前会被吞掉、不截） |
| M-07 | L4 | 托盘「更换截图键…」，分别按 Insert、→、Home | 提示和托盘菜单显示的是这几个键自己的名字（如「Insert」「Right」「Home」，具体文字取决于键盘布局），不是「Num 0」「Num 6」「Num 7」。测完改回 ` |
| M-08 | L2 | 托盘「更换截图键…」，在第 10 秒左右按一个键 | 只出现一条提示（「截图键已设为 …」或「已取消更换截图键」二选一），config.json 和提示一致 |
| M-09 | M1、L5、L9 | 游戏里截一张；把游戏从窗口切到全屏（或改分辨率）；再截一张 | 第二张尺寸是新分辨率；日志有「画面尺寸变为 …，重建帧池」；两张的后端都是 `wgc`，没有「换下这个会话」 |
| M-10 | M8 | 先点「云·原神 + 截图」（`--no-elevate`），1 秒内再点「米哈游启动器 + 截图」（管理员）并同意 UAC | 只剩一个托盘图标；新实例日志有「正在运行的 GameSnap 没有管理员权限 … 由本实例接管」和「管理员权限：True」；旧实例日志有「自动退出：由新启动的 GameSnap（管理员权限）接管」；托盘「退出」能退出 |
| M-11 | M6、Q1 | 连按截图键 10 次；再在游戏退出的同时打开托盘菜单 | 托盘图标一直正确（工作中是绿色，退出后变灰），提示文字的张数对；菜单不失效、不崩（Q1 观察结果记下来） |
| M-12 | M3 | 无法手动触发（要耗尽 GDI 资源） | 只靠 quick 的 toast_gdi；记「⏭」 |
| M-13 | M2 | 测试配置里把记事本的显示名改成 `CON`，截一张；再改成 `..`，截一张 | 截图分别在 `shots\_CON\` 和 `shots\未知游戏\`，不在 `shots` 的上一级 |
| M-14 | L10 | 如果平时用剪贴板管理器（Ditto 等），开着它连拍几张；没有就记「⏭」 | 每张都提示「已截图」；万一没复制上，日志里是「写剪贴板失败（截图已保存）」或「剪贴板一直被占用」，不是「保存截图失败」 |
| M-15 | L18 | 在另一个 PowerShell 里执行 `$f = [IO.File]::Open("$env:APPDATA\GameSnap\config.json", 'Open', 'Read', 'None')`（同一个测试 APPDATA），然后托盘切「截图声音」；再 `$f.Close()`，再切一次 | 第一次约 1 秒后提示「设置没保存上（config.json 被占用），详见日志」，菜单勾选照样变了；关闭后再切，config.json 里是新值 |
| M-16 | L11 | 可选：把 `save_dir` 指到一个快满的 U 盘，连拍到满 | 提示「截图失败」；文件夹里没有 `.png.part` |
| M-17 | P1、L12 | 截一张，打开画图粘贴 | 粘贴出的图和 PNG 一样（尺寸、颜色） |
| M-18 | P2、P3 | 观察托盘图标三种状态和截图提示 | 等待是灰色、工作中是绿色、暂停是橙色，和以前一样；提示出现得不比以前慢 |
| M-19 | L17、R-15 | 开着记事本：托盘「添加游戏…」后切到另一个程序按截图键把它加进来，紧接着在「游戏名单」里移除另一项（很难真正同时，主要看两边的改动都留下） | config.json 里新加的在、移除的不在；被移除游戏以前的截图文件夹还在 |
| M-20 | L16 | 不开游戏，托盘「添加游戏…」，等超时 | 超时后不会立刻退出，而是再等 `wait_no_launcher_sec` |
| M-21 | 高 DPI（R-17） | 系统缩放设 150%，截一张；有两块显示器时把游戏放到缩放不同的那块再截 | 浮层在游戏所在显示器右上角、文字清晰、不进截图；截图是物理分辨率 |
| M-22 | R-01、R-02 | 测试配置 `save_dir` 设成 `D:\测试 截图\一层\二层`，截图 | 能保存，文件夹和文件名中文正常 |
| M-23 | R-11 | 退出 GameSnap，备份并把 `crash.log` 补到 1 MB 以上，启动一个实例，再点另一个快捷方式 | **已知风险**：第二个实例可能无声消失。记下实际表现，决定是否要修（见第 6 节） |
| M-24 | R-04 | 截图后读 PNG 元数据（见 R-04 的命令） | `GameSnap` 一项里有 `game=<中文游戏名>`、`backend=wgc` |
| M-25 | R-13、快捷方式 | 重新打包后，桌面 3 个快捷方式各点一次（游戏启动后再退出） | 带管理员的弹 UAC、日志「管理员权限：True」；`--no-elevate` 的不弹；游戏和启动器都关掉后按规则自动退出 |
| M-26 | 资源占用 | 等待进游戏时和游戏中，看任务管理器的内存 | 和 README「资源占用」一节的数字相近，没有明显上涨 |

## 6. 已知问题

**标为跳过的发现**

| 编号 | 问题 | 跳过原因 |
|---|---|---|
| M9 | `requirements.txt` 允许 Pillow 10.1–12.3，这些版本有已知高危漏洞 | 要升到 13.x，大版本升级，RUNBOOK 不允许；GameSnap 不打开外来图片，实际可利用性低。先 `pip show pillow` 看实际版本再决定 |
| L7 | 换下的截图会话 / 设备没有上限 | 修复风险过大：要定「连续失败几次就放弃 WGC」或冷却时间，放弃后独占全屏截出来是黑的；参数要在 Windows 上模拟驱动重置才能定 |
| L8 | `_gpu_for` 一次失败就永久改用 GDI | 同 L7，和 L7 是同一个重试策略问题 |
| P4 | `save_png` 压缩级别（最大热点，约 220 ms） | 改压缩级别会改变输出文件，需要你决定 |
| L19–L21 | 安全一节：命名对象对所有人开放、管理员进程用普通用户可写的文件、CLAUDE.md 里有个人路径 | 不在这三轮的范围内，见 02-findings「安全」 |
| Q1–Q9 | 待人工确认 | 都要在 Windows 上复现或查资料，见 02-findings「待人工确认」 |

**修了但没照建议全做的部分**

| 编号 | 没做的部分 | 原因 |
|---|---|---|
| H2 | 读不出来时禁止覆盖、弹窗提醒 | 改变交互，留给你决定 |
| M2 | `strip(" .")` | 会改掉以前能用的名字（如 `.hack`），截图换文件夹 |
| M4 | 按轮询自动重建监听 | 一直失败时每 2 秒一条日志加一次提示，太吵 |
| M5 | `_get_interval()` 挪进 try | 值在加载时已保证合法 |
| M6 | 菜单显示中被 DestroyMenu（Q1） | pystray 显示菜单不经过这把锁 |
| M7 | `self.games` 的赋值挪进锁 | 不需要（PROGRESS D15） |
| L1 | `_held_vk` | `_held` 只跟踪绑定键，换键时清掉就够了（D24） |
| L13 | 缓存字体对象 | 每个字号常驻 +3.5 MB，改为缓存卡片（D9） |

**写本文时新发现、没改的 Windows 风险**（都是原有代码，不是这三轮引入的）

- R-11：crash.log 超过 1 MB 时，第二个实例启动就崩（`main.py:591-592` 在单实例检查之前删文件）。可能的修法：删除失败时忽略，或挪到单实例检查之后。
- R-12：两个进程同时写 gamesnap.log 时，轮转可能失败、丢日志。
- R-10：`.png.part` 也被占用时，删除失败的异常会盖掉原来的异常（只影响日志内容）。

**测试本身的限制**：26 个新测试从没在 Windows 上跑过（第 2 节）；instance_quit、toast_gdi 等用假的 Win32 函数，只验证逻辑，不验证真实 API 的行为。

## 7. 结果记录模板

结果填 ✅ 通过 / ❌ 失败 / ⏭ 没测（写原因）。失败时把 `build\test_runs\<out>\<名字>.txt` 或 gamesnap.log 里的关键几行贴到「报错信息」。

**环境**：Windows 版本 ______；`pip show pillow` 版本 ______；显示器缩放 ______；测试日期 ______；分支 / commit ______

| 编号 | 项目 | 结果 | 报错信息 / 备注 |
|---|---|---|---|
| E-01 | 依赖安装（`pip install -r requirements.txt`、`pip check`） | | |
| A-01 | quick：not_games | | |
| A-02 | quick：toast_card | | |
| A-03 | quick：toast_gdi | | |
| A-04 | quick：config | | |
| A-05 | quick：config_values | | |
| A-06 | quick：add_game | | |
| A-07 | quick：tray_icon | | |
| A-08 | quick：tray_refresh | | |
| A-09 | quick：blocklist_remove | | |
| A-10 | quick：yuzu_naming | | |
| A-11 | quick：safe_name | | |
| A-12 | quick：clipboard | | |
| A-13 | quick：capture_resize | | |
| A-14 | quick：dualsense | | |
| A-15 | quick：listener_restart | | |
| A-16 | quick：listener_sync | | |
| A-17 | quick：listener_start_fail | | |
| A-18 | quick：instance_quit | | |
| A-19 | quick：clipboard_error | | |
| A-20 | quick：save_png_fail | | |
| A-21 | quick：scan_fail | | |
| A-22 | quick：idle_order | | |
| A-23 | quick：learn_race | | |
| A-24 | quick：games_update | | |
| A-25 | quick：config_save_fail | | |
| A-26 | quick：held_key | | |
| A-27 | quick：key_name | | |
| A-28 | quick：win_event_hook | | |
| A-29 | quick：d3d_staging | | |
| A-30 | quick：d3d_release | | |
| A-31 | quick：session_init_fail | | |
| B-01 | 打包 `build.py`（有无警告） | | |
| A-32 | all：lifecycle_source | | |
| A-33 | all：add_live | | |
| A-34 | all：remove_live | | |
| A-35 | all：lifecycle_exe | | |
| A-36 | all：multi_exit | | |
| A-37 | 可选：H1 修复前的 listener_restart 应失败 | | |
| M-01 | H2 配置多逗号 | | |
| M-02 | H2 带 BOM | | |
| M-03 | M5 不合法的值 | | |
| M-04 | H1 添加游戏后截图、侧键 | | |
| M-05 | M7 学键超时后自动退出 | | |
| M-06 | L1 按住 / 安全桌面 | | |
| M-07 | L4 扩展键显示名 | | |
| M-08 | L2 第 10 秒按键 | | |
| M-09 | M1 改分辨率后截图 | | |
| M-10 | M8 管理员实例接管 | | |
| M-11 | M6 连拍 / 托盘菜单（Q1） | | |
| M-12 | M3（无法手动触发） | ⏭ | 只靠 toast_gdi |
| M-13 | M2 保留名 / `..` | | |
| M-14 | L10 剪贴板被占用 | | |
| M-15 | L18 config.json 被占用 | | |
| M-16 | L11 磁盘满（可选） | | |
| M-17 | P1 剪贴板内容 | | |
| M-18 | P2 / P3 图标和提示 | | |
| M-19 | L17 添加和移除同时 | | |
| M-20 | L16 添加超时后不立刻退出 | | |
| M-21 | 高 DPI / 多显示器 | | |
| M-22 | 中文深路径 | | |
| M-23 | R-11 crash.log 超大时的第二个实例 | | |
| M-24 | PNG 中文元数据 | | |
| M-25 | 三个快捷方式 | | |
| M-26 | 资源占用 | | |
