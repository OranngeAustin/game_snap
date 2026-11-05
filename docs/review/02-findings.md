# 02 审查发现

审查基线：`main` @ 58c59fb。按 [01-architecture.md](01-architecture.md) 第 6 节的顺序，用 3 个只读的 code-reviewer
子代理分组审查（hotkey/winapi/toast；d3d/capture/output；main/config/watcher/instance/dualsense），再由我逐条对照代码核实、
去重、定级。云端是 Linux，Windows 代码都只能读代码推断；能在 Linux 上复现的标了「已复现」。

> 2026-11-05 注：本文的 file:line 和测试数量是当时（`claude/low-fixes` @ 0bc5178 及之前）的。之后 Windows 验证修了 05 文档的 P1–P7，`config.py`、`hotkey.py`、`main.py`、`output.py` 的行号都移动了，读代码时按函数名找。验证结果见 [05-windows-verification.md](05-windows-verification.md)。

把握程度：**高** = 读代码可以确定，或已复现；**中** = 机制确定、实际后果取决于运行时（GC、驱动、WinRT 实现）；
**低** = 推测，放进「待人工确认」。

**合计**：高 2（H1–H2）、中 9（M1–M8，安全 M9）、低 21（L1–L18，安全 L19–L21）、待人工确认 9（Q1–Q9）；安全审计见文末「安全」一节。
阶段 4 只修「高」：H1、H2。中危 M1–M8、低危 L1–L18 在 2026-11-04 分别于 `claude/medium-fixes`、`claude/low-fixes` 上处理，状态见「中」「低」两节开头的表；两条分支已按顺序合进 `claude/review-fixes`（PR #5、#6），还没合进 main。

## 高

### H1 监听窗口重建后，消息被送进第一个（可能已回收的）InputListener 的回调
- **位置**：`winapi.py:75`（`RegisterClassExW` 重复注册失败被忽略），`hotkey.py:133`、`hotkey.py:165`
- **问题**：窗口类名固定为 `GameSnapInput`。同名类在进程里只能注册一次，之后每次 `CreateWindowExW` 用的都是
  **第一次注册时**的窗口过程，也就是第一个 InputListener 的 `_wndproc`。InputListener 在一个进程里会停了再建
  （游戏关了又开、没开游戏时用「添加游戏…」「更换截图键…」、游戏在宽限期内自己重启）。
- **后果**：
  - 第一个对象还没被回收时：新窗口的 `WM_APP_REFRESH_RAW`、`WM_INPUT`、`WM_CLOSE` 都交给旧对象处理，用的是旧对象的
    `_learning`、`binding`、`_raw_registered`、`_hwnd`。第二个监听起学不到鼠标侧键；绑了鼠标侧键时 Raw Input 的登记 / 注销
    按旧状态做，侧键截图可能失灵。
  - 第一个对象被回收后（它和自己的回调构成引用环，循环 GC 会回收）：类里的窗口过程指向已释放、或已被别的 ctypes 回调复用
    的闭包内存。之后创建窗口（`WM_NCCREATE` 同步派发）或收到任何消息，都会跳进那块内存——原生崩溃，或者调用签名不符的
    回调。Python 层拦不住，什么时候发生取决于 GC 时机和 ctypes 的闭包分配顺序。
  - Linux 上演示了地址复用：回收后再建对象，新对象的回调拿到了旧 `_wndproc` 的地址（这次碰巧是新的 `_wndproc`，
    Windows 上的分配器和顺序不保证）。现有测试都没覆盖：只建过一个真 InputListener。
- **修复建议**：每个窗口用自己的类名（序号），窗口销毁后 `UnregisterClassW`；`RegisterClassExW` 失败就抛错。
  toast.py:171 同样写法，一个进程只建一个 Toast 所以目前没事，一并改。
- **把握**：高（机制）；具体症状（失灵 / 崩溃）取决于 GC，中。两个审查来源独立得出同一结论。

### H2 config.json 读不出来时用默认配置，之后任何一次保存都会覆盖用户的游戏名单（已复现）
- **位置**：`config.py:54-61`
- **问题**：JSON 解析失败只记日志、用默认值继续。之后用户切一下托盘开关、添加 / 移除游戏或更换截图键，`set()` 就把默认配置
  写回 `config.json`，原文件里的游戏名单、截图键、`save_dir` 永久丢失，没有任何提示。README 明确让用户手改 config.json
  （改游戏名、手加游戏），手改多一个逗号就会触发；**存成带 BOM 的 UTF-8 也会触发**（PowerShell 5.1 的
  `Set-Content -Encoding UTF8`、记事本选「UTF-8 带 BOM」）：`read_text(encoding="utf-8")` 不去 BOM，`json.loads` 报
  `Unexpected UTF-8 BOM`。用户发现游戏没被识别，多半会去点「添加游戏…」或切开关，正好触发覆盖。顶层不是对象（如 `[...]`）时
  `dict.update` 还可能半吞半解析。
- **复现**：Linux 上写一份多了逗号的 config.json → `Config(p)` → `set("toast", False)` → 文件里 `MyGame.exe` 消失。
- **修复建议**：用 `utf-8-sig` 读；读失败（含顶层不是对象）时先把原文件另存为 `config.unreadable_<时间>.json` 再用默认配置；
  其余行为不变。（更进一步可以禁止覆盖并弹提示，但那会改变交互，留给人工决定。）
- **把握**：高。两个审查来源独立得出同一结论。

## 中

**处理状态**（2026-11-04，分支 `claude/medium-fixes`，按 M7 → M5 → M6 → M1 → M4 → M8 → M2 → M3 的顺序，每项一个 commit，先写测试再修）：

| 编号 | 状态 | 新测试（quick） | 修复前 → 修复后 | 没照建议做 / 留给人工的部分 |
|---|---|---|---|---|
| M1 | ✅ 已修复 | capture_resize | 3 项失败 → 全过 | 真实 WinRT 关闭后是否报错要在 Windows 上改分辨率确认 |
| M2 | ✅ 已修复 | safe_name | 18 项失败 → 全过 | 没照搬 `strip(" .")`（会改掉以前能用的名字） |
| M3 | ✅ 已修复 | toast_gdi | 10 项失败 → 全过 | — |
| M4 | ✅ 已修复 | listener_start_fail | 12 项失败 → 全过 | 不按轮询自动重试（一直失败时太吵） |
| M5 | ✅ 已修复 | config_values | 93 项失败并抛异常 → 全过 | `_get_interval()` 没挪进 try（值在加载时已保证合法） |
| M6 | ✅ 已修复 | tray_refresh | 3 项失败 → 全过 | Q1（菜单显示中被 DestroyMenu）不在锁的范围内 |
| M7 | ✅ 已修复 | listener_sync | 6 项失败 → 全过 | `self.games` 的赋值没挪进锁（不需要，见 PROGRESS D15） |
| M8 | ✅ 已修复 | instance_quit | 11 项失败 → 全过 | 真实的接管流程要在 Windows 上试一次 |
| M9 | ✅ 2026-11-04 在 Windows 上修复 | — | — | 当时跳过：RUNBOOK 工作规则「不升级依赖的大版本」，而且要在 Windows 上重新打包验证。之后升到 13.0.0，下限 `pillow>=13.0`，见 05 第 4 节 |

全部修复都只在云端 Linux 上跑过测试（Windows 专属的 add_game、blocklist_remove、yuzu_naming、dualsense 和 all 的 5 个跑不了），
合并前要回 Windows 用 gamesnap-build 跑 quick 和 all。

### M1 `frame.close()` 之后又读 `frame.content_size` 重建帧池
- **位置**：`capture.py:163-165`
- **问题**：分辨率变化（游戏切全屏 / 改分辨率）时，先关闭帧再把 `frame.content_size` 传给 `pool.recreate`。WinRT 的
  IClosable 对象关闭后访问成员通常返回 `RO_E_CLOSED`。
- **后果**：抛异常 → 会话和设备被换下（按设计不关闭，多占一套）→ 这一张截图走重建流程或 GDI，重建帧池的逻辑形同虚设。
- **修复建议**：`close()` 之前先存下新尺寸再用。改动无副作用。
- **把握**：中（取决于 pywinrt / WinRT 关闭后读属性是否报错）。
- **状态**：✅ 已修复（`claude/medium-fixes`）。`close()` 之前把 `content_size` 存进 `new_size`，比较、记录、`recreate` 都用它。
  `content_size` 是 SizeInt32 值类型，存下的副本不依赖帧对象。新测试 `tests/test_capture_resize.py` 用关闭后读尺寸就报错的假帧
  走一遍：修复前 3 项失败（抛 RO_E_CLOSED、没重建帧池、手里没帧），修复后全过。真实 WinRT 关闭后是否报错仍要在 Windows 上
  改分辨率验证（改法本身不管报不报错都对）。

### M2 `_safe_name` 不处理 `.`、`..`、控制字符、Windows 保留名和超长名字
- **位置**：`output.py:37-38`（`_safe_name`），名字来源 `main.py:75-77`（yuzu 窗口标题，即 ROM 元数据）、`main.py:84-85`
- **问题 / 后果**：游戏名 `..` → 截图写到 GameShots 的上一级；`.` → 写进 GameShots 根目录；`CON`、`NUL`、`COM1` 等 mkdir 失败；
  `\x00` 抛 ValueError、其他控制字符抛 OSError；`emulator_game` 不限长度，单个路径分量超过 255 字符（文件名里又带一遍游戏名，
  名字约 110 字符起）就保存失败。失败时这个游戏每张都「截图失败」。
- **修复建议**：替换 `[\x00-\x1f]`；`strip(" .")`；结果为空或命中保留名时加前缀；截断到约 80 字符。
- **把握**：高（代码事实）；触发概率低。
- **状态**：✅ 已修复（`claude/medium-fixes`），但**没照搬** `strip(" .")`：它会改掉以前能用的名字（`.hack` 这类以点开头的、以点结尾的），
  换文件夹。现在只处理以前会出错的：只有点和空格的用「未知游戏」，控制字符换成 `_`，保留名（CON、PRN、AUX、NUL、COM1–9、LPT1–9，
  不分大小写、带扩展名也算）前面加 `_`，超过 80 个字符截断并去掉截断处的尾部空格和点。唯一会变的以前能用的情况是 81–96 个字符的名字
  （截图根目录很短时以前也存得下），只可能来自手写或 yuzu 的 ROM 标题。新测试 `tests/test_safe_name.py`：修复前 18 项失败
  （含 `..` 写到根目录外面），修复后全过；test_yuzu_naming 断言的 Zelda 文件夹名（41 个字符）不变。

### M3 提示浮层 `CreateDIBSection` 失败后 `memmove` 写 0 地址
- **位置**：`toast.py:221-238`
- **问题**：`GetDC`、`CreateCompatibleDC`、`CreateDIBSection` 返回值都不查。GDI 配额耗尽或内存不足时 `bits` 是 NULL，
  `ctypes.memmove(bits, …)` 访问违例，进程在游戏中途消失；`GetDC`→`ReleaseDC` 之间抛异常时屏幕 DC 泄漏。
- **修复建议**：先算 `data`；检查 `self._bitmap and bits.value`，失败就 `_free_bitmap()`、记日志、返回；`ReleaseDC` 放进 finally。
- **把握**：高（代码事实）；触发概率低。
- **状态**：✅ 已修复（`claude/medium-fixes`），按建议做：先算 `data`；`GetDC` 失败直接返回；`CreateCompatibleDC` 失败就不建位图；
  `memdc`、`bitmap`、`bits` 有一个是 NULL 就 `_free_bitmap()`、记日志、这次不显示；`ReleaseDC` 放进 finally。新测试 `tests/test_toast_gdi.py`
  （假 user32 / gdi32，`memmove` 目标是 0 就报错）：修复前 10 项失败（含写 0 地址），修复后全过。

### M4 监听启动失败后不重试，截图键静默失效
- **位置**：`hotkey.py:174-177`，`main.py:239-240`
- **问题**：`run()` 里建窗口或挂钩子失败只记一条日志就 `_ready.set()` 返回，`wait_ready()` 照样返回 True；App 留着这个已经
  结束的对象（`self.listener` 不是 None），直到游戏名单再次变空才重建。这期间截图键、学键、添加游戏都无效，用户只看到没反应。
- **修复建议**：记一个启动成功标志；`_ensure_listener` 检查它或 `is_alive()`，失败就置 None 并提示，下次再试。
- **把握**：高（路径确定），触发少。
- **状态**：✅ 已修复（`claude/medium-fixes`）。`InputListener` 启动失败时记 `_failed`、拆掉挂上一半的钩子，`wait_ready()` 返回 False；
  `_sync_listener` 在 `wait_ready()` 为 False 时等线程最多 0.5 秒：已结束就不留这个监听、记日志并提示「按键监听没启动起来」，下次需要监听
  （检测到游戏、更换截图键、添加游戏）时重建；线程还活着（只是启动慢）就照旧留着，免得挂上两个钩子。`start_learning` / `start_adding`
  拿不到监听时立即复位 learning / adding。**没做**按轮询自动重试：一直失败时会每 2 秒刷一次日志和提示，留给人工决定。新测试
  `tests/test_listener_start_fail.py`：修复前 12 项失败，修复后全过。

### M5 配置值不校验类型和范围
- **位置**：`config.py:57`、`watcher.py:150`、`main.py:161`、`main.py:169`
- **问题 / 后果**：
  - `poll_interval_sec` 为 0 或负数：`wait(0)` 忙等，占满一个核。
  - `poll_interval_sec` 为 null 或 `"2s"`：`float()` 在 `GameWatcher.run` 的 try 外面抛异常，线程第一次轮询后就死掉；打包版是
    `--noconsole`，日志里没有任何记录。之后不再检测进程，也永远不会自动退出。
  - `games` 为 null：`main.py:169` 的 `", ".join(...)` 抛 TypeError，一启动就崩；`games` 写成列表、`exit_grace_sec` 为 null：
    每轮抛异常（每 2 秒一条日志），永远不会自动退出。
- **修复建议**：加载后按 `DEFAULTS` 逐键校验类型（games 是 dict[str,str]、launchers 是 list[str]、数值 > 0 并设下限），不合法的键
  回退默认值并记日志；`_get_interval()` 挪进 try。
- **把握**：高。
- **状态**：✅ 已修复（`claude/medium-fixes`）。`Config` 读完后逐键校验：开关要 true / false（0 / 1 照旧当开关）、秒数要是有限数字且不低于下限
  （轮询 0.1，另两个 0）、截图键要是合法的键盘 / 鼠标侧键绑定、save_dir 要是字符串；不合法的回退默认值并记日志；games / launchers
  只去掉不对的项。有改动时先把原文件另存为 `config.invalid_<时间>.json`（同 H2）。`_get_interval()` 没挪进 try：值在加载时已保证合法，
  运行中只有托盘开关会 `set()`，不会写坏它。新测试 `tests/test_config_values.py`：修复前 93 项失败、并在 `launchers_lower()` 抛异常，修复后全过。

### M6 `refresh_tray` 被多个线程同时调用，pystray 不是线程安全的
- **位置**：`main.py:421-426`；pystray `_win32.py`（venv 里 0.19.5）的 `_update_icon` / `_update_menu`
- **问题**：GameWatcher、Saver、Timer、学键 / 添加线程、托盘 setup 线程和主线程都会调 `refresh_tray`。pystray win32 后端在调用线程
  里直接 `DestroyIcon` / `LoadImage` / `Shell_NotifyIcon` / `DestroyMenu`，没有锁。
- **后果**：两个线程同时换图标时，一个可能销毁另一个刚建的 HICON 再 `NIM_MODIFY` → 托盘图标空白或句柄泄漏；状态先算后写，晚写的
  可能是旧状态（游戏已退出，图标还是绿的）；菜单开着时别的线程 `update_menu` 会 `DestroyMenu` 正在显示的菜单。
- **修复建议**：`refresh_tray` 整体加锁、状态在锁里算；三种图标预先生成缓存，状态没变就不设 `icon`（也省掉每张截图一次的 PIL
  绘制和写临时 ICO，见 L14）。
- **把握**：竞争存在为高；可见后果为中。
- **状态**：✅ 已修复（`claude/medium-fixes`）。`refresh_tray` 整体放进 `_tray_lock`，状态在锁里算；记下托盘上显示的状态，没变就不重设
  图标（图标缓存已由 P2 做了）。菜单仍每次重建（菜单文字、游戏名单可能变了）。**没解决**的部分：托盘线程正在显示菜单时，别的线程
  `update_menu` 仍会 `DestroyMenu`（pystray 显示菜单不经过这把锁），即 Q1，要在 Windows 上复现后再定。新测试 `tests/test_tray_refresh.py`：
  修复前 3 项失败（8 个线程同时换图标、旧状态盖掉新状态、状态没变也重设），修复后全过。

### M7 「该不该挂监听」的判断和真正挂 / 摘不在同一把锁里
- **位置**：`main.py:222-223`、`283-284`、`291-294`、`316-317`、`328-329`、`362-363`
- **问题 / 后果**：
  - GameWatcher 在 `_on_games_changed({})` 里读到 `learning` / `adding` 为 False 之后，用户恰好点了「更换截图键…」：`start_learning`
    拿到的旧监听随后被摘掉。`_learn_timeout` 要求 `self.listener is not None`，不成立就什么都不做，`learning` 永远是 True：
    `on_poll` 一直提前返回，**再也不会自动退出**，「更换截图键」「添加游戏」点了也没反应。「添加游戏」同理（15 秒后提示没收到按键）。
  - 反过来，`_finish_learning` / `_finish_adding` 读到 `games` 为空之后，GameWatcher 恰好检测到游戏并 `_ensure_listener()`（拿到
    旧监听直接返回），随后监听被摘：这一整局游戏截图键都没反应（games 不再变化，不会重新挂上）。
- **修复建议**：合并成一个 `_sync_listener()`，在 `_listener_lock` 里按当前 `games` / `learning` / `adding` 决定挂还是摘；
  `_on_games_changed` 给 `self.games` 赋值也放进这把锁；`_learn_timeout` 不再依赖 `self.listener`。
- **把握**：机制为高；需要点击和游戏启停落在同一瞬间，发生概率低。
- **状态**：✅ 已修复（`claude/medium-fixes`）。新增 `_sync_listener()`，所有挂 / 摘都经过它；`_learn_timeout` 不再要求监听还在。
  `self.games` 的赋值没挪进锁（不需要，理由见 PROGRESS D15）。新测试 `tests/test_listener_sync.py` 把上面四种交错固定下来重放：
  修复前 6 项失败（学键时监听被摘、学键永不结束、不再自动退出、添加游戏时监听被摘、两种「这局游戏没监听」），修复后全过。

### M8 退出信号建得太晚，接管和启动交错时可能卡死
- **位置**：`instance.py:93-96`、`106-120`，`main.py:597-599`、`451-461`
- **问题 / 后果**：Quit 事件要到 `App` 构造之后的 `serve()` 才建。管理员新实例在旧实例的 `Instance()` 与 `serve()` 之间到达时，
  `OpenEventW` 失败就直接放弃，留下没有管理员权限的旧实例（原神里收不到按键）；信号在 pystray 进入消息循环之前到达时，
  `icon.stop()` 什么都不做、`worker.join` 对没启动的线程抛 RuntimeError，而 `_quitting` 已是 True、watcher 已停：托盘照常出现，
  但不检测进程、不自动退出，托盘「退出」也点不动，只能用任务管理器结束。
- **修复建议**：拿到互斥体后立即创建 Quit 事件和 Elevated 标记，等待线程在 `_on_tray_ready` 里再启动；`take_over` 对
  `OpenEventW` 重试几秒；`_quit` 用 try/finally 保证调用 `icon.stop`。
- **把握**：机制为高；窗口只有启动时的几百毫秒，发生概率低。
- **状态**：✅ 已修复（`claude/medium-fixes`），三处都按建议做了：①`Instance` 拿到互斥体（含接管成功后）立即 `_announce()` 建 Quit 事件和
  Elevated 标记，`serve()` 只启动等待线程；接管成功后若打开的是被换下实例还没释放的那个事件，先 `ResetEvent` 清掉残留信号。
  ②`take_over` 对 `OpenEventW` 重试 3 秒。③`main` 通过 `App.on_tray_ready` 在托盘就绪后才调 `serve()`；`_quit` 用 try/except/finally，
  没启动的截图线程不 join，出错也调用 `icon.stop()`。新测试 `tests/test_instance_quit.py`（假 kernel32，不建真的命名对象）：修复前 11 项失败，
  修复后全过。真实的接管流程（两个快捷方式先后启动）仍要在 Windows 上试一次。

## 低

**处理状态**（2026-11-04，分支 `claude/low-fixes`，每项一个 commit，先写测试、确认它在修复前失败，再修）：

| 编号 | 状态 | commit | 新测试（quick） | 修复前 → 修复后 | 说明 |
|---|---|---|---|---|---|
| L1 | ✅ 已修复 | 31873dc | held_key | 3 项失败 → 全过 | 距上次按下超过 1.5 秒（系统按键重复延迟最长 1 秒）当新按下；`set_binding` / `start_learning` 清掉按住状态。没加 `_held_vk`：`_held` 只跟踪绑定键，换键时清掉就够了 |
| L2 | ✅ 已修复 | b213929 | learn_race | 2 → 全过 | `_finish_learning` 的检查和置位放进 `_learn_lock` |
| L3 | ✅ 已修复 | 199aecc | win_event_hook | 1 → 全过 | 失败时 `log.warning` 带错误码 |
| L4 | ✅ 已修复（补修见右） | 7564bf4 | key_name | 10 → 全过 | `MAPVK_VK_TO_VSC_EX`，扩展键置 lParam 第 24 位；只影响显示。**7564bf4 在真机上 10 个键没修好**（测试的假 user32 和真机不符），05 的 P6 补修；M-07 真实按键已确认（2026-11-05） |
| L5 | ✅ 已修复 | 88f6eca | d3d_staging | 3 → 全过 | release 后立即把 `_staging` 和尺寸清零 |
| L6 | ✅ 已修复 | 598b848 | d3d_release | 3 → 全过 | 只改异常路径：释放显卡 / device / context 再抛出 |
| L7 | ⏭ 跳过 | — | — | — | 修复风险过大：要定「连续失败几次就放弃 WGC」或冷却时间，这会改变截图后端的退路（放弃后独占全屏截出来是黑的）。参数要在 Windows 上模拟驱动重置才能定，云端没法验证；和 L8 是同一个策略问题，一起留给人工 |
| L8 | ⏭ 跳过 | — | — | — | 修复风险过大：「过一段时间重试」会和 L7 叠加（每次重试都可能再换下一套设备），重试间隔、上限同样要在 Windows 上实测 |
| L9 | ✅ 已修复 | 8533002 | session_init_fail | 2 → 全过 | 建到一半失败的会话放进模块级 `_half_built` 留着引用 |
| L10 | ✅ 已修复 | b51adab | clipboard_error | 6 → 全过 | `copy_to_clipboard` 内部捕获、记日志、返回 False |
| L11 | ✅ 已修复 | a5777d4 | save_png_fail | 1 → 全过 | 失败时 `unlink(missing_ok=True)` 再抛出 |
| L12 | ✅ 已修复（PR #2） | 5878a8b | clipboard（特征测试） | — | 阶段 6 的 P1：图已是 RGB 就不 convert |
| L13 | ✅ 已处理（PR #4，换了方案） | 453ecde | toast_card（特征测试） | — | 阶段 6 的 P3：缓存画好的卡片，不缓存字体（字体缓存每个字号常驻 +3.5 MB，见 PROGRESS D9）。同一句提示不再新建字体，新的文字仍会新建 |
| L14 | ✅ 已修复（PR #3 + M6） | ee9823e、2e32e53 | tray_icon、tray_refresh | — | 阶段 6 的 P2 按状态缓存图标；M6 状态没变时不重设图标 |
| L15 | ✅ 已修复 | 18bf92e | scan_fail | 7 → 全过 | EnumProcesses 失败 / 返回 0 个、快照为空时抛异常，GameWatcher 跳过这一轮 |
| L16 | ✅ 已修复 | bb167cf | idle_order | 4 → 全过 | 先设 `_idle_since` 再清标志 |
| L17 | ✅ 已修复 | c7ff386 | games_update | 4 → 全过 | 新增 `Config.update(key, change)`，在锁里读改写 |
| L18 | ✅ 已修复 | a06cd72 | config_save_fail | 11 → 全过 | `save()` 隔 0.2 秒重试 5 次，仍失败就记日志、提示「设置没保存上」，不抛异常 |

全部只在云端 Linux 上跑过测试（quick 27 过 4 失败，失败的是缺 Windows 模块的 add_game、blocklist_remove、yuzu_naming、dualsense），
合并前要回 Windows 用 gamesnap-build 跑 quick 和 all。L19–L21（安全一节）不在这次范围内。

| 编号 | 位置 | 问题 | 修复建议 | 把握 |
|---|---|---|---|---|
| L1 | `hotkey.py:232-242`、`138-140` | `_held` 不记按键码，抬起事件丢失（安全桌面、别的钩子吞掉、按住时 `set_binding`）会卡在 True：下一次真按被当成自动重复，吞掉却不截图 | 记 `_held_vk`；`set_binding`/`start_learning` 时重置；和上次按下的 `kb.time` 相差超过约 1 秒当新按下 | 高 |
| L2 | `main.py:300-303`、`hotkey.py:221-225` | `_finish_learning` 的「检查再置位」不加锁，按键恰好在 10 秒超时那一刻到时，超时 Timer 和学键线程各跑一次：既存了新键又提示「已取消」（`_finish_adding` 有锁，这里没有） | 加锁，照 `_finish_adding` 的写法 | 中 |
| L3 | `hotkey.py:170-171` | `SetWinEventHook` 返回值不查也不记日志，失败时前台切换和截图会话预热都没了，没有痕迹 | 失败时 `log.warning` | 高 |
| L4 | `hotkey.py:107-108` | `key_name` 不带扩展键位，Insert / Delete / Home / End / PgUp / PgDn / 方向键显示成小键盘的「Num 0」「Num 8」（只影响显示） | `MapVirtualKeyW(vk, MAPVK_VK_TO_VSC_EX)`，高字节 0xE0 时置 `1 << 24` | 高 |
| L5 | `d3d.py:164-172` | 先 `release(self._staging)` 再建新纹理，CreateTexture2D 抛错后 `_staging` 是悬空指针、尺寸还是旧的；目前异常后整块设备被换下所以没事，以后重试同一 Device 就是释放后使用 | 先建新的，成功后再释放旧的；或 release 后立即清零 | 高（事实）/ 现在不触发 |
| L6 | `d3d.py:128`、`151-152` | `GetDesc1` 抛错时当前 adapter 不释放；QI `ID3D11Multithread` 抛错时 device/context 泄漏（只在异常路径） | try/finally 释放 | 高 |
| L7 | `capture.py:216`、`283-285`、`321-324` | `_retired` 没有上限：错误持续时每按一次键换下并新建最多 2 套设备和会话（核显约 4MB、独显约 48MB + 16MB 显存） | 连续失败 N 次后置 `_wgc_broken`，或加冷却 | 中 |
| L8 | `capture.py:236-238`、`262-266` | 任何一次 `_gpu_for` 失败都永久置 `_wgc_broken`，驱动重置时的短暂失败也会让整局只能用 GDI（独占全屏下是黑的） | 区分首次导入失败和重建失败，后者过一段时间再试 | 中 |
| L9 | `capture.py:135-147` | `_Session.__init__` 中途抛错时已建的 pool / session 被 GC 回收，等于关闭会话，违背「开了就不关」 | except 里把已建对象放进 `_retired` 再抛 | 中 |
| L10 | `output.py:61-80`、`main.py:261-266` | 剪贴板 `EmptyClipboard`/`SetClipboardData` 抛异常会冒到 `finish_shot`：PNG 已存好却提示「截图失败」，计数不加 | `copy_to_clipboard` 内部捕获、记日志、返回 False | 高 |
| L11 | `output.py:55-57` | `img.save` 失败（磁盘满）留下 `.png.part` | except 里 `unlink(missing_ok=True)` 再抛 | 高 |
| L12 | `output.py:65` | 图像本来就是 RGB，`convert("RGB")` 多拷一整帧，`getvalue()[14:]` 再拷两次（4K 时瞬时多出近 100MB） | 已是 RGB 就不 convert（见阶段 5） | 高 |
| L13 | `toast.py:91-97` | 每次提示都重新 `ImageFont.truetype("msyh.ttc")` | `functools.lru_cache`（见阶段 5） | 中 |
| L14 | `main.py:486-497`、`421-423` | 每次 `refresh_tray` 都重画 256px 图标再 LANCZOS 缩小（截图后、状态变化时都会调） | 按状态缓存（见阶段 5） | 高 |
| L15 | `watcher.py:81-88`、`52-54` | `EnumProcesses` 返回值不查、快照失败返回空：被当成「游戏全退出」，摘钩子、下一轮再挂；连续失败达到 `exit_grace_sec` 就会在游戏中途退出 | 失败时抛异常，让 GameWatcher 跳过这一轮、保留上次结果 | 高（机制）/ 很少失败 |
| L16 | `main.py:303-304`、`356-358` | 先清 `learning` / `adding` 再重置 `_idle_since`：GameWatcher 恰好在两行之间轮询，会用旧的 `_idle_since` 判断，学键 / 添加刚结束就自动退出 | 先设 `_idle_since` 再清标志 | 高 / 窗口极小 |
| L17 | `main.py:368`、`394` | 「添加游戏」和「移除游戏」各自读改写 `cfg["games"]`，并发时后写的覆盖先写的 | `Config` 加一个在锁里完成读改写的 `update(key, fn)` | 中 |
| L18 | `config.py:71-77`、`main.py:308` | `save()` 不处理异常（杀毒 / 同步盘短暂占用时 `os.replace` 抛 PermissionError）：内存已改、后续步骤中断（`_finish_learning` 里监听没换新键、没游戏时钩子也不摘、托盘不刷新） | 短暂重试；仍失败就提示「设置没保存上」 | 中 |

## 待人工确认

- **Q1 菜单开着时被别的线程 `DestroyMenu`**（M6 的一种情况）：**2026-11-05 已在 Windows 上测过，无害**：`DestroyMenu` 成功，旧菜单继续显示，主菜单和子菜单照常能选、回调照常执行，200 次连续刷新不失败、句柄不漏。见 05 第 2 节 Q1。
- **Q2 低级键盘钩子超时被系统摘掉**：钩子回调要拿 GIL；别的线程在不释放 GIL 的长 C 调用里时，回调可能超过 `LowLevelHooksTimeout`，
  Windows 7 起会静默摘掉钩子，代码里没有检测。建议在日志里记钩子回调耗时观察。
- **Q3 `stop()` 超时后可能挂着两个钩子**：`InputListener.stop()` 的 `join(timeout=2)` 之后不查 `is_alive()`，线程卡住时 App 照样新建
  监听，一次按键截两张。只有线程卡死时才会发生。
- **Q4 `get_dxgi_surface_from_object` 返回借用指针还是已 AddRef 的指针**（`capture.py:183`）：注释说「同 dxcam」，但 dxcam 用的是
  Desktop Duplication。若是已 AddRef 的，每张截图多留一个引用。要看 pywinrt 源码。
- **Q5 暂存纹理用会话记录的尺寸而不是帧纹理的实际尺寸**（`capture.py:182`、`193`）：重建帧池后若还取到旧尺寸的帧，CopyResource
  因尺寸不一致静默不执行，读回全零或上一张画面。可用 `ID3D11Texture2D::GetDesc` 取实际尺寸。
- **Q6 会话按 HMONITOR 做键**（`capture.py:215`）：显示配置变化后句柄值可能变，旧会话一直留着；句柄被复用时可能拿错会话。
- **Q7 画面静止时用的是很久以前的帧**（`capture.py:295-298`）：帧池满期间的新帧被丢弃，超时后的 `held` 可能不是当前画面。
- **Q8 托盘「退出」和自动退出同时触发**（`main.py:452-454`）：`_quitting` 的检查和置位没加锁，两边都执行时也只是重复 stop 和
  PostMessage，没看到实际危害。
- **Q9 pid 复用**（`watcher.py:18`）：最坏 30 秒内把复用了游戏 pid 的非游戏进程当成游戏（吞键、晚一点退出），属已知取舍。

## 已核对、没发现问题

- d3d.py 的 7 个虚表序号（CreateTexture2D=5、Map=14、Unmap=15、CopyResource=47、EnumAdapters1=12、GetDesc1=10、
  SetMultithreadProtected=5）、4 个 IID、`_PATH_INFO`（72 字节）/ MODE_INFO（64 字节）/ `_SOURCE_NAME` 等结构体布局。
- 「HRESULT 不检查、把 NULL 传进驱动」不成立：`D3D11CreateDevice`、QI、`GetDesc1`、`CreateTexture2D`、`Map` 的 restype 都是
  `ctypes.HRESULT`，失败时 ctypes 自动抛 OSError（异常之后的状态问题见 L5、L6）。
- `wait_frame` 的超时判断正确，0.5ms 轮询有上限。
- dualsense.py：通知没触发前不重复登记；`MAX_TRIES` / `_reported` 计数、拔插后重置、svcl 超时处理正确。
- `on_poll`：启动器开着一直等、学键和添加期间不退出、宽限从最后一次看到游戏起算，都和 CLAUDE.md 的约定一致。

## 安全

范围：全仓库（13 个模块 + tests/ + build.py），检查注入（SQL / 命令 / 模板）、鉴权与越权、敏感信息硬编码或写入日志、
不安全的反序列化、依赖中已知的高危版本。编号接续上面各级。

### 检查过程与结论

| 类别 | 怎么查的 | 结论 |
|---|---|---|
| SQL / 模板注入 | 全仓库没有数据库、没有模板引擎 | 不适用 |
| 命令注入 | 列出所有 `subprocess.*`、`ShellExecuteW`、`os.startfile`、`os.system`、`shell=True` 调用点 | 没有。`subprocess` 都是参数列表、无 `shell=True`（`dualsense.py:145` 的 svcl 参数来自 HKLM 下的端点 GUID，写 HKLM 本身需要管理员；`build.py:72` 是开发工具）。`ShellExecuteW`（`main.py:514`、`556`）的参数来自本人的命令行 / 快捷方式；`relaunch_as_admin` 用 `list2cmdline` 正确转义。`os.startfile(save_dir)`（`main.py:449`）之前的 `mkdir(exist_ok=True)` 遇到已存在的文件会抛 FileExistsError，借不了它执行现成的 exe |
| 路径穿越 | 追踪写文件的路径来源 | 截图文件夹名来自窗口标题，`..` 会写到 GameShots 上一级，见 M2（只写 PNG，影响很小） |
| 鉴权与越权 | 本地工具，没有网络接口；看以管理员身份运行时会碰哪些普通用户可写的东西 | 见 L19、L20 |
| 敏感信息 | `grep` 源码和全部 git 历史：password / secret / token / api_key / 私钥头 / `ghp_` / `sk-` | 没有密钥、令牌。日志只有进程名、窗口标题、截图路径，都在本机。仓库是公开的，CLAUDE.md 里有 Windows 用户名和个人文件夹名，见 L21 |
| 不安全的反序列化 | `grep` pickle / marshal / yaml / eval / exec | 只有 `json.loads`（`config.py`），没有不安全的反序列化 |
| 依赖已知漏洞 | 用 OSV（api.osv.dev）按 requirements.txt 的下限版本逐个查；再查 Pillow 各大版本 | 见 M9；mss 10.0、pystray 0.19.0、pywin32 306、pyinstaller 6.0.0、winrt-runtime 3.2.0 在 OSV 里没有记录 |

### M9 requirements.txt 允许装上有已知高危 / 严重漏洞的 Pillow
- **位置**：`requirements.txt:10`（`pillow>=10.1`）
- **问题**：下限 10.1.0 在 OSV 里有 51 条 GHSA（含 CRITICAL：CVE-2023-50447 `ImageMath.eval` 任意代码执行，10.2.0 修复；HIGH：
  CVE-2024-28219 缓冲区溢出，10.3.0 修复）；12.1 / 12.2 / 12.3 分别还有 60 / 54 / 41 条 GHSA（多数在 12.3.0、13.0.0 修复）。截至 2026-11-03，
  只有当前最新的 13.0.0 没有已知漏洞。用户 gamesnap-build 环境里实际装的版本未知。
- **实际可利用性：低**。GameSnap 不打开任何外来图片：只编码自己抓的帧（PNG / BMP）、画托盘图标和提示卡片、用系统字体渲染文字；
  绝大多数漏洞在 TIFF / GIF / PDF / JPEG 等解码器、`ImageMath`、`ImageCms` 里，用不到。字体相关的两条（12.2.0 的字体整数溢出、
  13.0.0 的描边渲染 invalid free）需要恶意字体或描边，GameSnap 也不满足。
- **修复建议**：回 Windows 用 `gamesnap-build\python.exe -m pip show pillow` 看实际版本；升到 13.x 是大版本升级（RUNBOOK 禁止
  这里做），需要在 Windows 上跑 `all` 并重新打包验证后再改下限。放进「待人工确认」。
- **把握**：高（版本事实）；可利用性低。
- **状态**：✅ 2026-11-04 在 Windows 上升到 13.0.0、下限改成 `pillow>=13.0`，逐字节对比和全量测试通过（05 第 4 节）。中危修复时跳过的原因：RUNBOOK 工作规则禁止升级依赖的大版本，
  而且打包版要在 Windows 上重新打包、跑 all 才能验证，云端做不了。

### 低

| 编号 | 位置 | 问题 | 修复建议 | 把握 |
|---|---|---|---|---|
| L19 | `instance.py:26` | 命名对象的安全描述符给 Everyone 完全控制（GA）、低完整性标签：同一会话里任何进程（包括低完整性的沙箱进程）都能 SetEvent 让 GameSnap 退出，或抢先占用 `SingleInstance` / `Elevated` 名字让它起不来、无法被管理员实例接管。只是拒绝服务，不能提权 | 标签改成中完整性（ME）就足够让普通和管理员实例互通；访问权限只给 SYNCHRONIZE / EVENT_MODIFY_STATE 等需要的几项 | 中 |
| L20 | `main.py:573-576`、`dualsense.py:40`、`145`、`config.py:13` | 以管理员身份运行的 GameSnap 用的文件都在普通用户可写的位置：`dist\GameSnap\` 里的 exe / DLL / .pyd、`tools\svcl\svcl.exe`（DualSense 不对时以管理员身份执行）、`%APPDATA%\GameSnap\config.json`（`save_dir` 决定管理员进程在哪儿建目录、写 PNG）。已在本用户权限下运行的恶意程序替换其中任何一个，下次双击「米哈游启动器 + 截图」点 UAC「是」时就以管理员身份执行。微软不把 UAC 当安全边界，属加固项 | 要加固就把 dist 装到 `Program Files`（普通用户不可写），svcl 随之移动；单独加固 config 意义不大 | 高（事实）/ 加固项 |
| L21 | `CLAUDE.md:14`、`26` | 公开仓库里有 Windows 用户名和个人文件夹布局（`C:\Users\<用户名>\…`、`D:\00…Documents\图片`），属轻微信息暴露 | 若不希望公开，改成占位符（如 `%USERPROFILE%`）；是否在意由用户决定 | 高 |
