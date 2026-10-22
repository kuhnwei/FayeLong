"""`app.core.config.static_dir()` 的候选选择测试 —— **锁的是前端切换语义**。

为什么要单独一个文件
--------------------
`static_dir()` 决定后端托管哪一套前端产物。它是「开发环境 Vue 产物 / 打包环境
static」的唯一切换点：改 `STATIC_CANDIDATES` 的顺序 + 重启即生效，后端代码零改动
（见 `docs/REFACTOR-PLAN-001-执行计划.md` §8/§9）。

在 P5-2 之前它**零覆盖** —— 这不是「少写了几条用例」，而是切换机制没有护栏：
一旦有人把「**第一个含 index.html 的候选胜出**」改成「后者优先」或「合并多个
目录按修改时间取新」，整套用例仍会全绿，而线上会静默挂错前端。

本文件锁的五件事
----------------
1. 每个候选单独存在时都能被选中（开发 Vue / 打包 static）；
2. 两个候选同时在时**前者（Vue）胜出**，把顺序调反即换成后者；
3. Vue 目录存在但**缺 index.html**（拷贝不完整）时**回落 static**，而不是返回空目录；
4. 目录都在但都没有 index.html → `None`（`app/main.py` 据此决定是否注册 SPA 回退路由）；
5. 真实元组里**不许再出现**已删除的 `frontend/dist`（2026-10-22 清理旧 React 后，
   它是一条指向空目录的死候选；有人手滑加回来就红）。

⚠️ 纪律：本文件**绝不触碰真实仓库目录**。全部布局由 `tmp_path` 现造，
只 patch 一个模块级常量 `app.core.config.STATIC_CANDIDATES`；`static_dir()`
在调用时读该全局，因此 patch 一定生效（若将来有人把它绑成默认参数，
这里会立刻红 —— 那正是要拦住的重构）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import config

#: 与 `config.STATIC_CANDIDATES` 一一对应的两个相对布局（顺序即优先级）。
_VUE_REL = Path("frontend-vue") / "dist"
_PACKED_REL = Path("static")

#: 2026-10-22 已删除的旧 React 产物路径（只用于「不许加回来」的断言）。
_REMOVED_REACT_REL = Path("frontend") / "dist"


def _make_dirs(tmp_path: Path, rels: tuple[Path, ...], *, with_index: bool = True) -> tuple[Path, ...]:
    """在 `tmp_path` 下按相对路径造目录（可选择是否放 index.html）。

    Args:
        tmp_path: pytest 提供的临时目录（每个用例独立）。
        rels: 要创建的相对路径，如 `frontend-vue/dist`。
        with_index: True 时每个目录写一个 `index.html`（模拟「产物完整」）。

    Returns:
        与 `rels` 顺序一致的绝对路径元组。
    """
    made: list[Path] = []
    for rel in rels:
        directory = tmp_path / rel
        directory.mkdir(parents=True, exist_ok=True)
        if with_index:
            # 内容包含目录名，失败时一眼看出到底选中了哪个候选
            (directory / "index.html").write_text(f"<!-- {rel.as_posix()} -->", encoding="utf-8")
        made.append(directory)
    return tuple(made)


def _patch_candidates(monkeypatch: pytest.MonkeyPatch, ordered: tuple[Path, ...]) -> None:
    """把 `STATIC_CANDIDATES` 换成给定的有序元组（用例结束自动还原）。"""
    monkeypatch.setattr(config, "STATIC_CANDIDATES", ordered)


def test_returns_vue_dir_when_only_vue_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """只有 Vue 产物 → 返回 Vue 目录（开发环境的常态）。"""
    (vue,) = _make_dirs(tmp_path, (_VUE_REL,))
    _patch_candidates(monkeypatch, (vue, tmp_path / _PACKED_REL))

    assert config.static_dir() == vue


def test_returns_packaged_static_when_only_static_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """打包环境（无 frontend-vue 源码，只有 static）→ 返回 static。"""
    (packed,) = _make_dirs(tmp_path, (_PACKED_REL,))
    _patch_candidates(monkeypatch, (tmp_path / _VUE_REL, packed))

    assert config.static_dir() == packed


def test_returns_none_when_no_candidate_has_index_html(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """两个目录都在但都没有 index.html → None（前端未构建）。

    `app/main.py` 用 `static_dir() is None` 决定是否降级为 JSON 提示路由，
    所以这里必须是 None，不能「返回第一个存在的目录」。
    """
    candidates = _make_dirs(tmp_path, (_VUE_REL, _PACKED_REL), with_index=False)
    for rel in (_VUE_REL, _PACKED_REL):
        assert not (tmp_path / rel / "index.html").exists()

    _patch_candidates(monkeypatch, candidates)

    assert config.static_dir() is None


def test_falls_back_to_static_when_vue_dir_has_no_index_html(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Vue 目录存在但**缺 index.html**（拷贝中断/构建失败）→ 必须回落 static。

    这是线上最危险的半成品状态：目录在、产物不全。若实现改成「看目录存在与否」，
    后端会 mount 一个空目录 → 首页 404 白屏，且切换/回滚都失效。
    """
    (tmp_path / _VUE_REL).mkdir(parents=True)          # 只有空目录，刻意不写 index.html
    (packed,) = _make_dirs(tmp_path, (_PACKED_REL,))

    _patch_candidates(monkeypatch, (tmp_path / _VUE_REL, packed))

    assert config.static_dir() == packed


def test_first_candidate_wins_when_both_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """两个候选同时存在 → **前者胜出**；把顺序调反则换成后者。

    这条同时锁两件事：
      ① 语义是「按序第一个命中者胜出」，而非「后者覆盖前者」；
      ② 交换顺序即可切换前端（后端零改动），行为可预测。
    """
    vue, packed = _make_dirs(tmp_path, (_VUE_REL, _PACKED_REL))

    _patch_candidates(monkeypatch, (vue, packed))
    assert config.static_dir() == vue, "两个候选都在时，元组首项必须胜出"

    # 顺序互换演练：立刻换成后者
    _patch_candidates(monkeypatch, (packed, vue))
    assert config.static_dir() == packed, "互换顺序后必须切到后者"


def test_real_candidates_are_vue_then_static_and_exclude_removed_react() -> None:
    """真实 `STATIC_CANDIDATES`：Vue → static，且**不含**已删除的 `frontend/dist`。

    前面几条用 patch 后的假元组验证**语义**；这条验证**仓库里真实的那份**没被人改坏
    —— 只比较 `Path` 对象，不依赖磁盘上产物是否存在，因此在「已构建 / 未构建」的
    任何机器上都稳定。
    """
    root = config.ROOT_DIR
    assert config.STATIC_CANDIDATES == (
        root / "frontend-vue" / "dist",   # 开发环境（唯一现役前端）
        root / "static",                  # 打包环境
    ), "STATIC_CANDIDATES 的顺序即前端切换点，改动前请先看计划 §9 回滚预案"

    assert (root / _REMOVED_REACT_REL) not in config.STATIC_CANDIDATES, (
        "旧 React 的 frontend/dist 已于 2026-10-22 从仓库删除；"
        "把它加回候选会得到一条永远指向空目录的死路径（真要用请先按 §9 从 tag 重建）"
    )
