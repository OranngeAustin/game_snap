# 审查与优化进度

按 [RUNBOOK.md](RUNBOOK.md) 执行。环境：claude.ai/code 云端会话（Ubuntu 容器，Python 3.12.3），
不是 Windows。用户 2026-11-03 补充：「云端环境实在无法测试的标注并跳过，能做的尽可能做」。

状态：✅ 完成 · 🔄 进行中 · ⏭ 跳过 · ⬜ 未开始

| 阶段 | 内容 | 状态 | 说明 |
|---|---|---|---|
| 0 | 准备：依赖、基线测试、分支、本文件 | ✅ | Linux 基线：quick 1 过 4 失败（环境），all 跑不起来；分支已推送 |
| 1 | 架构摸底 → 01-architecture.md | ✅ | 13 个模块、8 类线程；审查顺序 hotkey/winapi → d3d/capture → main → config → watcher → toast → output → instance/dualsense → build/not_games → tests |
| 2 | 代码审查 → 02-findings.md | ✅ | 3 个 code-reviewer 子代理分组审查 + 逐条核实：高 2、中 8、低 18、待确认 9；H2 已在 Linux 复现 |
| 3 | 安全审计 → 02-findings.md「安全」 | 🔄 | |
| 4 | 修复高危问题，PR → main | ⬜ | |
| 5 | 性能分析 → 03-perf-plan.md | ⬜ | |
| 6 | 算法优化（前 3 项），PR → claude/review-fixes | ⬜ | |
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
