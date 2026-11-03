# 03 性能分析与优化计划

## 测量方法

- 环境：claude.ai 云端 Linux 容器，Python 3.12.3，Pillow 13.0.0；测试图 1920×1080，「渐变 + 40 块噪声」，比纯噪声或纯色更像游戏画面。
- 工具：新增 `tests/bench_logic.py`。它用 `tests/winstubs.py` 在 Linux 上把 Windows 模块换成桩，测的都是项目里的真函数。
  每项跑 5 轮，每轮循环 N 次取平均，报告 5 轮的中位数。另用 cProfile 拆分耗时，用 tracemalloc 记 Python 侧的峰值内存。
- 剪贴板换成只记录数据的假 `win32clipboard`，不碰真剪贴板。
- 字体：Windows 上 `msyh.ttc` 第一下就能找到；Linux 上找不到，Pillow 会把字体目录全翻一遍。为了接近 Windows，基准把
  `wqy-zenhei.ttc`（16MB 的中文 TTC，和 msyh.ttc 差不多大）链接成 `msyh.ttc`。
- 测不到的部分：WGC 抓帧、D3D 读回、托盘、浮层窗口、进程快照都只能在 Windows 上实测，见本文最后一节。
- 云端计时有波动（同一项各轮可差 30%），所以只比较相对提升。

## 基线（`bench_logic.py 5`，2026-11-03，claude/review-fixes @ a06558d）

| 项 | 调用频率 | 中位数 | 各轮 |
|---|---|---|---|
| save_png | 每张截图（Saver 线程） | **220.6 ms** | 269.5, 218.9, 282.2, 209.5, 220.6 |
| copy_to_clipboard | 每张截图（Saver 线程，默认开） | **13.7 ms**，Python 侧峰值 11.9 MB | 20.6, 14.4, 12.8, 13.7, 13.3 |
| render_card | 每次提示（Toast 线程） | **7.7 ms** | 5.4, 7.7, 8.2, 8.6, 7.0 |
| to_image_decode（BGRX→RGB） | 每张截图（CaptureWorker） | 3.2 ms | 3.1, 3.1, 3.2, 3.2, 3.3 |
| make_icon | 每次 refresh_tray：每张截图、每次状态变化 | **1.5 ms** | 2.3, 2.5, 1.5, 1.5, 1.4 |
| premultiplied_bgra | 每次提示 | 0.18 ms | |
| scanner_scan（300 个进程） | 每 2 秒 | 0.037 ms | |
| is_black | 每张截图 | 0.011 ms | |

一张截图在 Python 侧的 CPU 时间约为 3.2 + 220.6 + 13.7 + 7.7 + 0.2 + 1.5 ≈ **247 ms**，其中 save_png 约占 89%。
这些都在按键钩子线程之外（截到的帧不受影响），但会推迟「✓ 已截图」提示的出现时间（`finish_shot` 存完 PNG、写完剪贴板才提示），
而且都要和钩子回调抢 GIL（见 02-findings Q2）。

## 热点分析

### P1 `copy_to_clipboard` 的 DIB 构造（`output.py:61-66`）
- **当前复杂度**：O(W·H)，整帧拷贝 4 次：`convert("RGB")`（图本来就是 RGB，纯复制，C 侧多一帧）→ BMP 编码进 BytesIO →
  `getvalue()` 复制 → `[14:]` 再复制。
- **数据**：13.7 ms；Python 侧峰值 11.9 MB（1080p 一帧 5.9 MB），再加上 C 侧多出的一帧。4K 时一帧 23.7 MB，瞬时多占约 70 MB。
  cProfile 显示 `convert` 约占 60%。
- **方案**：图已是 RGB 就不 convert；去 BMP 文件头时用 `getbuffer()[14:].tobytes()`，只复制一次。另一种做法是自己拼 40 字节的
  BITMAPINFOHEADER，再加上 `tobytes("raw", ("BGR", stride, -1))`，测出来和前者一样快，但代码更多，不选。
- **预计收益**：耗时约 -60%（16.1 → 6.2 ms），Python 峰值约 -50%，C 侧少一帧。
- **风险**：低。三种分辨率（含奇数宽度 1921）下输出与原来**逐字节相同**；写剪贴板的部分不变，仍然传 bytes。

### P2 `make_icon` 每次都重画（`main.py:486-497`，调用点 `main.py:423`）
- **当前复杂度**：O(256²) 绘制 + LANCZOS 缩到 64×64；只有 3 种状态，结果完全由状态决定。
- **数据**：1.5 ms / 次。
- **方案**：3 种状态各画一次缓存起来，每次返回一份拷贝。返回拷贝是为了保持「每次都是新对象」的语义，调用方改了图也不会污染缓存。
- **预计收益**：约 -99.7%（1.56 → 0.005 ms）。绝对值不大，但每张截图和每次状态变化都要调一次。
- **风险**：很低。像素和原来逐字节相同。

### P3 `render_card` 每次新建字体对象（`toast.py:91-104`）
- **当前复杂度**：每次提示都 `ImageFont.truetype(...)`（Windows 上还要按名字在字体目录里找到 msyh.ttc）。
  字体对象本身只要 0.16 ms，但新对象的 FreeType 字形缓存是冷的：cProfile 里 `getbbox`（`Font.getsize`）每次约 2 ms，
  `text` 约 1.3 ms。LANCZOS 缩小（3 倍超采样）约 3.7 ms，是剩下的大头。
- **数据**：7.7 ms / 次（基准）；用 cProfile 单独量：6.8 ms，缓存字体后 4.3 ms。
- **方案**：`_font(size)` 加 `functools.lru_cache`。同一缩放下字号只有一个，多显示器不同 DPI 时也只有几个。
- **预计收益**：约 -35%。
- **风险**：低。输出像素不变。FreeType 字体对象不是线程安全的，但 render_card 只在 Toast 线程里调；测试里在主线程调，
  也是单线程。

### P4 `save_png`（`output.py:55-56`），不选
- 耗时最大（220 ms），时间几乎都在 zlib（compress_level=6）里，O(W·H)。
- 能提速的只有降低压缩级别（这张测试图上 level 1 约 91 ms），或者先提示、后保存。前者会改变输出文件（大小、字节），
  后者改变「提示 = 已存好」的语义，都属于需要用户决定的行为变化，不符合「风险低」，**不进入阶段 6**，写进总结的建议里。

### P5 其他，不需要优化
- `to_image` 的 BGRX→RGB 解码 3.2 ms，已经是 Pillow 的 C 解码、一次遍历。
- `render_card` 的 LANCZOS 缩小：换便宜的滤镜会改变卡片外观，不做。
- `scanner_scan` 0.037 ms / 轮询、`is_black` 0.011 ms、`premultiplied_bgra` 0.18 ms：可以忽略。
- 每次轮询的 `games_lower()` / `launchers_lower()` 只重建很小的 dict / set，可以忽略。

## 排序与选择

按「收益高、风险低」排序（收益 = 单次节省 × 调用频率，并参考相对提升；风险 = 输出是否逐字节不变、是否只能在 Windows 上验证）：

| 排名 | 项 | 单次节省 | 相对提升 | 输出 | 风险 | 进入阶段 6 |
|---|---|---|---|---|---|---|
| 1 | P1 copy_to_clipboard | 约 8–10 ms + 一帧内存 | 约 -60% | 逐字节相同 | 低 | ✅ `claude/perf-clipboard-dib` |
| 2 | P2 make_icon 缓存 | 约 1.5 ms | 约 -99% | 逐字节相同 | 很低 | ✅ `claude/perf-tray-icon-cache` |
| 3 | P3 render_card 字体缓存 | 约 2.5 ms | 约 -35% | 像素相同 | 低 | ✅ 实际做成 `claude/perf-toast-card-cache`（见下） |
| — | P4 save_png 压缩级别 | 约 100 ms | 约 -50% | 文件变化 | 需用户决定 | ❌ |

## 只能在 Windows 上测的部分（留给用户）

- 按键 → 抓到帧：日志里每张截图都记了「帧上屏-按键」和「按键→抓到」，README 里的实测是 7–13 ms。
- `snapshot_names` 约 7 ms CPU（作者实测），只在出现新 pid 时调用。
- `refresh_tray` 里 pystray 每次改图标都写一个临时 ICO 再 `LoadImage`。02-findings M6 / L14 建议「状态没变就不设图标」，
  这能省掉这部分开销，但会改变 refresh_tray 的行为，这里不做。
- 启动耗时：`tests\bench_startup.py`。

## 阶段 6 结果

| 项 | PR（→ claude/review-fixes） | 采用的方案 | 基准中位数（前 → 后） | 内存 |
|---|---|---|---|---|
| P1 | https://github.com/OranngeAustin/game_snap/pull/2 | 图已是 RGB 就不 convert | 13.65 / 12.45 → 5.09 / 7.40 ms（-40%～-60%） | 4K 单次峰值 RSS -8 MB |
| P2 | https://github.com/OranngeAustin/game_snap/pull/3 | `lru_cache` 按状态缓存，返回拷贝 | 1.481 / 2.323 → 0.003 / 0.004 ms（-99.8%） | 常驻 +48 KB |
| P3 | https://github.com/OranngeAustin/game_snap/pull/4 | 缓存画好的卡片（`lru_cache(maxsize=4)`），返回拷贝 | 同一句提示 9.06 / 7.07 / 8.24 → 0.004–0.005 ms（-99.9%）；全不命中时不变 | 实际场景无可测差别；最坏 +3 MB（glibc 堆碎片） |

P3 原计划给 `_font` 加缓存：耗时 -34%，但每个字号常驻约 +3.5 MB（4 个字号 +14 MB），不划算，所以改成缓存卡片。
P1 试过 `getbuffer()[14:].tobytes()`，没有收益（CPython 3.12 的 `getvalue()` 本来就不复制），所以没采用。
