# 00 审查与优化总结

按 [RUNBOOK.md](RUNBOOK.md) 无人值守执行，2026-11-03，claude.ai 云端会话（Linux 容器）。进度和每个决定的理由见
[PROGRESS.md](PROGRESS.md) 的「决策记录」D1–D11。

> **最重要的一点**：这个容器是 Linux，GameSnap 的代码一 import 就要 `winsound`、`winreg`、`ctypes.WinDLL`，所以全部修复和优化
> 都**还没在 Windows 上跑过**。Linux 上能跑的测试都跑了：失败数和基线一样，新增的测试都通过。合并之前请按下面「建议你下一步做什么」的
> 第 1 步，回 Windows 验证。

> **2026-11-04 更新**：之后又按你的要求修了中危 M1–M8（PR #5）和低危 L1–L18（PR #6），写了 Windows 交接文档
> [04-windows-handoff.md](04-windows-handoff.md)。PR #2–#6 都已按顺序合进 `claude/review-fixes`，只剩 PR #1（→ main）没合并。
> 下面「完成了什么」「所有 PR」「跳过的项」「建议你下一步做什么」已按现在的状态改过。

## 完成了什么

| 阶段 | 产出 | 结果 |
|---|---|---|
| 0 准备 | PROGRESS.md、`claude/review-fixes` 分支 | Linux 基线：quick 1 个通过、4 个失败（都是缺 Windows 模块），all 跑不起来 |
| 1 架构摸底 | [01-architecture.md](01-architecture.md) | 13 个模块、8 类线程、核心数据流、外部依赖、高风险区域、审查顺序 |
| 2 代码审查 | [02-findings.md](02-findings.md) | 3 个只读 code-reviewer 子代理分组审查，每条我都逐一核实：**高 2、中 8、低 18、待确认 9** |
| 3 安全审计 | 02-findings.md「安全」 | 没有注入、不安全的反序列化或硬编码密钥；M9（Pillow 版本下限）和 L19–L21 是加固项 |
| 4 修复高危 | PR #1 | H1、H2 两处修复，各一个 commit，各配一个新测试 |
| 5 性能分析 | [03-perf-plan.md](03-perf-plan.md)、`tests/bench_logic.py` | 每张截图在 Python 侧约 247 ms，其中 save_png 占 89%；选出 3 项低风险优化 |
| 6 算法优化 | PR #2、#3、#4 | 每项都先补特征测试，输出逐字节不变；基准提升 40%～99.9% |
| 7 总结 | 本文件 | |
| 中危修复（之后） | PR #5 | M1–M8 修复，M9 跳过；8 个新测试，各自在修复前失败、修复后全过 |
| 低危修复（之后） | PR #6 | L1–L6、L9–L11、L15–L18 修复；L12–L14 已在 PR #2–#4 和 M6 里处理；L7、L8 跳过；13 个新测试 |
| Windows 交接（之后） | [04-windows-handoff.md](04-windows-handoff.md) | 改动总览、云端没验证的、风险清单、本机测试步骤、手动测试清单、结果记录表 |

### 修掉的两个高危问题（PR #1）

- **H2 配置被默认值覆盖**（已在 Linux 复现）：config.json 读不出来时（手改多了个逗号，或者存成带 BOM 的 UTF-8），GameSnap 用默认配置继续运行。之后只要切一下托盘开关、添加或移除游戏，就会把默认配置写回文件，你的游戏名单和截图键永久丢失。
  - 修复：读的时候用 `utf-8-sig`；读失败时先把原文件另存为 `config.unreadable_<时间>.json`；
  - README「配置」一节补了说明。
- **H1 监听窗口的回调错位**：窗口类名是固定的，所以每次重建的按键监听窗口，用的都是**第一个** InputListener 的窗口过程。重建发生在游戏关了又开、添加游戏 / 更换截图键前后。
  - 后果有两种：旧对象还在时，学不到鼠标侧键、侧键截图失灵；旧对象被回收后，回调指向已释放的内存，会原生崩溃。
  - 修复：每个窗口用自己的类名，窗口销毁后注销。

### 三项性能优化（PR #2–#4，目标分支都是 `claude/review-fixes`）

| 项 | 改动 | 基准中位数 | 内存 |
|---|---|---|---|
| P1 剪贴板 | 图已经是 RGB 就不再 `convert` | -40%～-60% | 4K 每次少一份整帧拷贝（峰值 RSS -8 MB） |
| P2 托盘图标 | 三种状态各画一次，之后返回拷贝 | -99.8% | +48 KB |
| P3 提示卡片 | 同样的参数只画一次（缓存画好的卡片） | 重复提示 -99.9%，首次不变 | 实际场景下测不出差别 |

## 所有 PR

状态（2026-11-04）：#2–#6 已合并，#1 开着、没合并。

| PR | 分支 → 目标 | 内容 |
|---|---|---|
| https://github.com/OranngeAustin/game_snap/pull/1 | `claude/review-fixes` → `main` | 审查文档 + H1、H2 修复 + 新测试（config、listener_restart）+ bench_logic / winstubs |
| https://github.com/OranngeAustin/game_snap/pull/2 | `claude/perf-clipboard-dib` → `claude/review-fixes` | P1 + 特征测试 clipboard |
| https://github.com/OranngeAustin/game_snap/pull/3 | `claude/perf-tray-icon-cache` → `claude/review-fixes` | P2 + 特征测试 tray_icon |
| https://github.com/OranngeAustin/game_snap/pull/4 | `claude/perf-toast-card-cache` → `claude/review-fixes` | P3 + 特征测试 toast_card |
| https://github.com/OranngeAustin/game_snap/pull/5 | `claude/medium-fixes` → `claude/review-fixes` | 中危 M1–M8 + 8 个新测试 |
| https://github.com/OranngeAustin/game_snap/pull/6 | `claude/low-fixes` → `claude/medium-fixes` | 低危 L1–L18（13 项修复）+ 13 个新测试 + 04 交接文档 |

在本地临时分支上把 #2、#3、#4 一起合进 `claude/review-fixes` 试过：没有冲突，合并后 quick 6 个通过、4 个失败，失败的还是那 4 个环境原因。
这个临时分支只在本地，没推送，试完就删了。

全程没有推送 main、没有 force push、没有删除远端分支。#2–#6 是按你的要求合并的（#2–#4、#5 合进 `claude/review-fixes`，#6 合进 `claude/medium-fixes` 后再一起合进 `claude/review-fixes`），#1（→ main）没合并。

## 跳过的项和原因

| 项 | 原因 |
|---|---|
| Windows 专属测试：quick 里的 add_game、blocklist_remove、yuzu_naming、dualsense，以及 all 的 5 个 | 云端是 Linux，这些测试一 import 项目就需要 Windows 模块。你补充过「云端环境实在无法测试的标注并跳过」 |
| `tests/bench_startup.py`、打包（build.py） | 要用打包版 `dist\GameSnap\GameSnap.exe` 和 PyInstaller，只有 Windows 上能做 |
| 新测试 `listener_restart` 的真正运行 | 要真的挂键盘钩子、建窗口，只能在 Windows 上跑；Linux 上会打印 SKIP |
| 中、低级别的问题（M1–M9、L1–L21） | 阶段 4 按 RUNBOOK 只修「高」。之后已在 PR #5、#6 里处理：M9、L7、L8 跳过，L19–L21 不在范围内，见 02-findings「中」「低」两节开头的状态表 |
| P4：save_png 降低压缩级别（最大的热点，约 220 ms） | 要提速只能改压缩级别（改变输出文件），或者先提示后保存（改变语义）。两种都不是「风险低」，留给你决定 |
| P3 方案 1：缓存字体对象 | 耗时 -34%，但每个字号要常驻约 +3.5 MB，所以改用方案 2 |
| P1 方案 2：用 `getbuffer()` 去掉文件头 | 没有收益（CPython 3.12 的 `getvalue()` 本来就不复制） |
| 把 Pillow 升到 13 | 这是大版本升级，RUNBOOK 不允许做；而且需要在 Windows 上重新打包验证 |
| 改 CLAUDE.md 里的个人路径（L21） | 要不要公开由你决定，我没有改 |

## 待人工确认

| 编号 | 问题 | 需要你做什么 |
|---|---|---|
| M9 | `requirements.txt` 写的是 `pillow>=10.1`。10.1 到 12.3 都有已知的高危 / 严重漏洞，只有 13.0.0 没有。不过 GameSnap 不打开外来图片，实际可利用性低 | 在 gamesnap-build 里跑 `python -m pip show pillow` 看实际版本，再决定要不要升到 13 并重新打包 |
| H2 延伸 | 现在的修复只做「另存 + 能读 BOM」。如果还想在读不出来时禁止覆盖、弹窗提醒，交互会有变化 | 你决定要不要 |
| P4 | save_png 的压缩级别从 6 改成 1：在测试图上耗时约减半，但 PNG 文件会变（真实游戏画面通常大 10–30%） | 你决定要不要 |
| L20 | 以管理员身份运行的 GameSnap，用的文件都在普通用户可写的位置：dist、svcl.exe、config.json | 要加固就把 dist 装到 Program Files |
| L21 | 公开仓库的 CLAUDE.md 里有 Windows 用户名和个人文件夹名 | 你决定要不要换成占位符 |
| Q1 | 托盘菜单开着时，被别的线程 DestroyMenu：表现是菜单失效还是崩溃 | 在 Windows 上复现 |
| Q2 | 低级键盘钩子回调可能因为等 GIL 超时，被系统静默摘掉 | 建议在日志里记一下钩子回调的耗时，观察一段时间 |
| Q3 | `InputListener.stop()` 超时之后可能同时挂着两个钩子 | 看日志里有没有重复截图 |
| Q4 | `get_dxgi_surface_from_object` 返回的是借用指针还是已 AddRef 的指针 | 查 pywinrt 源码 |
| Q5 | 暂存纹理用的是会话记录的尺寸，不是帧的实际尺寸 | 改分辨率后各截一张，看是否全黑或是旧画面 |
| Q6 | 截图会话按 HMONITOR 作键，显示配置变化后可能用错会话 | 插拔显示器后测一下 |
| Q7 | 画面静止时可能截到很久以前的帧 | 实测 |
| Q8 | 托盘「退出」和自动退出同时触发 | 目前没看到危害 |
| Q9 | pid 复用 | 已知的取舍 |

## 建议你下一步做什么（2026-11-04 更新）

1. **在 Windows 上验证 `claude/review-fixes`**：完整步骤（建环境、quick、备份、打包、all）、风险清单和手动测试都在
   [04-windows-handoff.md](04-windows-handoff.md)，结果填进它第 7 节的表。
2. 都通过后再决定是否合并 PR #1 到 main。合并前按 CLAUDE.md，把 dist 和源码备份到 `backup\v5_review_fixes\`，并在 README「旧版备份」里记一笔。
3. 还没处理的：M9（Pillow 版本）、L7 / L8（截图后端的重试策略）、P4（压缩级别）、L19–L21（安全加固）、Q1–Q9（待人工确认），
   以及写交接文档时新发现的 R-10–R-12（04 第 3、6 节）。其中 **R-11**（crash.log 超过 1 MB 时，第二个 GameSnap 一启动就崩）建议先看。

## 新增的测试和工具（都登记在 tests/README.md，测试登记进 run_tests.py 的 QUICK）

| 名字 | 文件 | 测什么 | 在哪里能跑 | 所在分支 |
|---|---|---|---|---|
| config | test_config.py | 配置读写、BOM、读不出来时另存 | Windows / Linux | review-fixes |
| listener_restart | test_listener_restart.py | 监听停了再建，消息送到新监听自己 | 只有 Windows | review-fixes |
| clipboard | test_clipboard.py | CF_DIB 逐字节不变、重试（假剪贴板） | Windows / Linux | perf-clipboard-dib |
| tray_icon | test_tray_icon.py | 托盘图标像素不变、每次返回新对象 | Windows / Linux | perf-tray-icon-cache |
| toast_card | test_toast_card.py | 提示卡片像素不变 | Windows / Linux | perf-toast-card-cache |
| （工具）bench_logic | bench_logic.py | 截图后那段纯 Python / PIL 链路的耗时 | Windows / Linux | review-fixes |
| （辅助）winstubs | winstubs.py | 非 Windows 上给 Windows 模块装桩 | Linux | review-fixes |

之后中危、低危修复又加了 21 个测试（listener_sync、config_values 等），清单见 [04-windows-handoff.md](04-windows-handoff.md) 第 1 节和 tests/README.md；
上表「所在分支」里的分支现在都已合进 `claude/review-fixes`。
