# 审查与优化进度

按 [RUNBOOK.md](RUNBOOK.md) 执行。环境：claude.ai/code 云端会话（Ubuntu 容器，Python 3.12.3），
不是 Windows。用户 2026-11-03 补充：「云端环境实在无法测试的标注并跳过，能做的尽可能做」。

状态：✅ 完成 · 🔄 进行中 · ⏭ 跳过 · ⬜ 未开始

| 阶段 | 内容 | 状态 | 说明 |
|---|---|---|---|
| 0 | 准备：依赖、基线测试、分支、本文件 | ✅ | Linux 基线：quick 1 过 4 失败（环境），all 跑不起来；分支已推送 |
| 1 | 架构摸底 → 01-architecture.md | ✅ | 13 个模块、8 类线程；审查顺序 hotkey/winapi → d3d/capture → main → config → watcher → toast → output → instance/dualsense → build/not_games → tests |
| 2 | 代码审查 → 02-findings.md | ✅ | 3 个 code-reviewer 子代理分组审查 + 逐条核实：高 2、中 8、低 18、待确认 9；H2 已在 Linux 复现 |
| 3 | 安全审计 → 02-findings.md「安全」 | ✅ | 无注入、无不安全反序列化、无硬编码密钥；M9 Pillow 下限允许有已知漏洞的版本（可利用性低）；L19–L21 加固项 |
| 4 | 修复高危问题，PR → main | ✅ | H2 93f99bf、H1 d7b4f29；PR https://github.com/OranngeAustin/game_snap/pull/1 （未合并）；Linux 上失败数未增加，需回 Windows 验证 |
| 5 | 性能分析 → 03-perf-plan.md | ✅ | 新增 tests/bench_logic.py；每张截图 Python 侧约 247 ms，save_png 占 89% 但只能改输出提速（不选）；选 P1 剪贴板 DIB、P2 托盘图标缓存、P3 提示字体缓存 |
| 6 | 算法优化（前 3 项），PR → claude/review-fixes | ✅ | P1 剪贴板 -40%～-60%（#2）、P2 托盘图标 -99.8%（#3）、P3 提示卡片重复时 -99.9%（#4）；都先补特征测试，输出逐字节不变 |
| 7 | 总结 → 00-SUMMARY.md | ✅ | 00-SUMMARY.md：完成内容、PR #1–#4、跳过项、待人工确认、下一步建议 |

## 阶段 0：基线

### 依赖

环境安装脚本已建好 venv `~/.venvs/gamesnap`（Python 3.12.3）：mss 10.2.0、pillow 13.0.0、pystray 0.19.5、
python-xlib 0.33、six 1.17.0。requirements.txt 里其余的包（winrt-*、pywin32、pyinstaller）只有 Windows 版，
装不上，⏭ 跳过。

### 测试基线（2026-11-03，Linux 容器）

命令：`PYSTRAY_BACKEND=dummy ~/.venvs/gamesnap/bin/python -X utf8 tests/run_tests.py <quick|all>`

| 测试 | 结果 | 原因 |
|---|---|---|
| not_games | PASS | 不依赖 Windows（另用 `python3 -X utf8 tests/test_not_games.py` 也过：ALL PASSED） |
| add_game | FAIL（环境） | `AttributeError: module 'ctypes' has no attribute 'WinDLL'` |
| blocklist_remove | FAIL（环境） | `ModuleNotFoundError: No module named 'winsound'` |
| yuzu_naming | FAIL（环境） | `ModuleNotFoundError: No module named 'winsound'` |
| dualsense | FAIL（环境） | `ModuleNotFoundError: No module named 'winreg'` |
| all（SLOW 5 个） | 没跑起来 | run_tests.py 先 `from watcher import snapshot_names`，在 `ctypes.WinDLL` 处退出（rc=1） |
| bench_startup.py | ⏭ 跳过 | 测打包版 `dist\GameSnap\GameSnap.exe` 的启动耗时，只能在 Windows 上跑 |

**基线：quick 1 通过、4 失败（都是环境原因）；all 跑不起来。** 之后以「Linux 上失败数不增加、
not_games 保持通过」为标准；凡是只能在 Windows 上验证的改动，都在提交说明和 PR 里写明「需回 Windows 用
gamesnap-build 跑 quick / all」。

## 决策记录

- **D1 分支**：RUNBOOK 要求从 main 建 `claude/review-fixes`，会话默认分支是 `claude/sharp-archimedes-gb4cag`
  （与 main 同一提交 58c59fb）。按 RUNBOOK 和用户的 /goal 指令，在 `claude/review-fixes` 上工作并推送；
  建好后去掉了它对 origin/main 的 upstream，推送一律写全 `git push -u origin <分支>`，避免误推 main。
- **D2 测试环境**：Windows 专属测试在云端跑不了，按用户补充的指示标注「⏭ 跳过」而不是硬凑；
  为了让修复和优化在这里也有测试兜底，需要时写只用纯 Python 逻辑、把 Windows 模块换成桩的测试
  （见后续阶段），不改已有测试的断言。
- **D3 审查方式**：阶段 2 按 RUNBOOK 用 code-reviewer 子代理，分三组并行（hotkey/winapi/toast；d3d/capture/output；
  main/config/watcher/instance/dualsense），子代理只读。每条结论我都对照代码核实过；子代理和我各自得出的同一结论
  （H1、H2）注明「两个来源」。被核实推翻的（「HRESULT 不检查、把 NULL 传进驱动」）列在「已核对、没发现问题」。
- **D4 测试桩**：新增 `tests/winstubs.py`，只在非 Windows 上把 `ctypes.WinDLL` / `winsound` / `winreg` 换成桩，让项目模块能在
  Linux 上 import；Windows 上什么都不做。用它的测试只测纯逻辑。

## 阶段 4：修复记录

| 编号 | 提交 | 测试（Linux 容器） | Windows 验证 |
|---|---|---|---|
| H2 | 93f99bf | test_config 修复前 7 项失败 → 全过；quick 失败数 4 → 4 | 待做：quick |
| H1 | d7b4f29 | 只能确认能 import、类名各不相同；listener_restart 在 Linux 上 SKIP；quick 失败数 4 → 4 | 待做：quick（含 listener_restart）+ all |

- **D5 H1 的修法**：子代理提了两种：模块级常驻 WNDPROC 按 hwnd 分发，或每个窗口一个类名。选后者：改动最小（3 个文件、
  约 30 行），不引入新的全局状态；代价是每个监听多注册一个窗口类，窗口销毁后注销。
- **D6 H2 的修法**：只做「另存 + utf-8-sig」，不做「禁止覆盖 + 弹窗」：后者改变交互，留给用户决定（02-findings H2）。
- **D7 PR**：阶段 4 的 PR 就是 `claude/review-fixes → main`，审查文档和后续阶段的文档也在这个分支上，会一并出现在 PR 里。

- **D8 性能测量环境**：Windows 专属的热点（抓帧、托盘、进程快照）云端测不了，阶段 5 只测纯 Python / PIL 部分；
  render_card 用 wqy-zenhei.ttc 冒充 msyh.ttc，避免 Linux 上 Pillow 遍历字体目录把耗时放大。save_png 是最大热点，
  但提速要改压缩级别（改变输出文件），按「风险低」原则不进阶段 6，写进总结的建议。

## 阶段 6：优化记录

| 项 | 分支 / PR | 特征测试 | 基线中位数 | 优化后中位数 | 提升 | 结论 |
|---|---|---|---|---|---|---|
| P1 copy_to_clipboard | `claude/perf-clipboard-dib` / https://github.com/OranngeAustin/game_snap/pull/2 | test_clipboard.py（2203cab） | 13.65 / 12.45 ms | 5.09 / 7.40 ms | 约 -40%～-60%；4K 峰值 RSS -8 MB | ✅ 保留（方案 1；方案 2 getbuffer 无收益已弃） |
| P2 make_icon | `claude/perf-tray-icon-cache` / https://github.com/OranngeAustin/game_snap/pull/3 | test_tray_icon.py（7dc1714） | 1.481 / 2.323 ms | 0.003 / 0.004 ms | 约 -99.8%；常驻 +48 KB | ✅ 保留（方案 1：lru_cache + 返回拷贝） |
| P3 render_card | `claude/perf-toast-card-cache` / https://github.com/OranngeAustin/game_snap/pull/4 | test_toast_card.py（c951337） | 9.056 / 7.074 / 8.242 ms | 0.004 / 0.004 / 0.005 ms | 重复提示约 -99.9%；未命中不变；实际场景内存无可测差别 | ✅ 保留方案 2（缓存画好的卡片）；方案 1（缓存字体）-34% 但每字号常驻 +3.5 MB，弃用 |

- **D9 P3 换方案**：计划里的方案（给 `_font` 加缓存）达到了 20% 的目标（-34%），但内存代价不可接受（项目 README
  专门列了资源占用，游戏中总共约 20–29 MB）。按 RUNBOOK「最多尝试 3 种方案、保留最好的正确版本」，试了方案 2
  （缓存画好的卡片，maxsize 先 8 后 4），实际场景 -99.9% 且内存无可测差别，保留方案 2，分支随之改名为
  `claude/perf-toast-card-cache`（改名时还没推送）。
- **D10 优化 PR 的基准测法**：容器里同一项各轮可差 30%，所以每项都在同一时段测优化前后；P3 交替 A/B 各 3 次。
  PR 描述里都只给相对提升。
- **D11 试合并**：为确认 PR #2–#4 合进 `claude/review-fixes` 时互不冲突，在本地建了临时分支 `tmp-merge-check`
  依次合并（都无冲突，quick 6 过 4 失败，失败的仍是 4 个环境原因），试完删掉了这个**只在本地、从未推送**的临时分支。
  远端分支一个都没删。

## 最终状态

- 阶段 0–7 全部 ✅；没有推送 main、没有 force push、没有合并 PR、没有删除远端分支。
- 跳过的（都写明了原因，见各阶段和 00-SUMMARY.md「跳过的项和原因」）：Windows 专属测试（quick 4 个、all 5 个、
  listener_restart 的真正运行）、bench_startup 和打包、中低级问题的修复、save_png 压缩级别、Pillow 大版本升级。
- 未在 Windows 上验证：H1、H2、P1–P3 全部。下一步见 00-SUMMARY.md。

## 中危修复（2026-11-04，分支 `claude/medium-fixes`）

用户新目标：先把 PR #2–#4 合进 `claude/review-fixes`；再从它建 `claude/medium-fixes`，修 02-findings 的中危问题（M7 优先），
每个问题一个 commit、能写测试的先写测试；误报、纯风格、修复风险过大的标「⏭ 跳过」。只遵守 RUNBOOK 的「工作规则」，不重跑阶段 0–7。

| 编号 | 状态 | 测试 | 说明 |
|---|---|---|---|
| 合并 #2–#4 | ✅ | quick 6 过 4 失败（同基线） | 见 D12 |
| M7 | ✅ | 新增 listener_sync：修复前 6 项失败，修复后全过 | 见 D15 |
| M5 | ✅ | 新增 config_values：修复前 93 项失败并抛异常，修复后全过 | 见 D16 |
| M6 | ✅ | 新增 tray_refresh：修复前 3 项失败，修复后全过 | 见 D17 |
| M1 | ✅ | 新增 capture_resize：修复前 3 项失败，修复后全过 | 两行改动，无取舍 |
| M4 | ✅ | 新增 listener_start_fail：修复前 12 项失败，修复后全过 | 见 D18 |
| M8 | ✅ | 新增 instance_quit：修复前 11 项失败，修复后全过 | 见 D19 |
| M2 | ✅ | 新增 safe_name：修复前 18 项失败，修复后全过 | 见 D20 |
| M3 | ⏳ | | |

- **D12 合并 #2–#4**：RUNBOOK 工作规则禁止合并 PR，但用户这次明确要求把 #2–#4 合进 `claude/review-fixes`，以用户的话为准，
  其余 PR（#1 → main、本次新 PR）不合并。做法是在本地依次 `git merge --no-ff` 三个 perf 分支（无冲突），跑 quick
  （6 过 4 失败，失败的仍是 4 个缺 Windows 模块的），再推送 `claude/review-fixes`；GitHub 据此自动把 #2–#4 标为已合并。
  没碰 main。
- **D13 新 PR 的目标分支**：用户写的是「目标分支设为 claude/medium-fixes」，但那就是这个 PR 的源分支，自己合进自己不成立。
  按「从 claude/review-fixes 创建分支」理解为 `claude/medium-fixes → claude/review-fixes`，这样 PR 里只有中危修复的改动。
- **D14 「每次修复后运行全部测试」**：云端能跑的是 quick 里不依赖 Windows 的那些（not_games、config、toast_card、
  tray_icon、clipboard、listener_restart 打印 SKIP）和本次新增的测试；add_game、blocklist_remove、yuzu_naming、dualsense
  以及 all 的 5 个只能在 Windows 上跑（同 D2）。每次改动都对照这些跑不了的测试里**相关的断言**逐条核对过，写在各 commit 和 PR 里。
- **D15 M7 的修法**：按 02-findings 的建议，把 `_ensure_listener` 和各处「锁外判断 + `_stop_listener`」合并成
  `_sync_listener()`：在 `_listener_lock` 里按 games / learning / adding 决定挂还是摘；`_learn_timeout` 不再要求监听还在。
  `self.games` 的赋值没有挪进锁：每个改状态的线程都是先改、再调 `_sync_listener`，最后拿到锁的那次一定看到所有改动，
  不需要多拿一次锁。「添加游戏」成功后**不摘**监听的行为保持不变（test_add_game「listener left running for the new game」、
  test_add_live「hook stayed on … == 1」依赖它）。`_quit` 仍用无条件的 `_stop_listener`。
- **D16 M5 的取舍**：①开关的 0 / 1 继续当成 false / true（以前靠真假值判断，写 0 的人原来就能关掉），只有字符串、null、2 这类才回退；
  ②games / launchers 只去掉个别坏项而不是整个回退，免得一项写错就丢掉整份游戏名单；③有改动就另存原文件，因为之后的 `set()`
  会把改过的配置写回去；④轮询间隔下限 0.1 秒（防忙等），没设上限。核对过所有已有测试写的配置：轮询 1 秒、宽限 1–10 秒、
  截图键 0xC0 / F24，都在合法范围，校验不会改动它们。
- **D17 M6 的范围**：只做 02-findings 建议的「整体加锁 + 状态没变不设图标」。菜单照旧每次重建：blocklist_remove 断言移除游戏后
  「tray refreshed」（`update_menu` 次数增加），菜单里的游戏名单也确实会变。锁里调用的 pystray 操作（Shell_NotifyIcon、LoadImage、
  CreatePopupMenu）都不会同步等托盘线程处理消息，托盘线程在菜单回调里调 refresh_tray 等锁也不会死锁。Q1（菜单显示中被 DestroyMenu）
  不在这把锁的覆盖范围，仍留在待人工确认。
- **D18 M4 的取舍**：①区分「启动失败」和「启动慢」：`wait_ready()` 为 False 后再 `join(0.5)`，线程已结束才算失败；还活着就照旧留着，
  否则那个慢线程之后挂上钩子，再建一个就是两个钩子、一次按键截两张。②「下次再试」只在下次需要监听时（检测到游戏、更换截图键、
  添加游戏）重建，不按轮询自动重试：一直失败时每 2 秒一条日志加一次提示太吵。③已有测试的 FakeListener 的 `wait_ready()` 都返回
  True，所以不会走到新加的 `join` / `is_alive`，不用改它们。
- **D19 M8 的测法和一处补充**：命名互斥体 / 事件在测试里不能真建（会和正在运行的 GameSnap 抢同一个名字），所以测试把
  `instance._k32` 换成按名字记对象的假实现，`ctypes.get_last_error` 也由它提供。补充了一处 02-findings 没写的：接管成功后马上建信号，
  可能打开被换下实例还没释放的那个事件，上面还留着发给它的信号，不清掉的话本实例一开始等就会关掉自己，所以 `ResetEvent`。
  `App.on_tray_ready` 是新加的可选回调，已有测试建 App 时不设它，行为不变；add_live / remove_live 的 inner 脚本是包一层再调真的
  `_on_tray_ready`，回调照样会被调用。
- **D20 M2 没照搬 `strip(" .")`**：截图文件夹名变了，用户就会觉得同一个游戏的截图「分到了两个文件夹」。所以原则是以前能用的名字不改，
  只改以前会出错的；唯一的例外是截断（81–96 个字符的名字在截图根目录很短时以前也能存），取 02-findings 建议的 80。

