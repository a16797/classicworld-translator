# 翻译核心快照

`fast_translate.py` 和 `lookup.py` 是本项目自有 `cw-chat-assistant` 翻译核心的发布快照（2026-10-03）。公开版本固定使用此目录，不加载用户电脑上的 Skill 脚本。

运行时使用随包 `data/cw-chat-dict.sqlite3`；不包含个人 Key、聊天缓存或完整个人资料库。更新上游核心后，需要在这里同步经过审查的代码并运行测试。
