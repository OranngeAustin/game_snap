# GameSnap 测试

全部用 `D:\anaconda3\envs\gamesnap-build\python.exe` 运行。测试不改系统设置（DualSense 的写操作换成了一调用就报错的绊线），不发真实按键，不启动你的游戏和软件；配置、日志、截图都写在 `build\test_runs\` 下，不碰真实的 `%APPDATA%\GameSnap\`。假游戏、假启动器是改了名的 ping.exe 副本。

## 一次跑完

在 `game_snap` 文件夹里：

```
D:\anaconda3\envs\gamesnap-build\python.exe -X utf8 tests\run_tests.py
D:\anaconda3\envs\gamesnap-build\python.exe -X utf8 tests\run_tests.py all
D:\anaconda3\envs\gamesnap-build\python.exe -X utf8 tests\run_tests.py add_game remove_live
```

- 不带参数（quick）：进程内的测试，约半分钟，不启动 GameSnap。
- `all`：再加上真的启动 GameSnap 的测试（源码版和打包版），约 3 分钟。先退出正在运行的 GameSnap；改了源码要先重新打包，打包版测试测的是 `dist\GameSnap\`。
- 也可以只写要跑的测试名（见下表）。

结果在 `build\test_runs\suite_<日期>_<时间>\summary.txt`（`--out <文件夹>` 可以指定位置），每个测试的输出在同一文件夹的 `<名字>.txt` 和 `<名字>\` 里。有测试没过时退出码为 1。

从 Claude 里跑 `all` 时，要在 MSIX 容器外启动（见 CLAUDE.md），例如：

```powershell
$proj = "D:\0_my_projects\anthropic_claude_code\game_snap"
$out = "$proj\build\test_runs\suite_manual"
$cmd = "`"D:\anaconda3\envs\gamesnap-build\python.exe`" -X utf8 `"$proj\tests\run_tests.py`" all --out `"$out`""
$p = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine=$cmd; CurrentDirectory=$proj}
Wait-Process -Id $p.ProcessId -Timeout 600
Get-Content -Encoding UTF8 "$out\summary.txt"
```

## 各个测试

| 名字 | 文件 | 测什么 |
|---|---|---|
| not_games | test_not_games.py | 黑名单格式正确，没拦本机的游戏、模拟器和运行环境 |
| toast_card | test_toast_card.py | 提示卡片在多组文字、成败、缩放下的像素逐字节不变（云端 Linux 也能跑） |
| toast_gdi | test_toast_gdi.py | 提示浮层画卡片时 GDI 调用失败（GetDC、CreateCompatibleDC、CreateDIBSection 返回 NULL）：不写 0 地址、不显示、不留下半截的 DC，屏幕 DC 总会还回去。user32 / gdi32 换成假的，不显示窗口（纯 Python，云端 Linux 也能跑） |
| config | test_config.py | config.json 读写：没有文件时写默认配置、浅合并、读不出来时先另存一份再用默认配置（纯 Python，云端 Linux 也能跑） |
| config_values | test_config_values.py | config.json 里的值类型不对、超出范围（轮询间隔 0 或 null、games 为 null、截图键写坏等）：回退默认值并记日志，games / launchers 只去掉不对的项，先另存原文件；合法的值（含边界值、0 / 1 当开关）一个不改（纯 Python，云端 Linux 也能跑） |
| add_game | test_add_game.py | 「添加游戏…」：提示、拒收、加入、已在名单、超时、和「更换截图键…」互斥、按键和超时同时到；`--launch` 支持链接 |
| tray_icon | test_tray_icon.py | 托盘图标三种状态的像素逐字节不变、每次返回新对象（云端 Linux 也能跑） |
| tray_refresh | test_tray_refresh.py | 多个线程同时刷新托盘：换图标不交叠、晚到的线程不会用旧状态盖掉新状态、图标状态没变不重设（菜单和提示文字照样更新）。不建托盘图标（纯 Python，云端 Linux 也能跑） |
| blocklist_remove | test_blocklist_remove.py | 黑名单拦截和放行的样例；「游戏名单」移除：确认、取消、过期的菜单项、名字带 `&`、空名单、原生 Win32 菜单 |
| yuzu_naming | test_yuzu_naming.py | yuzu 截图按窗口标题里的游戏名分文件夹；跨进程读标题；文件名里的非法字符 |
| clipboard | test_clipboard.py | 复制到剪贴板的数据（CF_DIB）逐字节不变、不改原图、剪贴板被占用时的重试；剪贴板换成假的，不碰真剪贴板（云端 Linux 也能跑） |
| capture_resize | test_capture_resize.py | 游戏改分辨率后截图会话按新尺寸重建帧池：用假的 WinRT 帧（关闭后读尺寸就报错）走一遍，不抛异常、只重建一次、旧帧都关掉。不碰 WGC / D3D（纯 Python，云端 Linux 也能跑） |
| safe_name | test_safe_name.py | 游戏名变成文件夹名 / 文件名：以前能用的名字不变；只有点（`..` 不会写到根目录外面）、控制字符、Windows 保留名、超过 80 个字符的名字照规则处理（纯 Python，云端 Linux 也能跑） |
| dualsense | test_dualsense.py | DualSense 四声道守护的判断逻辑；只读真实注册表；守护线程（有绊线，不会真改） |
| listener_restart | test_listener_restart.py | 按键监听停了再建（游戏关了又开、添加游戏 / 更换截图键前后）：新监听窗口的消息送到它自己，而不是第一个、已停掉的监听；会真的挂一会儿键盘钩子（F24、不拦任何键）。非 Windows 上打印 SKIP |
| listener_sync | test_listener_sync.py | 按键监听该挂还是该摘：游戏退出的同时点「更换截图键…」「添加游戏…」，或者学键 / 添加结束的同时检测到游戏，监听都不能被错摘（学键要能超时结束、之后能自动退出）。把线程交错固定下来重放，不靠运气；不挂钩子（纯 Python，云端 Linux 也能跑） |
| listener_start_fail | test_listener_start_fail.py | 按键监听启动失败（建窗口 / 挂钩子出错）：wait_ready() 返回 False；App 不留下死掉的监听、提示一次、之后需要时重建；更换截图键 / 添加游戏立即复位不卡住；只是启动慢的照旧留着。真的 InputListener 那一项把建窗口换成报错，不挂钩子（纯 Python，云端 Linux 也能跑） |
| instance_quit | test_instance_quit.py | 单实例的退出信号：拿到互斥体就建好、serve() 之前收到的信号不丢、接管时对方信号晚到会重试、接管后清掉残留信号；App 托盘就绪后才开始等信号，_quit 中途出错也让托盘退出。kernel32 换成假的，不建真的命名对象、不影响正在运行的 GameSnap（纯 Python，云端 Linux 也能跑） |
| clipboard_error | test_clipboard_error.py | 写剪贴板时 EmptyClipboard / SetClipboardData 出错：copy_to_clipboard 返回 False 不抛异常、剪贴板照样关上；finish_shot 仍提示「已截图」、计数加一。假剪贴板（纯 Python，云端 Linux 也能跑） |
| save_png_fail | test_save_png_fail.py | save_png 写到一半失败（磁盘满）：异常照常抛出、不留下 .png.part；之后照常保存（纯 Python，云端 Linux 也能跑） |
| scan_fail | test_scan_fail.py | 进程检测失败（EnumProcesses 失败或返回 0 个、快照失败）：scan 抛异常而不是返回「没有游戏」，GameWatcher 跳过这一轮不回调。psapi 和快照是假的（纯 Python，云端 Linux 也能跑） |
| idle_order | test_idle_order.py | 更换截图键 / 添加游戏结束时先重置空闲起点、再清标志：在标志被清掉的那一刻轮询，不会用旧的空闲起点自动退出（纯 Python，云端 Linux 也能跑） |
| learn_race | test_learn_race.py | 更换截图键时按键和超时同时到：只有一个结果（不会既存了新键又提示「已取消」）。把线程交错固定下来重放（纯 Python，云端 Linux 也能跑） |
| games_update | test_games_update.py | 「添加游戏」和「移除游戏」同时改游戏名单：两边的改动都留下（内存和 config.json）。把线程交错固定下来重放（纯 Python，云端 Linux 也能跑） |
| config_save_fail | test_config_save_fail.py | 保存 config.json 时文件被短暂占用：重试后存上；一直占用时不抛异常、提示「设置没保存上」；更换截图键时保存失败，监听照样换新键、钩子照样摘、托盘照样刷新（纯 Python，云端 Linux 也能跑） |
| held_key | test_held_key.py | 截图键「按住」状态不会因为丢了抬起事件而卡住：隔 1.5 秒以上的按下当成新按下；换截图键、开始学键时清掉按住状态。直接调 _handle_key，不挂钩子（纯 Python，云端 Linux 也能跑） |
| key_name | test_key_name.py | 截图键的显示名：Insert / Delete / Home / End / PgUp / PgDn / 方向键显示自己的名字而不是小键盘键；小键盘、F24、字符键、鼠标侧键不变。user32 是假的（纯 Python，云端 Linux 也能跑） |
| win_event_hook | test_win_event_hook.py | 前台切换事件钩子（SetWinEventHook）挂不上时日志里有警告，监听照样启动；挂上时没有。user32 / 建窗口 / 消息循环都是假的（纯 Python，云端 Linux 也能跑） |
| d3d_staging | test_d3d_staging.py | 换暂存纹理时新建失败：旧纹理只释放一次、指针清零，之后能正常新建。d3d 的 COM 调用换成假的（纯 Python，云端 Linux 也能跑） |
| d3d_release | test_d3d_release.py | D3D 初始化的异常路径不漏 COM 对象：GetDesc1 抛错时释放这块显卡；取多线程保护接口抛错时释放刚建的 device / context；正常路径不多释放。DXGI / D3D11 换成假的（纯 Python，云端 Linux 也能跑） |
| session_init_fail | test_session_init_fail.py | 截图会话建到一半失败（建会话、start_capture 失败）：已建的帧池 / 会话不被 GC 关掉，异常照常抛出；正常建好不受影响。假的 WinRT 对象（纯 Python，云端 Linux 也能跑） |
| lifecycle_source、lifecycle_exe | test_lifecycle.py | 源码版 / 打包版走一遍：启动 → 检测到游戏 → 关游戏 → 自动退出 |
| add_live | test_add_live.py | 真程序里「添加游戏…」：等按键时不自动退出、超时、加入后马上生效、游戏关了再退出 |
| remove_live | test_remove_live.py | 真程序里移除正在运行的游戏：不再跟踪它，按规则自动退出 |
| multi_exit | test_multi_exit.py | 打包版：几个游戏和启动器按不同顺序关闭，全关掉才退出 |

辅助脚本，不单独运行：fake_window.py（子进程里的隐藏窗口）；gamesnap_tripwire.py、add_live_inner.py、remove_live_inner.py（打好补丁再启动 main.py）。

DualSense 插着但不是四声道时，dualsense 和 lifecycle_source 会失败：那是绊线拦下了一次真的改设置，不是程序坏了。

## 工具

- `list_not_games.py`：按分类打印黑名单，方便审查。
- `list_software.py <输出路径（不带扩展名）>`：列出本机装的软件和游戏库，用来更新 not_games.py 的 THIS_PC。要在容器外跑；输出里有你的软件和快捷方式名，写到 `%TEMP%` 下，不放进项目。之后用 `test_not_games.py <software.txt>` 可以看名单里哪些名字在清单里找不到。
- `bench_startup.py <run dir> [次数]`：测打包版的启动耗时，只测量，不判对错。
- `bench_logic.py [轮数] [--only 名字,…]`：测截图之后那段纯 Python / PIL 链路（make_icon、render_card、copy_to_clipboard、save_png 等）的耗时，每项报各轮中位数，只测量。剪贴板换成假的，不碰真剪贴板。Windows 和云端 Linux 都能跑。
- `winstubs.py`：不是测试。在非 Windows 上把 `ctypes.WinDLL`、`winsound`、`winreg` 换成桩，让项目模块能 import，好在云端 Linux 上测纯逻辑；在 Windows 上什么都不做。
