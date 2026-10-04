# ClassicWorld 翻译助手

Windows 悬浮翻译小窗，面向冒险岛 Classic World 的交易、组队和日常聊天。输入中文（或其他语言），得到玩家常用的英文简写，自动复制并切回游戏，由你自己按 Ctrl+V 和回车发送。

例如：`废弃都市组队任务来法师三缺一 → R> KPQ mage 3/4`，`收柠檬100个 → B> Lemon x100`。

## 使用

下载 [Releases](https://github.com/a16797/classicworld-translator/releases) 中的 Windows ZIP，完整解压，双击 `CWTranslator.exe`。详细说明见 [使用说明.txt](使用说明.txt)。

- 默认快捷键：Ctrl+Alt+Q；可在设置里直接录入其他组合。
- 词库与常用喊话可离线使用；新句子需要你自己的 DeepSeek API Key。
- 下拉列表能查物品、怪物、地图、NPC、技能和现成说法。
- 改过的译文点“复制”后记入“我的喊话表”。
- 当前为中→英喊话模式，不包含截图识别或完整的英→中阅读页。

程序未签名。如果 Windows 显示未知发布者，请先核对下载来源与发布页的 SHA256；不要因为“未签名”就直接判断安全或不安全。

## API Key 与本地数据

设置页显示当前 Key 来源、配置文件路径，并提供“打开数据文件夹”。

所有个人数据在 `%APPDATA%\CWTranslator\`，与程序安装目录分开：

| 文件 | 内容 |
| --- | --- |
| `settings.json` | 设置与 Windows DPAPI 加密后的 Key；不写明文 Key |
| `我的喊话表.csv` | 你修改并保存的中英喊话 |
| `cache.json` | 联网翻译缓存 |
| `usage.json` | 候选的使用次数 |

已保存 Key 优先；未保存时，可选择使用本机 `DEEPSEEK_API_KEY` 环境变量。勾选“清除 Key 并停用环境变量”并保存后，本程序不再使用这两种 Key；不会删除其他程序共用的 Windows 环境变量。

本地命中不发送翻译请求；新句子通过 HTTPS 发往固定的 DeepSeek 官方 API，Key 放在 Authorization 头中用于认证。程序不上传个人配置、喊话表或缓存文件，也不设中转服务器。窗口可能提前建立 TLS 连接，但不会为此发送 Key 或聊天文本。

DPAPI 使用当前 Windows 用户身份保护 Key，不能防住已经以同一用户身份运行的恶意软件。跨电脑或用户复制加密配置后，可能需要重新填写 Key。参考 [Microsoft DPAPI 文档](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata) 和 [DeepSeek 认证文档](https://api-docs.deepseek.com/api/deepseek-api/)。

## 源码运行与打包

需要 Windows、Python 3.11 或更新版本、PowerShell 7：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py'
.\.venv\Scripts\python.exe tests\smoke_app.py
pwsh -File build.ps1
```

产物：`dist/ClassicWorld翻译助手-v1.0.1.zip`。版本由 `app.py` 中的 `APP_VERSION` 控制。

以后每次发布自动递增版本号，并先核对 GitHub 已发布版本：修复升补丁号，新增功能升次版本号，不兼容改动升主版本号。窗口、exe 属性、ZIP 与 Release tag 同步更新；仅修改文档不另发安装包。

公开源码的运行核心在 `vendor/`，聊天词库在 `data/`，不依赖作者电脑上的 Skill。普通打包直接使用随仓库发布的数据；维护者的 `pwsh -File build.ps1 -RefreshData` 才调用 `prepare_data.py` 从本机 `cw-chat-assistant` Skill 重新导出，之后需要审查新的数据与核心快照。

`build.ps1` 执行单元测试、真实窗口冒烟测试、PyInstaller 打包、密钥与个人配置扫描，再生成 ZIP。测试默认不调用付费 API；`smoke_app.py --network` 会真实使用当前环境中的 Key。

## 翻译顺序

我的／默认喊话表 → 本地翻译缓存 → 内置短句与词库原句 → DeepSeek。

聊天词库包含 7,326 条名称与聊天词条、1,892 句原句直出。61 条中英物品不一致的样例不用于整句直出，清单在 `data/待核对样例.csv`。缓存按词库、模型与提示词版本区分。

## 安全与验证

见 [安全说明](SECURITY.md)。公开仓库和发布包不包含个人设置、环境变量文件、聊天缓存或本地开发记录。

窗口流程与本地翻译有自动测试。真实游戏的粘贴支持、独占全屏切换、管理员权限场景以及其他电脑的 SmartScreen／杀毒软件表现仍需实际验证；设置按 70 个字符提醒，游戏聊天的真实上限尚未核实。

## 数据来源

游戏名称来自 MSCW 名称资料，词库还包含游戏常用英文、词语和句子。导出的聊天名称资料按已获授权的范围随工具分发，不包含完整资料库、任务对话或个人历史。红枫叶图标取自游戏素材，其权利属于原权利人。本项目是非官方工具。
