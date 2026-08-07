"""PaperLens 版本号。

统一版本号：core 包版本、/api/health、README/PROGRESS 均引用此处。
解析器与提示词版本各自独立演进（见 parse_router / prompts.PROMPT_VERSION），
但随主版本一起发布。
"""

__version__ = "1.0.0"

# 当前架构代际（V3 = DocumentIR 时代，V4 = DocumentGraph 收束中）
ARCH_GENERATION = "V1.0"
