"""打包成文件夹版（输出到 dist\\GameSnap\\，入口是 dist\\GameSnap\\GameSnap.exe）。

    D:\\anaconda3\\envs\\gamesnap-build\\python.exe build.py

不打成单个 exe：单文件版每次启动都要先把约 64MB 解压到 %TEMP%（多花约 1 秒、多一个进程），
被强制结束时解压目录还会残留。文件夹版直接运行，启动约 0.3 秒。

不加 --uac-admin：程序启动时自己检查权限并通过 UAC 重新以管理员身份启动，
效果一样（双击会弹 UAC），但保留了 --no-elevate 调试开关。

tools\\svcl\\ 里的 NirSoft svcl.exe（改 DualSense 声音设置用）会一起打进去，见 README「DualSense 手柄震动」。
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
SVCL_DIR = HERE / "tools" / "svcl"
WINRT_MODULES = [
    "winrt.runtime",
    "winrt.system",
    "winrt.windows.foundation",
    "winrt.windows.foundation.collections",
    "winrt.windows.graphics",
    "winrt.windows.graphics.capture",
    "winrt.windows.graphics.capture.interop",
    "winrt.windows.graphics.directx",
    "winrt.windows.graphics.directx.direct3d11",
    "winrt.windows.graphics.directx.direct3d11.interop",
]
EXCLUDES = ["numpy", "dxcam", "comtypes", "tkinter"]


def main() -> None:
    sys.path.insert(0, str(HERE))
    from main import make_icon

    BUILD.mkdir(exist_ok=True)
    ico = BUILD / "gamesnap.ico"
    make_icon("active").save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64)])

    if (SVCL_DIR / "svcl.exe").is_file():
        # 整个文件夹原样带上（NirSoft 的许可要求分发时附带全部文件）；运行时在 _internal\tools\svcl\
        data = ["--add-data", f"{SVCL_DIR}{os.pathsep}tools/svcl"]
    else:
        data = []
        print("警告：没有 tools\\svcl\\svcl.exe，打出来的版本发现 DualSense 设置不对时只会提醒，不会自动改")

    cmd = [
        # --clean：不复用上次的依赖分析缓存（换环境/改 PATH 后缓存会让漏掉的 DLL 继续漏）
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--noconsole",
        "--name", "GameSnap", "--icon", str(ico),
        "--distpath", str(HERE / "dist"), "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
        "--hidden-import", "pystray._win32",
        # winrt 是命名空间包，各子模块之间在 C 扩展里互相导入，PyInstaller 扫描不全，只能逐个列出
        *[arg for mod in WINRT_MODULES for arg in ("--hidden-import", mod)],
        # 旧版用过、现在不再需要的库：即使环境里还装着也别打进去
        *[arg for mod in EXCLUDES for arg in ("--exclude-module", mod)],
        *data,
        str(HERE / "main.py"),
    ]
    # conda 环境的 DLL（如 _ctypes 依赖的 ffi-8.dll）在 Library\bin，未 activate 时不在 PATH 上，
    # PyInstaller 找不到就不会打包进去，exe 启动时报 “DLL load failed while importing _ctypes”
    env = dict(os.environ)
    lib_bin = Path(sys.executable).parent / "Library" / "bin"
    if lib_bin.is_dir():
        env["PATH"] = f"{lib_bin}{os.pathsep}{env.get('PATH', '')}"
    print(" ".join(cmd))
    subprocess.run(cmd, check=True, cwd=HERE, env=env)
    print("完成：", HERE / "dist" / "GameSnap" / "GameSnap.exe")


if __name__ == "__main__":
    main()
