# 05 Windows 验证记录：手动测试和待修项目

2026-11-04 写于本机 worktree（`claude/github-review-local-test-1f6fb7`）。验证和手动测试针对的是 c8eb75a（代码和 `origin/claude/review-fixes` 相同）；之后在同一个 worktree 里修了 P1–P6，**改动都在工作区，没有提交，也没有推送**。
[04-windows-handoff.md](04-windows-handoff.md) 是验证计划，本文记录结果和还要做的事。

> 本文的 P1–P6 是这次验证的待修编号，和 [02-findings.md](02-findings.md) 里的性能项 P1–P4 不是一回事。

## 现在的状态（先看这里）

| 类别 | 现在怎样 | 谁来做 |
|---|---|---|
| [A. 已修好，自动验证通过](#a-已修好自动验证通过) | P1–P6、M9（Pillow 升到 13.0.0） | 不用你做 |
| [B. 等你手动真机实测](#b-等你手动真机实测) | 修复后 3 项（M-07 重做必做），以前没做完的 17 项 | **你** |
| [C. 我没改、没测的](#c-我没改没测的) | 有意没改的和自动测试到不了的 | 看清楚就行，要补的都指向 B 或 D |
| [D. 等你决定](#d-等你决定) | 4 件事 | **你** |

### A. 已修好，自动验证通过

| 编号 | 改了什么 | 自动验证 |
|---|---|---|
| P1 | `output.py:52` 去掉名字结尾连续的点和空格 | safe_name 56 项，其中 10 个名字真存一张 |
| P2 | `config.py:123` 读取被占用时重试；`config.py:117`、`config.py:180` 读不出来也没另存上时这次运行不写回；`main.py:188` 弹窗提醒 | config 58 项（含真实独占）、config_save_fail 21 项；真实进程：配置一直被独占、弹窗没人点，约 4 秒后照常自动退出，config.json 一个字节没变 |
| P6 | `hotkey.py:43-49`、`hotkey.py:119-124` 10 个键和 Num Lock 加扩展键标志，Pause、Print Screen 单独写扫描码 | key_name 50 项（假 user32 改成真机返回值，另调真实 API，没发按键）；打包版日志显示 Home、Insert、Right、Pause、Num Lock |
| P3 | `main.py:598`、`main.py:616` 日志打不开或删不掉时继续运行 | log_fail 36 项（和 P4 合计，含真实占用）；打包版 6 种占用、crash.log 超过 1 MB 时的第二个实例：启动器都起来了，都自己退出，没有卡在对话框上 |
| P5 | `output.py:60` 改名被占用时重试；`output.py:92` 删不掉 `.part` 只记日志 | save_png_fail 22 项（含真实占用） |
| P4 | `main.py:583` 轮转失败时接着写，改名成功才换掉旧的 `.log.1` | log_fail；打包版两个实例同开日志：第二个实例的行都在，1 MB 内容没丢，它退出后轮转成功 |
| M9 | `gamesnap-build` 里 Pillow 从 12.3.0 升到 13.0.0；`requirements.txt` 下限改成 `pillow>=13.0` | 同样输入下 BGRX 解码、缩放、托盘图标、36 张提示卡片、BMP、PNG 和元数据，新旧版本逐字节相同；全量重跑通过 |

- **全量结果（最终代码，Pillow 13.0.0）：** quick 32/32；打包退出码 0，92 个文件，42 MB，无警告；all 37/37；真实进程复查 28/28。详情在第 4 节。
- **这些测试确实测得出问题：** 把新测试放到修复前的代码上跑，改过和新增的 6 个全部失败（`build\test_runs\fix_baseline_result\summary.txt`）。
- **局限：** 只在这台 Windows 上跑过。没发真实按键，没弹真实对话框，见 C。

### B. 等你手动真机实测

命令见第 8 节。`dist\GameSnap\` 已经是修复后的版本（含 Pillow 13.0.0），手动测试测的就是这批改动。

**B1. 修复后要确认的（自动测试看不到）**

| 编号 | 对应 | 必做吗 | 操作 | 预期 |
|---|---|---|---|---|
| M-07 重做 | P6、M9 | **必做** | 用**打包版**（第 8 节），打开记事本，托盘「更换截图键…」，依次改成 Insert、→、Home。每改一个，在记事本里按一下，再打开一张截图看看 | 提示、托盘、日志都是 Insert、Right、Home，不是 Num 0、Num 6、Num 7；每次都截到一张（修复前没测过这一步），按 → 时记事本的光标不动；提示卡片和图片内容正常，日志后端是 `wgc`（这也是 Pillow 13 第一次走真实截图）。测完改回 `` ` `` |
| M-29 新增 | P2 | 建议 | 见第 8 节 | 弹窗写着 config.json 的路径；切开关提示「设置没保存上」；弹窗不点也会自动退出；config.json 内容不变 |
| M-30 新增 | P1 | 可选 | 测试配置里把记事本的显示名改成 `Loading...`，按截图键 | 提示已截图，图片在 `shots\Loading\`，没有 `.png.part`。测完改回 `记事本测试` |

**B2. 以前就没做完的（这轮修复不影响，还是要做）**

| 编号 | 还差什么 | 备注 |
|---|---|---|
| M-04 补做 | 鼠标后退侧键；看一眼截图内容 | 前进侧键已通过 |
| M-08 补做 | 第 10 秒左右按键，是不是只出现一条提示 | |
| M-09 | 游戏改分辨率后截图 | 要真实游戏 |
| M-10 | 真实 UAC 下的接管 | 逻辑已自动通过 |
| M-11 补做 | 托盘菜单能否打开、点击；游戏退出时开着菜单（Q1） | 连拍、图标、退出已通过 |
| M-14 | 开着剪贴板管理器连拍 | 平时不用就跳过 |
| M-15 补做 | 托盘勾选和提示的外观 | 逻辑已自动通过 |
| M-16 | 真实 U 盘写满 | 可选，模拟已通过 |
| M-17 | 剪贴板内容和 PNG 一样 | |
| M-18 | 托盘图标三种状态和提示 | 绿变灰已看过 |
| M-19 | 添加和移除同时做 | |
| M-21 | 高 DPI、多显示器 | 本机 100% 单屏，要改缩放 |
| M-22 补做 | 在资源管理器里看中文路径 | 保存已自动通过 |
| M-26 | 资源占用 | |
| M-27 | `save_dir` 留空，截一张 | 会真的写进你的「图片」文件夹 |
| M-28 | OneDrive 文件夹连拍 | 可选 |
| M-25 | 快捷方式 | **合并到 main、主目录重新打包后才能做** |

**B3. 不用再做的**

- M-04 主体、M-05、M-06、M-24：修复前已通过，这轮没改按键监听和抓帧。保存这一步有改动（P1、P5），M-07 重做时会顺便走到。
- M-23：修复前后都用真实进程自动跑过，修复后第二个实例正常退出。
- M-01、M-02、M-03、M-13、M-20：已自动通过（第 5 节）。M-12 无法手动触发。

### C. 我没改、没测的

**有意没改的**

| 项目 | 现在的行为 | 为什么没改 |
|---|---|---|
| P4 的另一半 | 多个进程同时启动时，日志行还会互相覆盖，偶尔有半截 UTF-8 | 第 2 节说可以接受；只修了轮转 |
| P5 的残留 | `.png.part` 删不掉时留在原处，只记日志，之后不会自动清理 | 第 2 节只要求记日志 |
| P2 的其他情况 | JSON 写错但另存成功（M-01）：之后保存仍会覆盖，备份还在。不合法的值（M-03）也不变 | 第 2 节说可以不动 |
| P2 的默认配置 | 读不出来时整份用默认配置，默认的 `dualsense_quad` 是 true，你原来关掉的话这次运行也会生效 | 原有行为，不在第 2 节 |
| P6 的其他键 | F13–F24 显示 `VK 0x7c`–`VK 0x87`；小键盘数字显示 `0`、`8`，和主键盘同名；这次查到媒体键（如静音）显示 `D` | 只影响名字，第 2 节说不是必须；要修见 D |
| 文档 | 第 3 节的偏差一个没改（含 `main.py:9` 的 docstring）；第 5 节没有写回 04；02-findings、PROGRESS、04 里的 file:line 和「quick 31、all 36」是修复前的 | 要你决定，见 D。这轮只改了 README、tests/README，和 CLAUDE.md 里 config.py 那一行、打包文件数 |
| 主目录的正式版 | `dist\GameSnap\` 没动，还是旧代码，用它打包时的 Pillow | 要合并后在主目录重新打包才用上这批改动，见 M-25 |
| 其他 | Q1–Q9 没动；没提交，没推送 | 见 D |

**没测的**

| 项目 | 为什么 | 怎么补 |
|---|---|---|
| 真实弹窗的样子（P2） | 自动复查把 `message_box` 换成了记录函数，没在你屏幕上弹框 | M-29 |
| 改成这些键后真实按键截图（P6） | 规则是不发真实按键 | M-07 重做 |
| Pillow 13 走真实 WGC 截图、在屏幕上显示提示卡片（M9） | 同样的原因。解码、PNG 和卡片像素已和 12.3.0 比过，打包版启动和托盘已跑过，但没真的截过一张 | M-07 重做 |
| 真实杀毒软件、同步盘的占用（P2、P5） | 用另一个句柄和 `CreateFileW` 模拟的 | M-28 能看一部分 |
| 其他键盘布局、非英文系统（P6） | 本机只有 `0x8040804`。测试在非英文系统上只查「不是错的名字」 | 本机补不了 |
| 云端 Linux | 改过和新增的测试只在 Windows 上跑过，CLAUDE.md 里「31 个里 27 个通过」是旧数字 | 下次云端会话 |
| `LongPathsEnabled=0` 的机器 | 本机是 1 | 本机不改 |
| svcl 真实输出、插手柄的分支 | 不运行写操作，没插手柄 | 不在这轮 |
| Q1–Q9 | 只有 Q7 有一点观察（第 1.1 节），Q1 在 M-11 补做里 | 02-findings |
| `bench_startup`、`bench_logic` | 可选，没跑 | 04 第 4 节 |

### D. 等你决定

1. **要不要提交、推送。** 现在都在工作区。
2. **合并 PR #1 之前，B 里的手动项要做完哪些。** M-25 只能合并后做。
3. **要不要把第 5 节写回 04 第 7 节，并改第 3 节的文档偏差。**
4. **可选：** F13–F24、小键盘、媒体键的显示名要不要也修。

已决定：P2 第 2 步（读不出来也没另存上时不写回、弹窗提醒）保留，M9 已升级。

## 1. 手动测试结果

下面是手动测试时记下的原文（P6 的详情挪到了第 2 节）。写本文时的核对和两处更正在 1.1。

### 手动测试结果（截至 2026-11-04 07:08）

**版本：** `claude/github-review-local-test-1f6fb7` @ c8eb75a，没有改代码
**环境：** 测试配置 `build\test_runs\manual\appdata`，截图在 `build\test_runs\manual\shots`，用记事本当游戏；Windows 11，1920×1080，100% 缩放，AMD 核显

| 编号 | 运行版本 | 结果 | 依据 / 备注 |
|---|---|---|---|
| M-04 | 源码 | ✅ | 添加游戏超时后监听停止，检测到记事本后在同一进程内重启；`` ` `` 和鼠标侧键（前进）共截 3 张，全是 wgc；无「监听窗口消息处理出错」，无崩溃。文件和元数据已查，**图片内容没有人看过** |
| M-05 | 源码 | ✅ | 监听 10 秒后停止；用户看到「已取消更换截图键」；学键结束后正好 60 秒自动退出 |
| M-06 | 打包 | ✅ | 按住不连拍；用户确认从 Ctrl+Alt+Del 回来后再按能截图（06:58:18）。#5、#6 相隔 111 ms，按代码必须先有一次松键，不是自动重复，来源（快速按两下或键盘连击）未确认 |
| M-07 | 源码 | ❌ | 见 P6。Insert、→、Home 显示成 Num 0、Num 6、Num 7 |
| M-08 | 源码 | 部分 | 改键正常，config.json 与日志一致（`vk: 192`）。**没有确认卡到第 10 秒的竞争点**，也**还没确认是否只出现一条提示**；竞争逻辑靠自动测试 `learn_race` |
| M-11 | 打包 | 部分 | 10 张全是 wgc（按键次数未由用户明确确认）；图标绿变灰；重开记事本时取消退出；8 秒宽限后退出，无崩溃。**托盘菜单是否可用待确认** |
| M-24 | 源码 | ✅ | 3 张 PNG 元数据有 `game=记事本测试`、`backend=wgc`，中文读回正常 |

**未做：** M-09、M-10、M-14、M-15、M-16、M-17、M-18、M-19、M-21、M-22、M-23（可选，已自动复现）、M-25、M-26、M-27、M-28。M-12 无法手动触发。

**需要留意（不算问题）**

- **Q1 观察：** M-11 的 #7 是「帧上屏-按键 -119.8 ms、按键→抓到 157.8 ms」，存的是按键前的帧；#8 是 +46.5 ms；其余 8 张在 +7.5 到 +14.1 ms。可能是静止画面没有新帧、超时后用了最近一帧，但这个解释没有读代码验证。用真实游戏时要再看。

**更正之前的报告**

- **R-24**（真实截图链路）现在是部分验证：真实按键走通了 WGC，都没有退回 GDI。换分辨率还要看 M-09。
- 我曾怀疑打包版「设备建好」和「会话就绪」之间的 6 秒有问题，**已排除**：`prepare()` 在检测到游戏时运行，`open()` 要等游戏切到前台，那段时间是用户还没切到记事本。

**当前状态**

- 测试配置的截图键已改回 `` ` ``。
- GameSnap 在 07:07:58 自动退出，之后没有再启动。
- 正式版没有被启动或替换，真实 `%APPDATA%\GameSnap` 没有被修改。

### 1.1 写本文时的核对

对照 `build\test_runs\manual\appdata\GameSnap\gamesnap.log`（85 行）和截图文件夹，上面的记录都对得上：

- 23 张截图 = M-04 的 3 张 + M-06 的 10 张 + M-11 的 10 张，后端全是 `wgc`，没有 `.png.part`。
- 日志里没有 ERROR、WARNING、Traceback，也没有「监听窗口消息处理出错」「键盘钩子出错」「进程检测出错」「SetWinEventHook」「换下这个会话」。crash.log 没有 fatal 记录。
- M-05：监听 06:51:42 启动，06:51:52 停止（10 秒），06:52:52 自动退出（60 秒）。
- M-11：设定的宽限是 10 秒，实际 8 秒（07:07:50 → 07:07:58），符合 CLAUDE.md 说的「最多少一个轮询间隔」。
- M-07：日志 07:01:29、07:01:42、07:02:20 写的也是 Num 0、Num 6、Num 7，所以错的键名不只出现在托盘和提示里。

两处更正：

- **「Q1 观察」的编号要改成 Q7。** #7 这条对应 02-findings 的 Q7（画面静止时用旧帧）。Q1 是菜单开着时被别的线程 `DestroyMenu`，**还没有观察结果**，和 M-11 里「托盘菜单是否可用待确认」是一回事。
- **#7 的解释读过代码了，对得上。** `capture.py:28` 等新帧最多 0.15 秒，`capture.py:179-188` 超时后返回手里最新的帧，`capture.py:304` 是调用处。157.8 ms 约等于 150 ms 超时加读回；#8 的 +46.5 ms 没有超时，是等到了新帧。当时画面是否完全静止没有单独复现，真实游戏里还要再看。

## 2. 待修项目（已修，没提交）

按下表的顺序修的。P1–P5 是原有问题（P5 里删 `.part` 那一步是 L11 加的），P6 是 L4 没修好。

| 顺序 | 编号 | 问题 | 严重程度 | 状态 |
|---|---|---|---|---|
| 1 | P1 | 游戏名结尾有多个点或「点加空格」时，截图永远存不下 | 中 | 已修，自动通过；M-30 可选 |
| 2 | P2 | 启动读配置的瞬间 config.json 被独占，之后一次保存就丢掉游戏名单 | 中（概率低，后果是永久丢失） | 已修，自动通过，第 2 步你决定保留；**建议做 M-29 看一次真实弹窗** |
| 3 | P6 | Insert、Home、方向键等 10 个键仍显示成小键盘键名 | 低 | 已修，自动通过；**等你做 M-07** |
| 4 | P3 | 删或打开日志失败时，新实例启动就崩溃 | 低（概率极低，影响中等） | 已修，自动通过 |
| 5 | P5 | `.png.part` 改名时被占用：截图失败，文件留下没人清理 | 低（目前只是理论风险） | 已修，自动通过 |
| 6 | P4 | 日志轮转失败、多进程同时写时丢日志 | 低（只影响诊断） | 轮转已修，自动通过；同时写的竞争没修（可接受） |

下面的现象、原因、证据和里面的行号都是修复前 c8eb75a 的，「已修」一行是现在的做法和行号。证据路径都相对于 `build\test_runs\win_verify_20261104_risks\`。

### P1（中）名字结尾有多个点时截图存不下

- **现象：** `Loading...`、`Zelda...`、`Hello..`、`Game. .`、`Game .` 报 `FileNotFoundError`，提示「截图失败」，还留下一个空文件夹（如 `Loading`）。`Game.`、`Vol.`、`a.b.`、`Game..v2`、`...Game` 正常。
- **名字来源：** yuzu 窗口标题（`emulator_game`，`main.py:72`，用户改不了）；「添加游戏…」的默认名也取窗口标题（`default_game_name`，`main.py:82`）。
- **原因：** Win32 规范化路径时，最后一段去掉所有结尾的点和空格，中间段最多去掉一个结尾的点。`mkdir` 时文件夹名是最后一段，建出来的是 `Loading`；存文件时它是中间段，路径指向 `Loading..`，不存在。
- **证据：** `x\report.txt` 第 2–15 行；`output.py:46-54`、`output.py:59-62`。旧代码同样有问题（`same as old code=True`）。
- **已修：** `output.py:52`，在 `_safe_name` 的空名检查之前加 `name = re.sub(r"[ .]{2,}$", "", name)`。`Game.`、`.hack__G.U.`、`Game..v2` 不变。不能用 `rstrip(" .")`：`tests/test_safe_name.py` 断言 `.hack__G.U.` 结尾的单个点要保留。`Loading...` 现在存到 `Loading\`，就是以前留下的那个空文件夹。README 补了这条规则。
- **测试：** `test_safe_name` 补了上面 5 个名字和 `CON..`、7 个不该变的名字，10 个名字真存一张。

### P2（中）启动读配置时文件被独占，游戏名单可能永久丢失

- **现象：** config.json 被独占（连读都不允许）时，读取失败、另存也失败，内存里是默认配置。之后切一次托盘开关，真实名单就被覆盖，磁盘上没有任何备份。允许读的占用没有这个问题。
- **证据：** `f\report.txt` 第 176–180 行；`config.py:109-117`、`config.py:127-131`。
- **已修（两步）：**
  1. `config.py:123` `_read_text`：读取遇到 `OSError` 时像 `save()` 一样重试约 1 秒。
  2. 重试后仍失败、另存也失败时（`config.py:117`），这次运行 `read_only`：`save()` 不写文件，返回 False，照常提示「设置没保存上」（`config.py:180`）；托盘就绪后弹窗提醒（`main.py:188`）。这属于 04 第 6 节 H2 留给你决定的「读不出来时禁止覆盖、弹窗提醒」，**你决定保留**。JSON 写坏又另存不了时同样不写回；JSON 写错但备份成功的情况（M-01）没动。
  - 弹窗放在单独的线程里：`icon.stop()` 退出时要等 pystray 的 setup 线程，弹窗如果开在 setup 线程里，没人点时每次退出都多等 5 秒。README 补了这种情况。
- **测试：** `tests/test_config.py` 加了读取时被占用的用例（假占用 3 种、JSON 写坏又另存不了 1 种，Windows 上再用共享模式 0 真占用 2 种）；`tests/test_config_save_fail.py` 加了弹窗提醒。

### P3（低，R-11）删或打开日志失败时，新实例启动就崩溃

- **现象：**
  - crash.log 在第一个实例运行期间超过 1 MB：第二个实例 `unlink` 报 WinError 32 后崩溃，`--launch` 不执行，管理员实例接不了管。
  - gamesnap.log 或 crash.log 被别的程序禁写（共享模式 0 或 1）：同样崩溃（rc=1，启动器没启动）。共享模式 3 正常。
  - 打包版弹模态框 `Unhandled exception in script`，进程挂着等关闭，不是无声消失。
- **概率：** 极低。真实 crash.log 跑了 33 次才 4.6 KB。第一个实例启动时会自己删掉超大文件，能恢复。
- **证据：** `i\report.txt` S4（第 54–75 行）；`u2\report.txt` 第 3–8 行；`main.py:580`、`main.py:591-593`、`main.py:637-640`。
- **已修：** `setup_logging`（`main.py:598`）、`enable_crash_log`（`main.py:616`）里删除和打开日志都包 `try/except OSError`：crash.log 删不掉就接着写，打不开就这次不写这个日志，继续运行，`--launch` 和单实例检查不受影响。README 补了这条。
- **测试：** 新增 `tests/test_log_fail.py`（`log_fail`），已登记进 `run_tests.py` 和 `tests/README.md`。quick 从 31 项变成 32 项，all 从 36 项变成 37 项。

### P4（低，R-12）日志轮转失败、多进程同时写时丢日志

- **现象：**
  - 日志超过 1 MB 时，两个进程同开会让轮转失败，丢失「已在运行」「由本实例接管」「已启动」等行，旧的 `.log.1` 还被先删了。
  - 多进程同时启动时日志行互相覆盖：5 轮里「已在运行」只留 1–3 行（应为 3 行），还出现半截 UTF-8（`��实例退出`）。
  - 源码版和打包版都不崩溃。
- **概率：** 真实日志 3 周多 57 KB，大约一年才到 1 MB。
- **证据：** `i\report.txt` S5（第 77–89 行）；`u\report.txt`；`i\s2_src2\`；`main.py:580`。
- **已修：** `main.py:583` `AppendingLogHandler`：轮转失败时继续追加，不丢行，下一条再试；用 `os.replace` 一步改名，成功才换掉旧的 `.log.1`。同时写的竞争影响很小，可以接受，**没修**（见开头 C）。
- **测试：** `tests/test_log_fail.py`，假占用和真占用（另一个句柄开着日志）各跑一遍。

### P5（低，R-09、R-10）`.png.part` 改名时被占用

- **现象：** PNG 写完、改名时被占用：提示「截图失败」，完整的 PNG 留在 `.part` 里，没人清理。删 `.part` 也被占用时再抛一次 PermissionError。config.json 保存有重试，PNG 没有。
- **概率：** 开着杀毒软件连存 100 张，0 失败、0 个 `.part`，目前只是理论风险。OneDrive 文件夹没测（M-28）。
- **证据：** `f\report.txt` 第 187 行、第 196–200 行；`output.py:72-77`。
- **已修：** `output.py:60` `_rename_part`：改名被占用时试 5 次，隔 0.2 秒（和 `Config.save()` 一样）；`output.py:92` `unlink` 失败只记日志，往外抛的还是改名的异常。留下的 `.part` 不会自动清理（见开头 C）。
- **测试：** `tests/test_save_png_fail.py` 补了放开、一直占用、删不掉 3 种情况，Windows 上再用另一个句柄真占用一遍。

### P6（低）L4 的修复在真机上没有生效

手动测试时记下的原文：

- **现象：** Insert、Delete、Home、End、Page Up、Page Down 和四个方向键都显示成小键盘键名（如 Num 0、Num 7）。这 10 个键的结果来自直接调用真实 API；手动只按了其中 3 个。
- **影响：** 只有托盘和提示里的键名错。绑定按 vk 保存（Home 记录为 `vk: 36`），但改成这些键后没有实际按键截图验证。
- **原因：** `hotkey.py:113` 靠 `MapVirtualKeyW(vk, MAPVK_VK_TO_VSC_EX)` 返回 `0xE0` 前缀来判断扩展键，但本机（键盘布局 `0x8040804`）对这 10 个键返回不带前缀的值，如 Home 是 `0x47`。强制加上第 24 位后名字全部正确。
- **测试为什么没发现：** `tests/test_key_name.py` 的假 user32 假设会返回 `0xE0xx`，与本机真实 API 不符，所以 quick 通过不代表修复有效。
- **修复建议：** 在 `key_name` 里明确列出这 10 个 vk（`0x21–0x28`、`0x2D`、`0x2E`）并加上第 24 位；假 user32 改成真实返回值，再加一个只在 Windows 上运行、调真实 API 的用例。

**写本文时直接调真实 API 复查（没有按键）**，10 个键的结果对得上：

| 键 | vk | `VSC_EX` 返回 | 现在显示 | 加第 24 位后 |
|---|---|---|---|---|
| Page Up | 0x21 | 0x49 | Num 9 | Page Up |
| Page Down | 0x22 | 0x51 | Num 3 | Page Down |
| End | 0x23 | 0x4F | Num 1 | End |
| Home | 0x24 | 0x47 | Num 7 | Home |
| ← | 0x25 | 0x4B | Num 4 | Left |
| ↑ | 0x26 | 0x48 | Num 8 | Up |
| → | 0x27 | 0x4D | Num 6 | Right |
| ↓ | 0x28 | 0x50 | Num 2 | Down |
| Insert | 0x2D | 0x52 | Num 0 | Insert |
| Delete | 0x2E | 0x53 | Num Del | Delete |

同一个函数还有几个键也不对，原来的记录里没有：

| 键 | vk | `VSC_EX` 返回 | 现在显示 | L4 之前 | 怎样才对 |
|---|---|---|---|---|---|
| Pause | 0x13 | 0xE11D | **Right Ctrl** | VK 0x13 | 扫描码 0x45、不加第 24 位 → Pause。这是 L4 带来的变化：以前只是难看，现在是错的名字 |
| Num Lock | 0x90 | 0x45 | **Pause** | Pause | 0x45 + 第 24 位 → Num Lock |
| Print Screen | 0x2C | 0x54 | Sys Req | Sys Req | 0x37 + 第 24 位 → Prnt Scrn |
| F24 | 0x87 | 0x76 | VK 0x87 | VK 0x87 | `GetKeyNameTextW` 返回空，只能自己写名字 |
| 小键盘 0 | 0x60 | 0x52 | 0 | 0 | `MAPVK_VK_TO_CHAR` 先返回了字符，和主键盘 0 同名 |

- L4 不是完全没用：Left Windows（0xE05B）、Right Ctrl（0xE01D）这些键确实返回 `0xE0` 前缀，L4 之前分别显示 `VK 0x5b`、`Ctrl`，现在是对的。所以 `0xE000` 这个分支要留着。
- 假 user32 和真机的差别不止 `0xE0xx`：它还认为小键盘 0 显示 `Num 0`、F24 显示 `F24`，真机是 `0`、`VK 0x87`。

**已修：**

- `hotkey.py:43` `_EXTENDED_VKS` 明确列出这 10 个 vk，加第 24 位；`hotkey.py:45` `_NAME_SCANS` 单独写 Pause（0x45）、Print Screen（0x37 + 第 24 位）、Num Lock（0x45 + 第 24 位）；去掉 `0xE100` 分支，`0xE000` 分支留着。F24 和小键盘没动。
- `tests/test_key_name.py` 的假 user32 改成真机的返回值，这是修测试的桩，不是放宽断言：小键盘 0 的预期改成 `0`，F24 改成 `VK 0x87`，都是修复前后不变的真实显示。另加一组只在 Windows 上跑、调真实 API 的用例。
- 其他键盘布局没测，明确列 vk 的做法不依赖布局。**还要你重做 M-07**，并在改成这些键后实际按键截一张（见开头 B1）。

## 3. 文档偏差（都没改，等你决定）

| 位置 | 写的 | 实际 |
|---|---|---|
| 04 第 3 行 | 只跑过 quick | 已过时，见第 4 节 |
| 02-findings:181、PROGRESS:180、04 第 31、118 行 | L4 已修复 | c8eb75a 上 10 个键没修好；P6 修完后这句成立了，M-07 重做通过前先不动 |
| 02-findings、PROGRESS、04 里的 file:line 和测试数量 | 修复前的 | `config.py`、`hotkey.py`、`main.py`、`output.py` 的行号都移动了；quick 现在 32 项，all 37 项 |
| 00-SUMMARY、02-findings、04、PROGRESS 的 M9；01-architecture:126 | M9 跳过；`pillow（≥10.1）` | 已升到 13.0.0，下限 `>=13.0` |
| 04 第 287 行（H2） | 读不出来时禁止覆盖、弹窗提醒，留给你决定 | 读不出来也另存不了时已这样做，你决定保留 || 04 R-02（第 100 行） | 打包版长路径取决于清单 | 源码用的 python.exe 和 GameSnap.exe 都有 `longPathAware`，本机 `LongPathsEnabled=1`，478 个字符能存 |
| 04 R-09（第 107 行） | 目标被不带 FILE_SHARE_DELETE 打开时失败 | 带了也失败（WinError 5） |
| 04 R-10（第 108 行） | 日志里的异常被换成删除失败的那个 | `log.exception` 两个都打印 |
| 04 R-11、M-23、第 6 节 | 第二个实例无声消失；步骤是退出后补大文件 | 打包版弹模态框；第一个实例启动时会把大文件删掉，按原步骤复现不了（第 8 节有修正步骤） |
| 04 第 91 行、CLAUDE.md「快捷方式」 | 6 个（各三个） | 7 个，开始菜单多一个无参数的 `GameSnap.lnk` |
| 04 第 288 行（M2） | `strip(" .")` 会改掉 `.hack` | 只处理结尾就不影响 `.hack`；修法见 P1 |
| 04 第 5 节 | M-01–M-26 | 新增 M-27、M-28（第 8 节），M-29、M-30（开头 B1） |
| 04 第 167 行、CLAUDE.md「测试」 | all 约 3 分钟 | 实测约 2 分钟 |
| CLAUDE.md「设计约定」 | 挂 / 摘监听一律走 `_sync_listener()` | 退出走 `_stop_listener`（定义在 `main.py:271`，调用在 `main.py:505`） |
| CLAUDE.md「设计约定」 | 只有「绑定的键 + 前台是游戏」才吞键 | 添加游戏时任何程序里的绑定键都吞，学键时任何键都吞 |
| `main.py:9` docstring | 没写 `--config` | `main.py:629` 有这个参数，README 也写了 |

修复前其余都对得上：代码地图 13 个 `.py`；QUICK 31、SLOW 5、tests\README 36；打包 93 个文件约 40 MB；04 第 3 节 R-01–R-28 的 file:line。

## 4. 自动测试

### 修复后（最终代码，Pillow 13.0.0，工作区未提交）

- **quick：** 32/32（`build\test_runs\m9_quick`）。
- **打包：** 退出码 0，92 个文件，42 MB，无 WARNING（`m9_pillow_20261104\build_output.txt`）。
- **all：** 37/37，容器外运行（`m9_all`）。
- **真实进程复查：** 28/28，容器外运行（`m9_pillow_20261104\verify_run\report.txt`）。结束后没有 GameSnap 残留。Pillow 12.3.0 上也跑过一次，同样全过（`fix_p1_p6_all2`、`fix_verify_20261104\run2\report.txt`）。
- **新测试放到修复前的代码上：** 6 个全部失败（`fix_baseline_result\summary.txt`）。key_name 里真实 API 那一组同样失败，说明这次的测试能发现 P6。

| 复查的场景 | 版本 | 结果 |
|---|---|---|
| P3：gamesnap.log、crash.log 被占用（共享模式 0、1、3，共 6 种） | 打包 | 启动器都起来了，进程都自己退出（rc=0） |
| P3（R-11）：运行中 crash.log 超过 1 MB，再开第二个实例 | 打包 | 第二个 rc=0，启动器起来了，日志有「已启动」「已在运行」；第一个不受影响 |
| P4（R-12）：两个实例同开超过 1 MB 的日志 | 打包 | 第二个的行都在，1 MB 内容没丢；它退出后第一个轮转成功 |
| P6：截图键设成 Home、Insert、→、Pause、Num Lock，看日志（没按键） | 打包 | 名字都对 |
| P2：config.json 全程被独占，弹窗一直没人点 | 源码（默认配置换成了无害的，避免碰手柄和真实游戏） | 约 4 秒后自动退出（rc=0）；弹窗一次；切开关被拒绝；config.json 一个字节没变；没有备份和临时文件 |

### M9：Pillow 12.3.0 升到 13.0.0

02-findings 记的是 12.3 还有已知漏洞、13.0.0 没有；GameSnap 不打开外来图片，实际可利用性低，这次是加固。

- **改了什么：** `gamesnap-build` 里 `pip install pillow==13.0.0`，`pip freeze` 前后对比只有 Pillow 变了，`pip check` 无问题。`requirements.txt` 下限改成 `pillow>=13.0`。代码没改。
- **不兼容的改动：** 读了 13.0.0 的发布说明，列出的不兼容项和移除项 GameSnap 都没用到。说明里提到文字渲染可能有细微变化，所以做了下面的对比。
- **逐字节对比：** 仓库里的 toast_card、tray_icon 是和同一个 Pillow 画的参照比，看不出版本之间的差别，所以另写了 `m9_pillow_20261104\snapshot.py`，用同样的输入在两个版本上各跑一次：BGRX 解码（WGC、GDI 两条路）、缩放、3 种托盘图标、36 张提示卡片（msyh.ttc）、文字边界框、BMP、真实 `save_png` 的 PNG 字节和中文元数据。**全部相同**，只有 Pillow 和 libjpeg-turbo 的版本号不同（GameSnap 不用 JPEG）。
- **耗时：** `bench_logic` 15 轮中位数，`save_png` 86.8 → 88.4 ms，`copy_to_clipboard` 12.5 → 12.7 ms，`to_image_decode` 3.02 → 3.07 ms，差别在波动范围内。
- **打包：** 少了一个文件 `PIL\_imagingmath*.pyd`。它只被 `ImageMath` 用，GameSnap 没用 `ImageMath`，13.0.0 里 PIL 其他模块也不再 import 它，所以 PyInstaller 没收进来。README、CLAUDE.md 的文件数已改成 92。
- **影响范围：** `gamesnap-build` 是共用环境，主目录以后从源码运行或打包也会用 13.0.0。主目录现有的 `dist\` 没动。
- **退回办法：** `gamesnap-build\python.exe -m pip install pillow==12.3.0`，`requirements.txt` 改回 `pillow>=10.1`，再重新打包。

### 修复前（c8eb75a）

- **环境：** Python 3.12.15 64 位；requirements 14 项都已安装，`pip check` 无问题；Pillow 12.3.0（在 M9 的范围内，等你决定）；`tools\svcl\svcl.exe` 存在且没运行；`not_games.py` 带 skip-worktree 标记（完整名单 93 行）。
- **quick：** 31/31（`build\test_runs\win_verify_20261104_quick`）。
- **打包：** 退出码 0，93 个文件，41 MB，无 WARNING（`win_verify_20261104_build\build_output.txt`）。
- **all：** 36/36，约 2 分 4 秒（`win_verify_20261104_all`）。

云端没真正跑过、这次在 Windows 上第一次运行的测试：

| 测试 | 云端 | 这次 |
|---|---|---|
| listener_restart | SKIP | 12/12 |
| add_game | 失败 | 62/62 |
| blocklist_remove | 失败 | 75/75 |
| yuzu_naming | 失败 | 14/14 |
| dualsense | 失败 | 23/23（没插手柄，部分 SKIP；svcl 写操作没运行） |
| lifecycle_source | 准备阶段失败 | 6/6，11.7 秒 |
| add_live | 准备阶段失败 | 20/20，27.0 秒 |
| remove_live | 准备阶段失败 | 11/11，6.6 秒 |
| lifecycle_exe | 准备阶段失败 | 5/5，11.6 秒 |
| multi_exit | 准备阶段失败 | 8/8，41.1 秒 |

**局限：** 修复前 quick 的 key_name 通过了，真机却是错的（P6）。其他用假 Win32 函数的测试（instance_quit、toast_gdi 等）同样只说明逻辑对。

## 5. 结果表（可填进 04 第 7 节）

**这张表是修复前 c8eb75a、Pillow 12.3.0 的结果。** 要写回 04 的话（开头 D 第 3 条），环境一行的 Pillow 改成 13.0.0，再按这张小表改：

| 编号 | 项目 | 修复后 |
|---|---|---|
| E-01 | 依赖安装 | ✅ Pillow 升到 13.0.0，其余没变；`pip check` 无问题 |
| A-04 | quick：config | ✅ 3.4s，58 项，含 P2 |
| A-11 | quick：safe_name | ✅ 0.2s，56 项，含 P1 |
| A-20 | quick：save_png_fail | ✅ 3.5s，22 项，含 P5 |
| A-25 | quick：config_save_fail | ✅ 2.3s，21 项，含 P2 的弹窗 |
| A-27 | quick：key_name | ✅ 0.2s，50 项，假 user32 是真机返回值，另调真实 API |
| 新增 | quick：log_fail | ✅ 0.3s，36 项，P3、P4 |
| B-01 | 打包 `build.py` | ✅ 退出码 0，92 个文件，42 MB，无警告 |
| M-07 | L4 扩展键显示名 | **等你重做**（开头 B1） |
| M-23 | R-11 crash.log 超大时的第二个实例 | ✅ 自动，打包版第二个实例 rc=0 |
| M-29、M-30 | 新增 | **等你做**（开头 B1） |

**环境**：Windows 11 家庭中文版 10.0.26100；`pip show pillow` 版本 12.3.0；显示器缩放 100%（1920×1080 单屏）；测试日期 2026-11-04；分支 / commit `claude/github-review-local-test-1f6fb7` @ c8eb75a

「自动」表示我用脚本在测试目录验证，没有人工操作。「部分」表示还有该看的东西没看，备注里写了缺什么。

| 编号 | 项目 | 结果 | 报错信息 / 备注 |
|---|---|---|---|
| E-01 | 依赖安装 | ✅ | 没有安装，都已存在；`pip check` 无问题 |
| A-01 | quick：not_games | ✅ | 0.1s |
| A-02 | quick：toast_card | ✅ | 0.8s |
| A-03 | quick：toast_gdi | ✅ | 0.2s |
| A-04 | quick：config | ✅ | 0.2s |
| A-05 | quick：config_values | ✅ | 0.2s |
| A-06 | quick：add_game | ✅ | 4.2s，62/62 |
| A-07 | quick：tray_icon | ✅ | 0.3s |
| A-08 | quick：tray_refresh | ✅ | 0.6s |
| A-09 | quick：blocklist_remove | ✅ | 0.3s，75/75 |
| A-10 | quick：yuzu_naming | ✅ | 0.4s，14/14 |
| A-11 | quick：safe_name | ✅ | 0.2s；没覆盖 P1 |
| A-12 | quick：clipboard | ✅ | 0.3s |
| A-13 | quick：capture_resize | ✅ | 0.2s |
| A-14 | quick：dualsense | ✅ | 6.8s，23/23；没插手柄，部分 SKIP |
| A-15 | quick：listener_restart | ✅ | 0.3s，12/12 |
| A-16 | quick：listener_sync | ✅ | 2.3s |
| A-17 | quick：listener_start_fail | ✅ | 0.3s |
| A-18 | quick：instance_quit | ✅ | 1.2s |
| A-19 | quick：clipboard_error | ✅ | 0.3s |
| A-20 | quick：save_png_fail | ✅ | 0.2s |
| A-21 | quick：scan_fail | ✅ | 0.6s |
| A-22 | quick：idle_order | ✅ | 0.3s |
| A-23 | quick：learn_race | ✅ | 1.3s |
| A-24 | quick：games_update | ✅ | 1.3s |
| A-25 | quick：config_save_fail | ✅ | 2.3s |
| A-26 | quick：held_key | ✅ | 0.2s |
| A-27 | quick：key_name | ✅ | 0.2s；**假 user32 和真机不符，通过不代表修复有效，见 P6** |
| A-28 | quick：win_event_hook | ✅ | 0.2s |
| A-29 | quick：d3d_staging | ✅ | 0.1s |
| A-30 | quick：d3d_release | ✅ | 0.1s |
| A-31 | quick：session_init_fail | ✅ | 0.2s |
| B-01 | 打包 `build.py` | ✅ | 退出码 0，93 个文件，41 MB，无警告 |
| A-32 | all：lifecycle_source | ✅ | 11.7s，6/6 |
| A-33 | all：add_live | ✅ | 27.0s，20/20 |
| A-34 | all：remove_live | ✅ | 6.6s，11/11 |
| A-35 | all：lifecycle_exe | ✅ | 11.6s，5/5 |
| A-36 | all：multi_exit | ✅ | 41.1s，8/8 |
| A-37 | 可选：H1 修复前的 listener_restart 应失败 | ✅ | origin/main 上 L2 失败，然后进程以 `0xC000041D` 崩溃；新代码 12/12 |
| M-01 | H2 配置多逗号 | ✅ 自动 | 打包版真跑；托盘点击用 `cfg.set` 代替 |
| M-02 | H2 带 BOM | ✅ 自动 | 打包版真跑，检测到游戏，无备份 |
| M-03 | M5 不合法的值 | ✅ 自动 | 打包版真跑，两条警告，有 `config.invalid_*`；4 秒内 CPU 0.42 秒 |
| M-04 | H1 添加游戏后截图、侧键 | ✅ | 见第 1 节；图片内容没人看过；后退侧键没测 |
| M-05 | M7 学键超时后自动退出 | ✅ | 10 秒、60 秒都对 |
| M-06 | L1 按住 / 安全桌面 | ✅ | 见第 1 节 |
| M-07 | L4 扩展键显示名 | ❌ | 显示成 Num 0、Num 6、Num 7，见 P6 |
| M-08 | L2 第 10 秒按键 | 部分 | 改键正常；第 10 秒的竞争点和提示条数没确认 |
| M-09 | M1 改分辨率后截图 | ⏭ | 还没做 |
| M-10 | M8 管理员实例接管 | 部分 | 接管逻辑自动通过（真实命名对象、假 `is_admin`）；真实 UAC 还没做 |
| M-11 | M6 连拍 / 托盘菜单（Q1） | 部分 | 连拍、图标、退出都对；托盘菜单和 Q1 待确认；M-11 里的帧观察属于 Q7 |
| M-12 | M3（无法手动触发） | ⏭ | 只靠 toast_gdi |
| M-13 | M2 保留名 / `..` | ✅ 自动 | 真实 `save_png` |
| M-14 | L10 剪贴板被占用 | ⏭ | 还没做 |
| M-15 | L18 config.json 被占用 | 部分 | 真实占用的逻辑自动通过；托盘勾选和提示外观还没看 |
| M-16 | L11 磁盘满（可选） | 部分 | 模拟磁盘满自动通过；真实 U 盘没做 |
| M-17 | 剪贴板内容（02-findings P1） | ⏭ | 还没做 |
| M-18 | 图标和提示（02-findings P2、P3） | ⏭ | 还没做；M-11 看过绿变灰 |
| M-19 | L17 添加和移除同时 | ⏭ | 还没做 |
| M-20 | L16 添加超时后不立刻退出 | ✅ 自动 | add_live A 场景 |
| M-21 | 高 DPI / 多显示器 | ⏭ | 还没做 |
| M-22 | 中文深路径 | 部分 | 文件保存自动通过；资源管理器里没看 |
| M-23 | R-11 crash.log 超大时的第二个实例 | ❌ 自动 | 按修正步骤复现，见 P3；可选 |
| M-24 | PNG 中文元数据 | ✅ | 见第 1 节 |
| M-25 | 快捷方式 | ⏭ | 合并后才能做 |
| M-26 | 资源占用 | ⏭ | 还没做 |
| M-27 | 新增：R-03，`save_dir` 留空 | ⏭ | 还没做 |
| M-28 | 新增，可选：R-09，OneDrive 连拍 | ⏭ | 还没做 |

## 6. Windows 风险逐项

这张表是修复前的结论。标着 P1、P3–P6 的风险（`_safe_name`、R-10、R-11、R-12、R-20）现在已修，见第 2 节；R-20 还要等 M-07 重做。

| 风险 | 结论 | 怎么验证的、结果 |
|---|---|---|
| R-01 | ✅ | 实测：中日韩、emoji、`&` 走真实 `save_png` |
| R-02 | ✅ | 实测：478 个字符的路径能存；`LongPathsEnabled=0` 的机器没测 |
| R-03 | ✅ 部分 | 路径解析为 `D:\00AustinDocuments\图片`，没往里写；真实写入见 M-27 |
| R-04 | ✅ | 中文、emoji 能读回；孤立代理字符这张失败、不留 `.part`（极端输入，不算问题）；手动 M-24 也通过 |
| `_safe_name` | 见 P1 | 53 个名字 51 个正常，失败的是 `foo..`、`foo. .`；保留名、控制字符、`..`、超长都按预期 |
| R-05 | ✅ | 9 种编码情况，加打包版真跑 4 种，备份逐字节相同 |
| R-06 | ✅ | all 的 14 个日志和真实的 3 个文件都是合法 UTF-8；PowerShell 不加 `-Encoding UTF8` 会乱码 |
| R-07 | ✅ 代码 | 代码页 936，假 GBK 字节解码正确；没运行 svcl |
| R-08 | ✅ | 4 种占用方式都约 0.81 秒返回 False，提示一次，解除后能存；只读属性也失败。读取时被占用见 P2 |
| R-09 | ✅ | 56 次保存、28881 次读取、0 次半截 JSON；`os.replace` 出错 38 次，1 次最终没存上；`config.tmp` 只在最终失败后残留，下次成功即消失。PNG 见 P5 |
| R-10 | 确认 | P5 |
| R-11 | 确认 | P3 |
| R-12 | 确认 | P4 |
| R-13 | ✅ 部分 | 没有 multiprocessing；`list2cmdline` 5 组往返一致；打包版 `--launch` 带中文和空格路径可用；真实 UAC 没测 |
| R-14 | ✅ 部分 | 真实命名对象、假 `is_admin`：同时启动 9 轮都只剩 1 个；隔 0.3、1、3 秒接管成功；互斥体一出现就接管 6/6，约 70 毫秒。跨权限级别没测。SDDL：mutex `D:(A;;0x1f0001;;;WD)S:AI(ML;;NW;;;LW)`，event `D:(A;;0x1f0003;;;WD)S:AI(ML;;NW;;;LW)` |
| 启动方式 | ✅ 只读 | 7 个 `.lnk` 的目标都是主目录 `dist\GameSnap\GameSnap.exe`；米哈游启动器两处勾了管理员；云·原神、yuzu 带 `--no-elevate`。新版留给 M-25 |
| 目录遍历 | 不适用 | 程序代码没有递归遍历；只有 `build.py:18`、`dualsense.py:40` 用 `.resolve()` 定位自身目录 |
| R-18 | ✅ 部分 | M-04、M-06 的日志没有「键盘钩子出错」；真实游戏里没测 |
| R-19 | ✅ | M-06 按住不连拍；没记录是否把重复延迟调到最长 |
| R-20 | ❌ | P6 |
| R-21 | 部分 | 前进侧键可用，后退没测 |
| R-22 | ✅ | 手动的日志没有「SetWinEventHook 失败」 |
| R-24 | 部分 | 手动 23 张全是 wgc，没退回 GDI，没有「换下这个会话」；换分辨率见 M-09 |
| R-26 | 待确认 | 托盘菜单（M-11、Q1） |
| R-28 | ✅ | 手动的日志没有「进程检测出错」 |

R-15、R-17、R-23、R-25、R-27 这轮没有专门验证（R-23、R-25 的逻辑有 quick 覆盖）。R-16 不适用，仓库里没有 .bat。

## 7. 真实日志的观察（只读，旧版）

来自容器外只读读取的真实 `%APPDATA%\GameSnap`，跑的是还没修复的旧版：

- 日志 479 行，截图 wgc 63 次、gdi 0 次。
- 2026-11-04 10:11:52 同一进程重建监听后，crash.log 有一条 access violation，位置 `winapi.py:87 message_loop` ← `hotkey.py:179 run`；10:35:51 之后没有「按键监听已停止」。这符合 H1，但 crash.log 不记时间，**时间和因果是推断**。
- 29 个会话里 5 个没有退出行（2026-10-12 22:48、10-17 17:40、10-28 15:12、10-29 15:43、11-04 09:57），其余几次的原因无法判断。

**两边的时间不能直接比较：** 本机现在是 GMT Standard Time，验证和手动测试的时间（06:23–07:18）都在这个时区。真实日志里同一天的 10:35 比这些时间还晚，说明写日志时机器在别的时区（具体哪个没有核实）。

## 8. 手动测试的命令

要做哪些看开头 B，这里只写怎么做。`dist\GameSnap\` 已经是修复后的版本（工作区未提交的代码），源码和打包版测到的是同一批改动。

准备（已验证能写出正确的中文配置）。测试配置已经存在，后面接着测只要设 `$env:APPDATA`，不用重写配置：

```powershell
$py = "D:\anaconda3\envs\gamesnap-build\python.exe"
$proj = "D:\0_my_projects\anthropic_claude_code\game_snap\.claude\worktrees\github-review-local-test-1f6fb7"
Set-Location $proj
Get-Process GameSnap -ErrorAction SilentlyContinue      # 有输出就先从托盘退出
$env:APPDATA = "$proj\build\test_runs\manual\appdata"
$cfg = "$env:APPDATA\GameSnap\config.json"
# 需要重写测试配置时才运行下面这行
& $py -X utf8 -c "import json,os,sys; p=sys.argv[1]; os.makedirs(os.path.dirname(p),exist_ok=True); json.dump({'games':{'Notepad.exe':'\u8bb0\u4e8b\u672c\u6d4b\u8bd5'},'launchers':[],'save_dir':sys.argv[2],'dualsense_quad':False},open(p,'w',encoding='utf-8'),ensure_ascii=False,indent=2)" $cfg "$proj\build\test_runs\manual\shots"
```

启动（二选一）：

```powershell
& $py main.py --no-elevate --console --config $cfg      # 源码
& "$proj\dist\GameSnap\GameSnap.exe" --no-elevate --config $cfg     # 打包版
```

操作和预期见 04 第 5 节。和 04 不一样或它没写的：

| 编号 | 说明 |
|---|---|
| M-08 补做 | 只看两件事：第 10 秒左右按键，是不是只出现一条提示；提示和 config.json 是否一致 |
| M-10 | 第二条命令是 `& "$proj\dist\GameSnap\GameSnap.exe" --config $cfg`。提权进程不继承窗口里的 `$env:APPDATA`，它的日志和 crash.log 会追加到**真实的** `%APPDATA%\GameSnap`，配置和截图仍走测试配置 |
| M-11 补做 | 只看托盘菜单：能否打开、点击；游戏退出的同时开着菜单，是失效还是崩溃（这才是 Q1） |
| M-23（不用做了） | 04 的步骤复现不了。正确做法：第一个实例**运行期间**把 `crash.log` 补到 1 MB 以上，再启动第二个。修复前第二个弹 `Unhandled exception in script`，修复后正常退出，都已用真实进程自动验证 |
| M-27（新增，R-03） | 测试配置里 `save_dir` 留空，截一张。预期：在 `D:\00AustinDocuments\图片\GameShots\记事本测试\`。这张会真的写进你的「图片」文件夹 |
| M-28（新增，可选，R-09） | `save_dir` 指到 OneDrive 同步的文件夹，连拍 10 张。预期：没有 `.png.part`，没有「截图失败」 |

### M-29（新增，P2）：配置文件一直被独占

这次会用**默认配置**运行，所以先做好这三件事：**拔掉 DualSense**（默认 `dualsense_quad` 是 true，插着时会真的改声音设置）；**关掉米哈游启动器和游戏**（默认名单里的程序开着就不会自动退出）；**全程不要按截图键**（默认 `save_dir` 是真实的「图片」文件夹）。

窗口 1，独占配置文件（先照上面的准备设好 `$cfg`）：

```powershell
$f = [IO.File]::Open($cfg, 'Open', 'Read', 'None')
```

窗口 2，启动（同样先设好 `$proj`、`$env:APPDATA`、`$cfg`）：

```powershell
& "$proj\dist\GameSnap\GameSnap.exe" --no-elevate --config $cfg
```

预期：

1. 约 1 秒后托盘出现图标，弹窗「配置文件现在读不出来…」，写着 config.json 的路径。
2. **不点弹窗**，托盘切一下「截图声音」：提示「设置没保存上（config.json 被占用），详见日志」。
3. 约 60 秒后 GameSnap 自动退出，弹窗跟着消失。
4. 回到窗口 1，运行下面两行：内容还是 `记事本测试` 那份，文件夹里没有 `config.unreadable_*`。

```powershell
$f.Close()
Get-Content -Encoding UTF8 $cfg
```

5. 再启动一次，托盘正常，日志里的游戏名单是 `Notepad.exe`。

## 9. 测试产物

都在 `build\test_runs\` 下（git 忽略），没有清理过：

| 路径 | 内容 |
|---|---|
| `win_verify_20261104_quick\`、`win_verify_20261104_all\` | quick、all 的 summary.txt 和每个测试的报告 |
| `win_verify_20261104_build\build_output.txt` | 打包输出 |
| `win_verify_20261104_h1_before\` | A-37：`git archive origin/main` 的源码和输出 |
| `win_verify_20261104_risks\` | 验证脚本（`risk_*.py`、`readonly_*.py`、`hold.py`、`inner.py`）和报告（`f\`、`i\`、`u\`、`u2\`、`x\` 下的 report.txt） |
| `manual_cmdcheck\` | 试手动准备命令 |
| `manual\` | 手动测试的配置、日志（`appdata\GameSnap\`）和 23 张截图（`shots\`）。后面接着测会继续往这里写 |
| `fix_p1_p6_first\`、`fix_p1_p6_quick\`、`fix_p1_p6_all\` | 修复过程中的几次运行 |
| `fix_p1_p6_quick2\`、`fix_p1_p6_all2\` | P1–P6 修完、Pillow 12.3.0 的 quick、all |
| `m9_quick\`、`m9_all\` | 最终代码（Pillow 13.0.0）的 quick、all |
| `m9_pillow_20261104\` | Pillow 对比：脚本（`snapshot.py`、`compare.py`）、结果（`before.json`、`after.json`）、`bench_*.txt`、`freeze_*.txt`、打包输出、真实进程复查（`verify_run\`） |
| `fix_baseline_src\`、`fix_baseline_result\` | 修复前的代码加新测试，和它的结果（全部失败） |
| `fix_verify_20261104\` | 真实进程复查的脚本（`verify.py`、`inner_readonly.py`）、打包输出（`build_output*.txt`）、报告（`run\`、`run2\` 下的 report.txt，都是 Pillow 12.3.0） |

- `i\report.txt` 里的几处 FAIL 不是产品问题：S2 是 P4 的日志竞争；S3 延迟 0 秒是假管理员 B 抢先拿到互斥体，属正确行为；S5a 的检查只看新日志，那行在 `.log.1`。
- **删除时注意：** `risks\f\长路径\` 有超过 260 个字符的路径，`risks\f\probe\` 有叫 `CON`、`COM1` 的文件夹，资源管理器可能删不掉，要用 Python 或 `\\?\` 路径。
- 工作区外的只读结果：`%LOCALAPPDATA%\Temp\gamesnap_verify_readonly_20261104.txt`、`gamesnap_verify_realLog_20261104.txt`、`gamesnap_verify_realLog2_20261104.txt`（含游戏名单）。Git Bash 的 `/tmp` 里还有一个 0 字节文件 `nul`，是我的命令留下的。
