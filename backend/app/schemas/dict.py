"""词典查询相关的响应模型（M4 / FR-S6）。"""

from pydantic import BaseModel, Field


class DictForm(BaseModel):
    """词形变化的一项，如 `过去式：went`。"""

    label: str
    value: str


class DictResult(BaseModel):
    """一次查词的结果。

    - `found=False` 时 `notice` 会给出原因（未安装词库 / 未收录），前端据此展示。
    - `lemma` 非空表示查询词是变形，已还原到原型（`word` 为原型）。
    """

    query: str                      # 用户查询的原词（归一化后）
    word: str = ""                  # 命中的主词形（还原后）
    found: bool = False
    notice: str | None = None       # 未命中时的说明

    lemma: str | None = None        # 还原出的原型
    via: str = ""                   # exact / exchange / lemminflect / rule / online

    phonetic: str = ""
    translation: list[str] = Field(default_factory=list)
    definition: list[str] = Field(default_factory=list)
    pos: str = ""
    tags: list[str] = Field(default_factory=list)   # 考纲标签（中文）
    collins: int = 0                # 柯林斯星级 0-5
    oxford: int = 0                 # 是否牛津三千核心词
    exchange: dict[str, str] = Field(default_factory=dict)
    forms: list[DictForm] = Field(default_factory=list)

    source: str = "ecdict"          # ecdict / online
    oxford_url: str = ""
    longman_url: str = ""
