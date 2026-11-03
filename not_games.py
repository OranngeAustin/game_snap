"""「添加游戏」时不收的程序（进程名，小写）。

这是公开仓库里的精简版，只留了几项示例；完整名单只在本机，不上传。

只拦认得出的软件，没列到的照样会被收下；加错了在托盘「游戏名单」里移除。分两部分：
- GENERAL：各台电脑上都常见的软件；
- THIS_PC：按这台电脑的开始菜单、桌面快捷方式、已安装程序和商店应用整理的非游戏软件。
不要收 python.exe、javaw.exe（Minecraft Java 版）、dotnet.exe（tModLoader）、mono.exe、nw.exe、electron.exe
这类也会用来跑游戏的运行环境，也不要收 game.exe、start.exe、main.exe 这类游戏也常用的通用名字。
微信小游戏跑在 WeChatAppEx.exe 里（小程序、公众号文章也是它），所以它也没收。
"""

GENERAL = {
    # 桌面、任务栏这些系统界面
    "explorer.exe", "taskmgr.exe", "notepad.exe",
    # 游戏平台的客户端（不是游戏本身）
    "steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe",
    # 浏览器
    "chrome.exe", "msedge.exe", "firefox.exe",
    # 编辑器、终端
    "code.exe", "windowsterminal.exe",
    # GameSnap 自己
    "gamesnap.exe",
}

THIS_PC = {
    # Windows 自带的工具
    "magnify.exe", "osk.exe", "charmap.exe",
}

NOT_GAMES = GENERAL | THIS_PC
