# 第三方组件说明

本工具使用下列开源组件。它们的许可证适用于各自组件，不是为本项目的游戏词库或图标授予许可。

| 组件 | 用途 | 许可证和源码 |
| --- | --- | --- |
| Python | 运行环境和标准库 | [随运行环境的许可原文](licenses/Python-LICENSE.txt)；[官方许可说明](https://docs.python.org/3/license.html)；[源码](https://github.com/python/cpython) |
| Tcl/Tk | 窗口界面 | [随包 Tk 许可](licenses/Tk-license.terms.txt)；[Tcl/Tk 许可说明](https://www.tcl-lang.org/software/tcltk/license.html) |
| Pillow 12.3.0 | 图标处理 | MIT-CMU；[完整许可及随库组件声明](licenses/Pillow-LICENSE.txt)；[源码](https://github.com/python-pillow/Pillow) |
| pystray 0.19.5 | 右下角托盘图标 | LGPLv3；[LGPL](licenses/pystray-COPYING.LGPL.txt) 与 [GPL](licenses/pystray-COPYING.txt)；[该版源码](https://github.com/moses-palmer/pystray/tree/v0.19.5) |
| six 1.17.0 | pystray 的兼容依赖 | MIT；[完整许可](licenses/six-LICENSE.txt)；[源码](https://github.com/benjaminp/six) |
| PyInstaller 6.22.3 | 生成 Windows 程序 | [许可与打包例外](https://pyinstaller.org/en/stable/license.html)；[许可原文](licenses/PyInstaller-COPYING.txt)；[源码](https://github.com/pyinstaller/pyinstaller) |

`licenses/` 保留所用组件随安装包提供的版权与许可原文。pystray 等第三方代码未作修改；按上游版本和 `requirements.txt` 可取得对应源码，再按开发说明重建程序。许可文件随 Windows 程序一起发布。
