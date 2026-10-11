"""单词查词接口（M4 / FR-S6）。

- `GET /api/dict/{word}`  查询单个英文单词：ECDICT 离线词库 + 词形还原。

设计要点：
- 完全离线命中词库；词库未收录时才退回在线翻译给「参考释义」（可配置关闭）。
- 词库未安装不报错，返回 `found=false` + 中文提示，前端据此引导安装。
- 始终返回牛津 / 朗文跳转链接，作为词库缺词时的补充手段（FR-S6）。
"""

from __future__ import annotations

import logging
import urllib.parse

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.schemas.dict import DictForm, DictResult
from app.services import dict as dict_service
from app.services import translate as translate_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dict", tags=["dict"])

_OXFORD_URL = "https://www.oxfordlearnersdictionaries.com/definition/english/{word}"
_LONGMAN_URL = "https://www.ldoceonline.com/dictionary/{word}"


def _links(word: str) -> tuple[str, str]:
    encoded = urllib.parse.quote((word or "").strip().lower())
    return _OXFORD_URL.format(word=encoded), _LONGMAN_URL.format(word=encoded)


@router.get("/{word}", response_model=DictResult)
def lookup_word(word: str) -> DictResult:
    """查询一个英文单词（含词形还原）。"""
    query = dict_service.normalize(word)
    if not query:
        raise HTTPException(status_code=400, detail="请提供要查询的单词")
    if not dict_service.is_lookupable(query):
        raise HTTPException(status_code=400, detail="一次只能查询一个英文单词")

    oxford, longman = _links(query)

    # 词库未安装：不报错，给出指引（在线链接仍可用）
    if not dict_service.available():
        return DictResult(
            query=query,
            found=False,
            notice="词典词库尚未安装，暂时无法给出站内释义；"
                   "可先跳转牛津 / 朗文在线查看，或运行 fetch_dict.py 安装词库。",
            source="none",
            oxford_url=oxford,
            longman_url=longman,
        )

    result = dict_service.lookup(query)
    if result.found and result.entry is not None:
        entry = result.entry
        word_for_link = entry.word or query
        oxford, longman = _links(word_for_link)
        return DictResult(
            query=query,
            word=entry.word,
            found=True,
            lemma=result.lemma,
            via=result.via,
            phonetic=entry.phonetic,
            translation=entry.translation,
            definition=entry.definition,
            pos=entry.pos,
            tags=entry.tags,
            collins=entry.collins,
            oxford=entry.oxford,
            exchange=entry.exchange,
            forms=[DictForm(**item) for item in entry.forms],
            source="ecdict",
            oxford_url=oxford,
            longman_url=longman,
        )

    # 词库未收录 → 在线翻译兜底（仅参考）
    if settings.dict_online_fallback:
        translated = translate_service.translate(query, src="en", tgt="zh")
        if translated.get("text"):
            return DictResult(
                query=query,
                word=query,
                found=True,
                via="online",
                translation=[translated["text"]],
                source="online",
                notice="词库未收录该词，以下为在线翻译结果，仅供参考。",
                oxford_url=oxford,
                longman_url=longman,
            )

    return DictResult(
        query=query,
        found=False,
        notice="词库未收录该词，可点击下方按钮跳转牛津 / 朗文查看。",
        oxford_url=oxford,
        longman_url=longman,
    )
