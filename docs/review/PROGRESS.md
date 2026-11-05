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
| M3 | ✅ | 新增 toast_gdi：修复前 10 项失败，修复后全过 | 按 02-findings 建议，无取舍 |
| M9 | ⏭ 当时跳过 | | 要升 Pillow 大版本，工作规则不允许，且要在 Windows 上重新打包验证。2026-11-04 已在 Windows 上升级（05 第 4 节） |
| 建 PR | ✅ | quick 14 过 4 失败（连跑 3 次一样） | https://github.com/OranngeAustin/game_snap/pull/5（`claude/medium-fixes → claude/review-fixes`；2026-11-04 已按用户要求合并，见 D26），见 D13、D21 |

- **D12 合并 #2–#4**：RUNBOOK 工作规则禁止合并 PR，但用户这次明确要求把 #2–#4 合进 `claude/review-fixes`，以用户的话为准，
  其余 PR（#1 → main、本次新 PR）不合并。做法是在本地依次 `git merge --no-ff` 三个 perf 分支（无冲突），跑 quick
  （6 过 4 失败，失败的仍是 4 个缺 Windows 模块的），再推送 `claude/review-fixes`；GitHub 据此自动把 #2–#4 标为已合并。
  没碰 main。
- **D13 新 PR 的目标分支**：用户写的是「目标分支设为 claude/medium-fixes」，但那就是这个 PR 的源分支，自己合进自己不成立。
  按「从 claude/review-fixes 创建分支」理解为 `claude/medium-fixes → claude/review-fixes`，这样 PR 里只有中危修复的改动。
  用户中途补充「完成后把所有中级修复合并入 claude/medium-fixes，不合并入 main」：每项修复本来就直接提交在 `claude/medium-fixes` 上，
  所以都已经在这个分支里；PR 当时只用来审阅、不合并，也没碰 main（之后按用户要求合并了，见 D26）。
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
- **D21 一处测试时序问题**：M3 之后跑 quick 时，M4 新加的 listener_start_fail 偶发一次「学键计时器没开」失败（单独跑 12 次都过）：
  上一节取消的计时器线程还没结束。另起一个 commit（471f99d），在那一节开始前先 join 这个已取消的计时器，断言不变；之后 quick 连跑 3 次都是
  14 过 4 失败。

### 中危修复的最终状态

- M1–M8 全部 ✅，每项一个 commit，先写测试、确认它在修复前失败，再修；另有一个 M4 测试的时序修正 commit。M9 ⏭（理由见上表）。
- 新增 8 个测试，都登记进 run_tests.py 的 QUICK 和 tests/README.md，都能在云端 Linux 和 Windows 上跑。已有测试的断言一条没改。
- 云端 quick：14 过 4 失败，失败的仍是 add_game、blocklist_remove、yuzu_naming、dualsense（缺 Windows 模块，同基线）。all 跑不了。
- 没推送 main、没 force push、没删除分支；除了用户明确要求的 #2–#4，没合并任何 PR（#5、#6 之后也按用户要求合并了，见 D26）。

## 低危修复（2026-11-04，分支 `claude/low-fixes`）

用户新目标：从 `claude/medium-fixes` 建 `claude/low-fixes`，修 02-findings 的低危问题 L1–L18，每个问题一个 commit、能写测试的先写测试；
误报、纯风格、修复风险过大的标「⏭ 跳过」。PR 目标分支 `claude/medium-fixes`。只遵守 RUNBOOK 的「工作规则」。

| 编号 | 状态 | 说明 |
|---|---|---|
| L10 | ✅ | 新增 clipboard_error：修复前 6 项失败，修复后全过 |
| L11 | ✅ | 新增 save_png_fail：修复前 1 项失败，修复后全过 |
| L15 | ✅ | 新增 scan_fail：修复前 7 项失败，修复后全过 |
| L16 | ✅ | 新增 idle_order：修复前 4 项失败，修复后全过 |
| L2 | ✅ | 新增 learn_race：修复前 2 项失败，修复后全过 |
| L17 | ✅ | 新增 games_update：修复前 4 项失败，修复后全过 |
| L18 | ✅ | 新增 config_save_fail：修复前 11 项失败，修复后全过 |
| L1 | ✅ | 新增 held_key：修复前 3 项失败，修复后全过 |
| L4 | ✅ | 新增 key_name：修复前 10 项失败，修复后全过。真机上没修好，05 的 P6 补修，真实按键确认等 M-07 |
| L3 | ✅ | 新增 win_event_hook：修复前 1 项失败，修复后全过 |
| L5 | ✅ | 新增 d3d_staging：修复前 3 项失败，修复后全过 |
| L6 | ✅ | 新增 d3d_release：修复前 3 项失败，修复后全过 |
| L9 | ✅ | 新增 session_init_fail：修复前 2 项失败，修复后全过 |
| L7 | ⏭ 跳过 | 修复风险过大：改截图后端的退路策略，参数要在 Windows 上模拟驱动重置才能定 |
| L8 | ⏭ 跳过 | 同 L7，和 L7 是同一个重试策略问题 |
| L12 | ✅ | 已由 PR #2（P1）修复 |
| L13 | ✅ | 已由 PR #4（P3，缓存卡片而不是字体）处理 |
| L14 | ✅ | 已由 PR #3（P2）+ M6 修复 |
<!-- 低危进度表末尾 -->

- **D22 测试范围**：同 D14，「每次修复后运行全部测试」在云端只能跑 quick 里不依赖 Windows 的那些；all 的 5 个和 4 个 Windows quick
  测试跑不了，改动相关的断言逐条核对。每项的流程固定为：新测试先在旧代码上跑、确认失败 → 修 → 新测试全过 → quick 失败的只有那 4 个
  环境原因 → 提交推送。
- **D23 一个测试桩的错误**：L15 的测试第一次跑时，假 EnumProcesses 按 4 字节算进程数，而 Linux 上 `wt.DWORD` 是 8 字节，
  修复后的代码也没全过。辅助脚本按规则停下、没提交；把 watcher.py 恢复成旧代码、改正测试桩后重走了一遍（修复前 7 项失败，修复后全过）。
- **D24 L1 没加 `_held_vk`**：`_held` 只跟踪当前绑定的那一个键（别的键在前面就返回了），换键（`set_binding`）和学键时清掉就够了；
  再加「超过 1.5 秒没收到按下就当新按下」覆盖抬起事件丢失。test_add_game 调 `_handle_key` 的时刻都是 0、按下抬起成对，行为不变。

### 低危修复的最终状态

- L1–L6、L9–L11、L15–L18 ✅（13 项，每项一个 commit、一个新测试，都先确认在修复前失败）；L12–L14 ✅（已在 PR #2–#4 和 M6 里修过）；
  L7、L8 ⏭（修复风险过大）。已有测试的断言一条没改。
- 云端 quick：27 过 4 失败，失败的仍是 4 个缺 Windows 模块的。
- all（D25）：`run_tests.py all` 在 Linux 上一开头就停下（它先 import watcher 检查 GameSnap 是否在运行，缺 `ctypes.WinDLL`）。
  5 个 SLOW 测试逐个直接运行，全部在准备阶段失败、还没执行到项目代码：lifecycle_source、add_live 找不到
  `D:\anaconda3\envs\gamesnap-build\python.exe`；remove_live、multi_exit 找不到 `C:\Windows\System32\PING.EXE`；lifecycle_exe
  找不到 `dist\GameSnap\GameSnap.exe`。真正跑它们要在 Windows 上先重新打包（会换掉正在用的 GameSnap），留给用户。
- 没推送 main、没 force push、没删除分支；当时没合并任何 PR（之后按用户要求合并了，见 D26）。
- PR：https://github.com/OranngeAustin/game_snap/pull/6（`claude/low-fixes → claude/medium-fixes`，已按用户要求合并，见 D26）。

## 合并与文档更新（2026-11-04）

- **D26 合并**：用户先要求「把 medium 和 low fixes 都合并到 claude/review-fixes，不合并到 main」，再要求「按顺序合并」。做法都是本地
  `merge --no-ff`、跑 quick（27 过 4 失败，同前）、再推送：
  1. `claude/medium-fixes`、`claude/low-fixes` 合进 `claude/review-fixes`（ad764a7、47141d4），GitHub 把 PR #5 标为已合并；
  2. 按顺序：`claude/low-fixes` 合进 `claude/medium-fixes`（2483072，PR #6 标为已合并），再把 `claude/medium-fixes` 合进
     `claude/review-fixes`（ba69e14）。三条分支现在是一条链：low ⊂ medium ⊂ review-fixes，文件内容和 `claude/low-fixes` 相同。
  「按顺序合并」没有包括 PR #1：用户此前明确说过不合并到 main，而且改动还没在 Windows 上验证，留给用户明确决定。
- **D27 文档跟上现状**：用户问「对应文档都改了吧」。核对后发现 04（还让在 `claude/low-fixes` 上验证、按 #6 → #5 → #1 合并）、
  00-SUMMARY（还停在阶段 7）、本文件（#5、#6 写着不合并）、CLAUDE.md（云端「能跑的只有 not_games」、改游戏名单还写 `cfg.set()`）、
  README（缺「设置没保存上」「按键监听没启动起来」两个提示的说明）、02 / 03 / 01 的开头没跟上，在 `claude/review-fixes` 上一起改了。

## Windows 验证（2026-11-04 至 11-05）

在本机 worktree `claude/github-review-local-test-1f6fb7` 里做，过程和结果都在 [05-windows-verification.md](05-windows-verification.md)，这里只记决定。

- **D28 验证的规矩**：用户定的：不动主目录，不启动或替换在用的 GameSnap，真实 `%APPDATA%\GameSnap` 只读，不发真实按键（SendInput），不改 DualSense 设置，
  不启动用户的游戏和软件，不合并 PR #1、不推送 main。c8eb75a 上 quick 31/31、all 36/36，云端跑不了的测试都第一次在 Windows 上通过。
- **D29 P1–P6**：手动测试发现 L4 在真机上没修好（P6），验证风险时发现 P1–P5。用户要求依次修，2f58279。P2 第 2 步（读不出来也没另存上时不写回、弹窗提醒）
  超出原来的范围，用户决定保留。P4 只修轮转，同时写的竞争可以接受。
- **D30 M9 升级**：用户同意后 Pillow 12.3.0 → 13.0.0，下限 `pillow>=13.0`。同样输入下解码、缩放、图标、提示卡片、PNG 新旧版本逐字节相同。
- **D31 P7**：修完实际启动时发现：退出的那一刻托盘菜单开着，`WM_QUIT` 被菜单的模态循环吃掉，进程不结束、占着单实例。旧代码也一样。
  修法是退出看门狗（`start_exit_watchdog`，3 秒后直接结束进程），没动 pystray；只在 `main()` 里挂，单元测试的 App 不开。
- **D32 Q1 不修**：真实菜单上测了 5 种情况，`DestroyMenu` 不崩、不失效、不漏，只是开着的菜单内容旧了。
- **D33 按键名**：F13–F24、小键盘、媒体键直接写名字（`_FIXED_NAMES`），用户同意。巴西键盘的 ABNT 键没写。
- **D34 两个旧的偶发失败**：add_game 的计时上限差一个时钟刻度；games_update 的 WinError 1410（`id(icon)` 复用）。都不是这次改动带来的，顺手修了测试。
- **D35 手动项尽量自动做**：M-08、M-11、M-15、M-17、M-19、M-26、M-29、M-30 改成脚本验证，M-27 用真实那局的数据。
  没用 computer use，也没弹 UAC，能用它代测的标在 05 开头 C，必须用户做的在 05 开头 B（M-07 合并前必做，M-25 合并后必做）。
- **D36 提交**：用户要求提交到 `claude/review-fixes`。PR #1 没合并，main 没动，主目录的正式版还是旧代码。

### Windows 验证的最终状态

quick 33/33（连跑 3 次），打包 92 个文件 42 MB，all 39/39（容器外，140 秒）。只在这台 Windows 上跑过：100% 单屏、键盘布局 0x8040804、普通权限。
