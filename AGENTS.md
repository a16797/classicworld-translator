# 项目约定

- 对外名称：ClassicWorld 翻译助手；仓库：classicworld-translator。
- 每次发布由代理自动递增版本号，不需要用户指定数字。先核对 `app.py` 的 APP_VERSION 与 GitHub 已发布版本，避免重号。
- 修复问题：补丁号 +1；新增功能：次版本号 +1、补丁号归零；不兼容改动：主版本号 +1、其余归零。单纯文档更新不另发安装包版本。
- APP_VERSION 是代码版本唯一源；窗口、exe 属性、ZIP 名称和 GitHub tag 保持一致。
- 发布 GitHub Release 时附 Windows ZIP、SHA256 和简要更新说明；资产名称使用 ClassicWorld-Translator-vX.Y.Z-Windows.zip。
- API Key、个人配置、聊天缓存、环境变量文件和本地开发记录不得进入公开仓库或发布包。提交前跑 tools/scan_public.py，发布前跑单元测试和窗口冒烟测试。
- 用户数据目录保留 `%APPDATA%\CWTranslator`，exe 保留 CWTranslator.exe，以兼容升级。
