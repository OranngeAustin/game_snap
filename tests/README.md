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
| config | test_config.py | config.json 读写：没有文件时写默认配置、浅合并、读不出来时先另存一份再用默认配置（纯 Python，云端 Linux 也能跑） |
| add_game | test_add_game.py | 「添加游戏…」：提示、拒收、加入、已在名单、超时、和「更换截图键…」互斥、按键和超时同时到；`--launch` 支持链接 |
| blocklist_remove | test_blocklist_remove.py | 黑名单拦截和放行的样例；「游戏名单」移除：确认、取消、过期的菜单项、名字带 `&`、空名单、原生 Win32 菜单 |
| yuzu_naming | test_yuzu_naming.py | yuzu 截图按窗口标题里的游戏名分文件夹；跨进程读标题；文件名里的非法字符 |
| dualsense | test_dualsense.py | DualSense 四声道守护的判断逻辑；只读真实注册表；守护线程（有绊线，不会真改） |
| listener_restart | test_listener_restart.py | 按键监听停了再建（游戏关了又开、添加游戏 / 更换截图键前后）：新监听窗口的消息送到它自己，而不是第一个、已停掉的监听；会真的挂一会儿键盘钩子（F24、不拦任何键）。非 Windows 上打印 SKIP |
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
