"""P4-1 题型契约与注册表的单元验收。

为什么这些断言值得存在（不是「覆盖率凑数」）
============================================
1. **`dictation` 包装必须与原实现逐字段一致**：`services/dictation.py` 是 P0-5
   的安全网，题型化只是「换个入口」，一旦包装层多做了一次 strip / lower / 标点
   处理，同一个作答经 HTTP 与经题型会得到不同分数 —— 这类 bug 只在灰度时炸。
   因此这里直接拿 `evaluate()` 的返回值与 `GradeResult.detail` 做**逐字段相等**断言。
2. **注册表的两个静默失败面**：① 同一 code 被两个模块注册（谁后 import 谁赢）；
   ② 注册表为空时端点崩了。两者都不会在日常使用里出现，只会在「加题型」的那天出现。
3. **`echo` 不许默认出现在对外注册表里**：它只是 G4-① 的脚手架证据；一旦漏进
   生产清单，前端就会多出一个用户永远点不到的题型。
"""

from __future__ import annotations

import pytest

from app.db import SessionLocal
from app.services import auth as auth_service
from app.services import dictation as dictation_service
from app.services.question_types import (
    BaseQuestionType,
    GradeResult,
    all_types,
    clear,
    describe,
    get,
    register,
    registered_codes,
    unregister,
)
from app.services.question_types import dictation as dictation_type_module
from app.services.question_types import writing as writing_type_module
from app.services.question_types.dictation import DictationQuestionType
from app.services.question_types.echo import EchoQuestionType, register_echo

#: 期望的对外清单（`GET /api/question-types` 的 body）。
EXPECTED_DICTATION = {
    "code": "dictation",
    "label": "听写",
    "grade_mode": "sync",
    "requires_external": False,
}
#: P4-4 起注册的第二个生产题型（默认 `grading_provider=off` 时判分走降级包）。
EXPECTED_WRITING = {
    "code": "writing",
    "label": "写作",
    "grade_mode": "async",
    "requires_external": True,
}


@pytest.fixture(autouse=True)
def _registry_restored() -> None:
    """每个用例结束后注册表必须回到「只有生产题型」的状态。

    Notes:
        这是「别污染对外注册表」的可执行版本：用例里注册/注销占位题型之后，
        这里会复核 `code` 集合是否复原。比起人工 review，它能在 CI 里立刻抓到
        「某个用例忘了 unregister」。
    """
    before = registered_codes()
    yield
    after = registered_codes()
    assert after == before, f"用例污染了题型注册表：before={before} after={after}"


@pytest.fixture()
def authed_client(client):
    """带有效会话 cookie 的客户端（`GET /api/question-types` 受登录门禁保护）。"""
    db = SessionLocal()
    try:
        secret = auth_service.get_secret(db)
    finally:
        db.close()
    token = auth_service.issue_token(1, secret, 600)
    client.cookies.set(auth_service.COOKIE_NAME, token)
    try:
        yield client
    finally:
        client.cookies.clear()


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_production_types_registered_by_import_alone(self) -> None:
        """只 import 包就该拿到**完整**注册表 —— 这是「新增题型不改核心」的前提。

        ⚠️ P4-4 起注册表有 **2** 个生产题型（`writing` 是第一个 async 题型）。
        这条断言是**故意**写成精确元组的：注册表多/少一个题型都应当被人看见
        （多出来 = 有人加了题型却没说，少一个 = import 链断了）。
        """
        assert registered_codes() == ("dictation", "writing")
        qtype = get("dictation")
        assert qtype is not None
        assert isinstance(qtype, DictationQuestionType)
        assert qtype.grade_mode == "sync"
        assert qtype.requires_external is False

        writing = get("writing")
        assert writing is not None, "writing 题型必须随包 import 自动注册"
        assert writing.grade_mode == "async", "写作必须走异步判分（ADR-001 §7.1）"
        assert writing.requires_external is True

    def test_get_unknown_code_returns_none(self) -> None:
        assert get("reading_mcq") is None
        assert get("") is None

    def test_all_types_is_sorted_and_empty_safe(self) -> None:
        """注册表为空时 `all_types()` 返回空元组，绝不抛异常。"""
        clear()
        try:
            assert all_types() == ()
            assert registered_codes() == ()
            assert get("dictation") is None
        finally:
            # 复原全部生产题型（autouse fixture 会复核 code 集合是否一致）
            register(dictation_type_module.TYPE)
            register(writing_type_module.TYPE)

        codes = registered_codes()
        assert codes == tuple(sorted(codes))

    def test_duplicate_code_is_rejected(self) -> None:
        """同一 code 的第二个实现必须报错（防静默覆盖）。"""
        class DupA(BaseQuestionType):
            code = "dup_probe"
            label = "探针A"

            def grade(self, answer, response):  # noqa: ANN001, D102 - 测试替身
                return GradeResult(score=1, max_score=1, correct=True)

        class DupB(DupA):
            label = "探针B"

        assert register(DupA) is DupA
        try:
            with pytest.raises(ValueError, match="已被"):
                register(DupB)
        finally:
            assert unregister("dup_probe") is True
        assert unregister("dup_probe") is False   # 幂等：第二次什么也没删

    def test_same_object_reregistration_is_idempotent(self) -> None:
        """同一对象重复注册不报错（模块被重复 import 的场景）。"""
        class Probe(BaseQuestionType):
            code = "idempotent_probe"
            label = "幂等探针"

            def grade(self, answer, response):  # noqa: ANN001, D102 - 测试替身
                return GradeResult(score=1, max_score=1, correct=True)

        instance = Probe()
        register(instance)
        register(instance)   # 第二次是同一对象 → 静默忽略
        try:
            assert get("idempotent_probe") is instance
        finally:
            unregister("idempotent_probe")

    def test_register_works_as_decorator(self) -> None:
        @register
        class Decorated(BaseQuestionType):
            code = "decorated_probe"
            label = "装饰器探针"

            def grade(self, answer, response):  # noqa: ANN001, D102 - 测试替身
                return GradeResult(score=0, max_score=1, correct=False)

        try:
            assert get("decorated_probe") is not None
            assert get("decorated_probe").label == "装饰器探针"
        finally:
            unregister("decorated_probe")
        # 装饰器语义：返回的必须是原类（不是实例），否则 `@register` 会毁掉类型
        assert isinstance(Decorated, type)

    def test_missing_required_method_raises_type_error(self) -> None:
        class NoGrade:
            code = "no_grade_probe"
            grade_mode = "sync"
            label = "缺方法"

            def validate(self, payload):  # noqa: ANN001, D102 - 测试替身
                return None

            def normalize(self, response):  # noqa: ANN001, D102 - 测试替身
                return dict(response)

            # 刻意不实现 grade / grade_async

        with pytest.raises(TypeError, match="grade"):
            register(NoGrade)

    def test_illegal_grade_mode_raises_value_error(self) -> None:
        class BadMode(BaseQuestionType):
            code = "bad_mode_probe"
            label = "错模式"
            grade_mode = "Sync"   # 大小写笔误

            def grade(self, answer, response):  # noqa: ANN001, D102 - 测试替身
                return GradeResult(score=1, max_score=1, correct=True)

        with pytest.raises(ValueError, match="grade_mode"):
            register(BadMode)

    def test_empty_code_raises_value_error(self) -> None:
        class NoCode(BaseQuestionType):
            label = "没 code"

            def grade(self, answer, response):  # noqa: ANN001, D102 - 测试替身
                return GradeResult(score=1, max_score=1, correct=True)

        with pytest.raises(ValueError, match="code"):
            register(NoCode)

    def test_describe_falls_back_to_code_for_empty_label(self) -> None:
        class NoLabel(BaseQuestionType):
            code = "no_label_probe"

            def grade(self, answer, response):  # noqa: ANN001, D102 - 测试替身
                return GradeResult(score=1, max_score=1, correct=True)

        registered = register(NoLabel)
        try:
            assert describe(registered) == {
                "code": "no_label_probe",
                "label": "no_label_probe",   # label 空 → 用 code 兜底
                "grade_mode": "sync",
                "requires_external": False,
            }
        finally:
            unregister("no_label_probe")


# ---------------------------------------------------------------------------
# GradeResult
# ---------------------------------------------------------------------------


class TestGradeResult:
    def test_fields_are_normalized(self) -> None:
        result = GradeResult(score=3, max_score=4, correct=1, detail={"a": 1})
        assert isinstance(result.score, float) and result.score == 3.0
        assert isinstance(result.max_score, float) and result.max_score == 4.0
        assert result.correct is True
        assert result.ratio == 0.75
        assert result.as_dict() == {
            "score": 3.0, "max_score": 4.0, "correct": True, "detail": {"a": 1},
        }

    def test_detail_defaults_to_empty_dict(self) -> None:
        assert GradeResult(score=0, max_score=1, correct=False).detail == {}
        assert GradeResult(score=0, max_score=1, correct=False, detail=None).detail == {}

    def test_non_dict_detail_rejected(self) -> None:
        with pytest.raises(TypeError, match="detail"):
            GradeResult(score=0, max_score=1, correct=False, detail=["x"])

    def test_nan_score_rejected(self) -> None:
        """NaN / inf 无法落 JSON，必须在构造期就拒掉，不能等到写库时才炸。"""
        with pytest.raises(ValueError, match="有限数"):
            GradeResult(score=float("nan"), max_score=1, correct=False)
        with pytest.raises(ValueError, match="有限数"):
            GradeResult(score=1, max_score=float("inf"), correct=False)

    def test_zero_max_score_ratio_is_one(self) -> None:
        """空题（max_score=0）按「无错」记 1.0，不做除零。"""
        assert GradeResult(score=0, max_score=0, correct=True).ratio == 1.0

    def test_frozen(self) -> None:
        result = GradeResult(score=1, max_score=1, correct=True)
        with pytest.raises(Exception):
            result.score = 2  # type: ignore[misc]  # frozen dataclass 应拒绝赋值


# ---------------------------------------------------------------------------
# dictation 包装：必须与原纯函数逐字段一致
# ---------------------------------------------------------------------------

#: (标准答案, 用户作答) —— 覆盖全对 / 拼错 / 漏词 / 多写 / 大小写与标点 / 空作答。
DICTATION_CASES: tuple[tuple[str, str], ...] = (
    ("The quick brown fox jumps over the lazy dog.", "The quick brown fox jumps over the lazy dog."),
    ("I received a letter yesterday.", "I recieved a letter yesterday."),
    ("She has been working here for three years.", "She has been working here for years."),
    ("Don't worry about it.", "don't worry about it"),
    ("He said hello.", "He said hello. Goodbye."),
    ("Practice makes perfect.", ""),
)


class TestDictationType:
    @pytest.mark.parametrize(("expected", "actual"), DICTATION_CASES)
    def test_grade_matches_pure_function(self, expected: str, actual: str) -> None:
        """判分结果必须与 `services/dictation.evaluate()` **逐字段相等**。"""
        qtype = get("dictation")
        assert qtype is not None

        result = qtype.grade({"expected_text": expected}, {"text": actual})
        baseline = dictation_service.evaluate(expected, actual)

        assert result.detail == baseline, "包装层改变了 evaluate() 的返回值"
        assert result.score == float(baseline["correct"])
        assert result.max_score == float(baseline["total_words"])
        assert result.correct is baseline["is_correct"]

    def test_alias_keys_are_accepted(self) -> None:
        """`text_en` / `input` 是 sentences / attempts 表的列名，也要能直接用。"""
        qtype = get("dictation")
        assert qtype is not None
        by_alias = qtype.grade({"text_en": "Hello world."}, {"input": "hello world"})
        by_canonical = qtype.grade({"expected_text": "Hello world."}, {"text": "hello world"})
        assert by_alias == by_canonical

    def test_normalize_strips_but_keeps_case_and_punctuation(self) -> None:
        """归一化只做 strip：大小写/标点由 `settings.dictation_*` 在纯函数里决定。"""
        qtype = get("dictation")
        assert qtype is not None
        assert qtype.normalize({"text": "  The Fox.  "}) == {"text": "The Fox."}
        assert qtype.normalize({"input": "  mixed Case "}) == {"text": "mixed Case"}

    def test_validate_rejects_missing_expected_text(self) -> None:
        qtype = get("dictation")
        assert qtype is not None
        with pytest.raises(ValueError, match="expected_text"):
            qtype.validate({"expected_text": "   "})
        with pytest.raises(ValueError, match="expected_text"):
            qtype.validate({})
        with pytest.raises(TypeError):
            qtype.validate("not a dict")   # type: ignore[arg-type]

    def test_validate_rejects_non_string_expected_text(self) -> None:
        qtype = get("dictation")
        assert qtype is not None
        with pytest.raises(TypeError, match="字符串"):
            qtype.validate({"expected_text": 42})   # type: ignore[dict-item]

    def test_grade_without_expected_text_raises(self) -> None:
        qtype = get("dictation")
        assert qtype is not None
        with pytest.raises(ValueError, match="expected_text"):
            qtype.grade({}, {"text": "anything"})

    def test_grade_async_delegates_to_sync(self) -> None:
        """sync 题型的 `grade_async` 兜底为同步实现（调度层误用不会 500）。"""
        qtype = get("dictation")
        assert qtype is not None
        assert qtype.grade_async({"expected_text": "a b"}, {"text": "a b"}) == qtype.grade(
            {"expected_text": "a b"}, {"text": "a b"}
        )


# ---------------------------------------------------------------------------
# 端点：GET /api/question-types
# ---------------------------------------------------------------------------


class TestQuestionTypesEndpoint:
    def test_requires_login(self, client) -> None:
        """清单不含题目内容，但仍受全局登录门禁保护（与其它 34 个端点一致）。"""
        client.cookies.clear()
        resp = client.get("/api/question-types")
        assert resp.status_code == 401, resp.text

    def test_returns_registry(self, authed_client) -> None:
        resp = authed_client.get("/api/question-types")
        assert resp.status_code == 200, resp.text
        # P4-4 起清单是 dictation + writing（按 code 升序）
        assert resp.json() == {"types": [EXPECTED_DICTATION, EXPECTED_WRITING]}

    def test_empty_registry_returns_empty_list(self, authed_client) -> None:
        """注册表为空是合法状态：端点必须返回空数组，而不是 500。"""
        clear()
        try:
            resp = authed_client.get("/api/question-types")
            assert resp.status_code == 200, resp.text
            assert resp.json() == {"types": []}
        finally:
            register(dictation_type_module.TYPE)
            register(writing_type_module.TYPE)


# ---------------------------------------------------------------------------
# G4-① 预演：占位题型 echo
# ---------------------------------------------------------------------------


class TestEchoPlaceholder:
    def test_not_registered_by_default(self) -> None:
        """`echo` 模块可以 import，但**默认不进**对外注册表。"""
        assert isinstance(EchoQuestionType(), BaseQuestionType)   # 模块本身可用
        assert "echo" not in registered_codes()
        assert get("echo") is None

    def test_mounts_by_registering_only(self, authed_client) -> None:
        """注册之后端点立刻多出 echo —— 端点代码一行都没改。"""
        register_echo()
        try:
            body = authed_client.get("/api/question-types").json()
            codes = [item["code"] for item in body["types"]]
            assert codes == ["dictation", "echo", "writing"], codes
            echo_item = body["types"][1]
            assert echo_item == {
                "code": "echo",
                "label": "回显（演示）",
                "grade_mode": "sync",
                "requires_external": False,
            }

            # 判分：永远满分，回显原文
            qtype = get("echo")
            assert qtype is not None
            result = qtype.grade({}, {"text": "  hello  "})
            assert result.score == 1.0 and result.max_score == 1.0 and result.correct is True
            assert result.detail["echo"] == "hello"
        finally:
            assert unregister("echo") is True

        assert "echo" not in registered_codes()
