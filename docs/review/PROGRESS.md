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
| 6 | 算法优化（前 3 项），PR → claude/review-fixes | 🔄 | |
| 7 | 总结 → 00-SUMMARY.md | ⬜ | |

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
