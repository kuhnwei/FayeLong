"""P4-4 验收：写作批改异步化（池归属 / 缓存 / 降级 / 密钥 / 成本闸）。

**本文件绝不发真实网络请求**：外部服务一律用 fake provider 注入
（`set_provider_factory`），只有一条用例故意指向 `127.0.0.1:1` 的**已关闭端口**
来验证「连不上 → 降级」，那是一次立刻 ECONNREFUSED 的本地连接，不是外网调用。
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from app.core.config import settings
from app.db import Base, SessionLocal, engine
from app.models import (
    Job,
    Paper,
    PracticeSession,
    Question,
    Response,
    Section,
    Setting,
    WritingGradeCache,
)
from app.services import jobs as jobs_service
from app.services.grading import (
    ProviderError,
    ProviderGrade,
    ProviderUnavailable,
    grade_and_cache,
    mask_secret,
    reset_provider_factory,
    resolve_provider,
    set_provider_factory,
)
from app.services.grading.provider import OpenAICompatProvider
from app.services.question_types import get as get_question_type
from app.services.question_types.writing import AsyncGradeRequired
from app.worker import HANDLERS, Worker, _PoolRunner

ESSAY = "Some people believe that technology makes our lives better. I partly agree."


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _schema() -> None:
    """确保临时库里有表。

    Notes:
        本模块**不**用 `client`（不需要 HTTP），因此不会触发 lifespan 的
        `init_db()`；与 `test_jobs.py` / `test_worker_pools.py` 同一招显式建表。
    """
    Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean() -> Any:
    """清空 IELTS / 批改相关行（共享 session 级临时库，必须自己收尾）。"""
    _purge()
    reset_provider_factory()
    yield
    reset_provider_factory()
    _purge()


def _purge() -> None:
    db = SessionLocal()
    try:
        db.query(Response).delete()
        db.query(PracticeSession).delete()
        db.query(Question).delete()
        db.query(Section).delete()
        db.query(Paper).delete()
        db.query(WritingGradeCache).delete()
        db.query(Job).filter(Job.kind == jobs_service.KIND_GRADE_WRITING).delete()
        db.query(Setting).filter(Setting.key.like("grading.usage.%")).delete()
        db.commit()
    finally:
        db.close()


class FakeProvider:
    """可计数的假 provider（`calls` 是「外部服务被调用了几次」的唯一证据）。"""

    name = "fake"

    def __init__(
        self,
        *,
        score: float = 6.5,
        feedback: str = "结构清晰，论证略单薄。",
        tokens: int = 321,
        error: Exception | None = None,
    ) -> None:
        self.calls = 0
        self.prompts: list[str] = []
        self.score = score
        self.feedback = feedback
        self.tokens = tokens
        self.error = error

    def grade(self, *, prompt: str, max_tokens: int) -> ProviderGrade:
        self.calls += 1
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return ProviderGrade(
            score=self.score,
            max_score=0.0,
            feedback=self.feedback,
            tokens=self.tokens,
            model="fake-1",
        )


@pytest.fixture()
def fake_provider() -> FakeProvider:
    """注入一个会数调用次数的假 provider。"""
    provider = FakeProvider()
    set_provider_factory(lambda: provider)
    return provider


def seed_writing(
    *,
    essay: str = ESSAY,
    answer: dict[str, Any] | None = None,
    status: str = "in_progress",
) -> dict[str, int]:
    """造「一张卷 + 一个写作题 + 一个会话 + 一条作答」，返回各 id。"""
    db = SessionLocal()
    try:
        paper = Paper(title="写作卷", mode="section_drill", source="自建", tags=[])
        db.add(paper)
        db.flush()
        section = Section(paper_id=paper.id, kind="writing", ordinal=0, time_limit_sec=3600)
        db.add(section)
        db.flush()
        question = Question(
            section_id=section.id,
            ordinal=0,
            type="writing",
            stem="Discuss both views.",
            options=[],
            answer=answer
            if answer is not None
            else {
                "prompt": "Discuss both views.",
                "reference_answer": "参考范文：……",
                "criteria": [{"name": "任务完成度", "max": 3}, {"name": "连贯与衔接", "max": 3}],
                "self_checklist": ["是否回应双方观点？"],
                "min_words": 250,
            },
        )
        db.add(question)
        db.flush()
        session = PracticeSession(paper_id=paper.id, status=status, time_spent_sec=0)
        db.add(session)
        db.flush()
        response = Response(
            session_id=session.id, question_id=question.id, user_answer={"text": essay}, detail={}
        )
        db.add(response)
        db.commit()
        return {
            "paper": int(paper.id),
            "section": int(section.id),
            "question": int(question.id),
            "session": int(session.id),
            "response": int(response.id),
        }
    finally:
        db.close()


def _response_row(response_id: int) -> Response:
    db = SessionLocal()
    try:
        row = db.get(Response, int(response_id))
        assert row is not None
        db.expunge(row)
        return row
    finally:
        db.close()


def _session_status(session_id: int) -> str:
    db = SessionLocal()
    try:
        session = db.get(PracticeSession, int(session_id))
        assert session is not None
        return session.status
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 1) 池归属：CPU 池绝不认领 grade_writing
# ---------------------------------------------------------------------------


class TestPoolOwnership:
    def test_routing_constants(self) -> None:
        """`grade_writing` 必须落在 IO 池的**认领集合**里，且不在 CPU 池的集合里。

        Notes:
            仓库里没有 `GRADE_KINDS` 常量（QA 已纠正过这个前提）；实际口径是
            `KIND_POOL` 映射 + `kinds_of_pool()`。CPU 池靠 `exclude_kinds`
            表达「CPU + 所有未登记 kind」，因此它排除的正是 IO 池那几个。
        """
        assert jobs_service.pool_of(jobs_service.KIND_GRADE_WRITING) == jobs_service.POOL_IO
        assert jobs_service.KIND_GRADE_WRITING in jobs_service.kinds_of_pool(jobs_service.POOL_IO)
        assert jobs_service.KIND_GRADE_WRITING not in jobs_service.kinds_of_pool(jobs_service.POOL_CPU)
        assert jobs_service.KIND_GRADE_WRITING in HANDLERS, "handler 必须已登记（P4-4）"

    def test_runner_filters(self) -> None:
        """两个池 runner 的认领口径与上面的常量一致（逐项核对）。"""
        worker = Worker(cpu_threads=1, io_threads=1, mode="external", recover=False)
        cpu = _PoolRunner(worker, jobs_service.POOL_CPU, 1)
        io = _PoolRunner(worker, jobs_service.POOL_IO, 1)
        try:
            assert cpu.kinds is None, "CPU 池用「排除」表达，不是白名单"
            assert jobs_service.KIND_GRADE_WRITING in cpu.exclude_kinds
            assert io.kinds is not None
            assert jobs_service.KIND_GRADE_WRITING in io.kinds
        finally:
            cpu.executor.shutdown(wait=False)
            io.executor.shutdown(wait=False)

    def test_cpu_only_worker_never_claims_it(self) -> None:
        """**行为证据**：只启 CPU 池的 worker 跑完就退出，`grade_writing` 仍是 pending。"""
        ids = seed_writing()
        jobs_service.enqueue(jobs_service.KIND_GRADE_WRITING, ids["response"])

        worker = Worker(
            cpu_threads=1, io_threads=1, mode="external", recover=False,
            pools=(jobs_service.POOL_CPU,),
        )
        try:
            worker.start()
            assert worker.wait_idle(timeout=5.0)
        finally:
            worker.stop()

        row = _response_row(ids["response"])
        assert row.graded_at is None, "CPU 池不该判写作"
        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.kind == jobs_service.KIND_GRADE_WRITING).one()
        finally:
            db.close()
        assert job.status == "pending", "任务必须原封不动留在队列里"

    def test_io_worker_grades_and_finishes(self, fake_provider: FakeProvider) -> None:
        """**行为证据**：只启 IO 池的 worker 会真的判完并把 job 置 done。"""
        fake_provider.score = 5.0   # 满分 6.0（criteria 3+3）范围内
        ids = seed_writing()
        jobs_service.enqueue(jobs_service.KIND_GRADE_WRITING, ids["response"])

        worker = Worker(
            cpu_threads=1, io_threads=1, mode="external", recover=False,
            pools=(jobs_service.POOL_IO,),
        )
        try:
            worker.start()
            assert worker.wait_idle(timeout=15.0)
        finally:
            worker.stop()

        row = _response_row(ids["response"])
        assert row.graded_at is not None
        assert row.score == pytest.approx(5.0)
        assert row.max_score == pytest.approx(6.0)   # criteria 求和 = 3+3
        assert row.detail["tokens"] == fake_provider.tokens
        assert row.detail["mode"] == "graded"
        assert row.detail["provider"] == "fake"
        assert _session_status(ids["session"]) == "graded"
        assert fake_provider.calls == 1

        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.kind == jobs_service.KIND_GRADE_WRITING).one()
        finally:
            db.close()
        assert job.status == "done"


# ---------------------------------------------------------------------------
# 2) 题型契约：async 不许同步判
# ---------------------------------------------------------------------------


class TestWritingType:
    def test_sync_grade_is_rejected(self) -> None:
        qtype = get_question_type("writing")
        assert qtype is not None
        assert qtype.grade_mode == "async"
        with pytest.raises(AsyncGradeRequired):
            qtype.grade({"reference_answer": "x"}, {"text": "y"})

    def test_max_score_prefers_explicit_then_criteria(self) -> None:
        qtype = get_question_type("writing")
        assert qtype is not None
        assert qtype.max_score({"max_score": 9}) == 9.0
        assert qtype.max_score({"criteria": [{"name": "a", "max": 4}, {"name": "b", "max": 5}]}) == 9.0
        assert qtype.max_score({}) == 9.0

    def test_provider_score_is_clamped(self) -> None:
        """provider 给出越界分数（12 / -1）时必须夹到 `[0, max_score]`。"""
        from app.services.question_types.writing import _clamp  # noqa: PLC0415 - 私有纯函数

        assert _clamp(12.0, 6.0) == 6.0
        assert _clamp(-1.0, 6.0) == 0.0
        assert _clamp(4.5, 6.0) == 4.5

    def test_validate_rejects_empty_rubric(self) -> None:
        qtype = get_question_type("writing")
        assert qtype is not None
        with pytest.raises(ValueError, match="reference_answer"):
            qtype.validate({})


# ---------------------------------------------------------------------------
# 3) 缓存：同内容第二次不再调用外部服务
# ---------------------------------------------------------------------------


class TestCache:
    def test_second_identical_submission_hits_cache(self, fake_provider: FakeProvider) -> None:
        ids = seed_writing()
        qtype = get_question_type("writing")
        answer = _answer_of(ids["question"])

        db = SessionLocal()
        try:
            first = grade_and_cache(
                db, question_id=ids["question"], qtype=qtype,
                answer=answer, response={"text": ESSAY},
            )
            db.commit()
        finally:
            db.close()
        assert first.cached is False
        assert first.provider_calls == 1
        assert fake_provider.calls == 1

        db = SessionLocal()
        try:
            # 首尾空白不同也必须命中（归一化之后才做 key）
            second = grade_and_cache(
                db, question_id=ids["question"], qtype=qtype,
                answer=answer, response={"text": f"  {ESSAY}\n"},
            )
            db.commit()
        finally:
            db.close()

        assert second.cached is True, "同内容第二次必须命中缓存"
        assert second.provider_calls == 0
        assert fake_provider.calls == 1, f"provider 被调用了 {fake_provider.calls} 次"
        assert second.result.score == first.result.score

        db = SessionLocal()
        try:
            assert db.query(WritingGradeCache).count() == 1
        finally:
            db.close()

    def test_degraded_result_is_not_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """降级结果**绝不入缓存**（否则「临时关掉 provider」会被固化成永久结论）。"""
        ids = seed_writing()
        qtype = get_question_type("writing")
        answer = _answer_of(ids["question"])
        set_provider_factory(lambda: FakeProvider(error=ProviderError("boom")))

        db = SessionLocal()
        try:
            outcome = grade_and_cache(
                db, question_id=ids["question"], qtype=qtype,
                answer=answer, response={"text": ESSAY},
            )
            db.commit()
        finally:
            db.close()

        assert outcome.result.detail["mode"] == "degraded"
        db = SessionLocal()
        try:
            assert db.query(WritingGradeCache).count() == 0, "降级结果不该写缓存"
        finally:
            db.close()


def _answer_of(question_id: int) -> dict[str, Any]:
    db = SessionLocal()
    try:
        question = db.get(Question, int(question_id))
        assert question is not None
        return dict(question.answer)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 4) 降级：默认关闭也能交卷
# ---------------------------------------------------------------------------


class TestDegradedFallback:
    def test_default_provider_is_off(self) -> None:
        """产品红线：默认**零付费**（`FAYELONG_GRADING_PROVIDER=off`）。"""
        assert str(settings.grading_provider).strip().lower() == "off"

    def test_off_yields_reference_answer_pack(self) -> None:
        ids = seed_writing()
        qtype = get_question_type("writing")
        answer = _answer_of(ids["question"])

        db = SessionLocal()
        try:
            outcome = grade_and_cache(
                db, question_id=ids["question"], qtype=qtype,
                answer=answer, response={"text": ESSAY},
            )
            db.commit()
        finally:
            db.close()

        detail = outcome.result.detail
        assert detail["mode"] == "degraded"
        assert detail["reason"] == "provider_off"
        assert detail["reference_answer"] == "参考范文：……"
        assert [item["name"] for item in detail["criteria"]] == ["任务完成度", "连贯与衔接"]
        assert detail["self_checklist"] == ["是否回应双方观点？"]
        assert detail["word_count"] == len(ESSAY.split())
        assert detail["min_words"] == 250
        # 降级**不是**失败：分数记 0，但没有异常
        assert outcome.result.score == 0.0
        assert outcome.provider_calls == 0

    def test_network_failure_degrades_instead_of_raising(self) -> None:
        """外部服务连不上 → 降级（不是 500、不是 failed）。"""
        ids = seed_writing()
        qtype = get_question_type("writing")
        answer = _answer_of(ids["question"])
        set_provider_factory(
            lambda: FakeProvider(error=ProviderError("network_error:connection refused"))
        )

        db = SessionLocal()
        try:
            outcome = grade_and_cache(
                db, question_id=ids["question"], qtype=qtype,
                answer=answer, response={"text": ESSAY},
            )
            db.commit()
        finally:
            db.close()

        assert outcome.result.detail["mode"] == "degraded"
        assert "network_error" in outcome.result.detail["reason"]
        assert outcome.result.detail["provider_called"] is True

    def test_worker_marks_session_degraded_not_failed(self) -> None:
        """端到端：默认 off 时 worker 判完，session 是 `degraded` 而**不是** `failed`。"""
        ids = seed_writing()
        jobs_service.enqueue(jobs_service.KIND_GRADE_WRITING, ids["response"])

        worker = Worker(
            cpu_threads=1, io_threads=1, mode="external", recover=False,
            pools=(jobs_service.POOL_IO,),
        )
        try:
            worker.start()
            assert worker.wait_idle(timeout=15.0)
        finally:
            worker.stop()

        row = _response_row(ids["response"])
        assert row.graded_at is not None, "降级也要落 graded_at（判分动作完成了）"
        assert row.detail["mode"] == "degraded"
        assert _session_status(ids["session"]) == "degraded"

        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.kind == jobs_service.KIND_GRADE_WRITING).one()
        finally:
            db.close()
        assert job.status == "done", "降级是成功路径，job 必须 done"


# ---------------------------------------------------------------------------
# 5) 成本闸
# ---------------------------------------------------------------------------


class TestDailyLimit:
    def test_limit_blocks_second_call(self, fake_provider: FakeProvider,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "grading_daily_max", 1)
        first_ids = seed_writing(essay="第一篇作文。")
        second_ids = seed_writing(essay="第二篇作文，内容不同。")
        qtype = get_question_type("writing")

        db = SessionLocal()
        try:
            first = grade_and_cache(
                db, question_id=first_ids["question"], qtype=qtype,
                answer=_answer_of(first_ids["question"]), response={"text": "第一篇作文。"},
            )
            db.commit()
        finally:
            db.close()
        assert first.result.detail["mode"] == "graded"
        assert fake_provider.calls == 1

        db = SessionLocal()
        try:
            second = grade_and_cache(
                db, question_id=second_ids["question"], qtype=qtype,
                answer=_answer_of(second_ids["question"]),
                response={"text": "第二篇作文，内容不同。"},
            )
            db.commit()
        finally:
            db.close()

        assert second.result.detail["mode"] == "degraded"
        assert second.result.detail["reason"] == "daily_limit"
        assert fake_provider.calls == 1, "超配额后绝不能再调外部服务"

    def test_usage_is_recorded(self, fake_provider: FakeProvider) -> None:
        ids = seed_writing()
        qtype = get_question_type("writing")
        db = SessionLocal()
        try:
            grade_and_cache(
                db, question_id=ids["question"], qtype=qtype,
                answer=_answer_of(ids["question"]), response={"text": ESSAY},
            )
            db.commit()
        finally:
            db.close()

        from app.services.grading import budget

        db = SessionLocal()
        try:
            usage = budget.read_usage(db)
        finally:
            db.close()
        assert usage["calls"] == 1
        assert usage["tokens"] == fake_provider.tokens


# ---------------------------------------------------------------------------
# 6) 密钥：只走环境变量，日志/异常/数据库里都不许出现原文
# ---------------------------------------------------------------------------


class TestSecretHandling:
    def test_mask_secret(self) -> None:
        assert mask_secret("") == ""
        assert mask_secret("short") == "***"
        assert mask_secret("sk-abcdefgh1234") == "sk-***1234"
        # 原文的中间部分绝不出现
        assert "abcdefgh" not in mask_secret("sk-abcdefgh1234")

    def test_openai_compat_requires_key(self) -> None:
        with pytest.raises(ProviderUnavailable, match="missing_api_key"):
            OpenAICompatProvider(base_url="http://127.0.0.1:1/v1", api_key="", model="m")

    def test_network_error_does_not_leak_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """连不上时：异常消息与日志里都不能出现密钥原文，只出现打码形式。

        连的是 `127.0.0.1:1`（本机已关闭端口）→ 立刻 ECONNREFUSED，
        **不是**对外网的调用。

        Notes:
            不用 `caplog`：本项目的日志可能被 `setup_logging()` 改成不向 root
            传播，`caplog.text` 会空着 —— 那样「密钥没泄漏」这条断言会**恒真**。
            这里自己给目标 logger 挂一个 handler，保证真的看到了日志记录。
        """
        secret = "sk-live-DO-NOT-LEAK-abcdef123456"
        monkeypatch.setattr(settings, "grading_provider", "openai_compat")
        monkeypatch.setattr(settings, "grading_api_key", secret)
        monkeypatch.setattr(settings, "grading_base_url", "http://127.0.0.1:1/v1")
        monkeypatch.setattr(settings, "grading_timeout_sec", 2.0)

        captured: list[str] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record.getMessage())

        target_logger = logging.getLogger("app.services.grading.provider")
        handler = _Capture()
        previous_level = target_logger.level
        target_logger.addHandler(handler)
        target_logger.setLevel(logging.DEBUG)
        try:
            provider = resolve_provider()
            assert isinstance(provider, OpenAICompatProvider)
            with pytest.raises(ProviderError) as excinfo:
                provider.grade(prompt="hi", max_tokens=16)
        finally:
            target_logger.removeHandler(handler)
            target_logger.setLevel(previous_level)

        text = "\n".join(captured)
        assert text, "没有捕获到任何日志 —— 这条用例会变成恒真，必须修好"
        assert secret not in str(excinfo.value), "异常消息泄漏了密钥"
        assert secret not in text, "日志泄漏了密钥"
        # 日志里应当有打码形式（证明「记了，但记的是安全形式」）
        assert mask_secret(secret) in text


# ---------------------------------------------------------------------------
# 7) job 幂等
# ---------------------------------------------------------------------------


    def test_api_key_never_reaches_database(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """密钥只存在于内存/环境变量：缓存载荷、`settings` 表里都不能出现原文。

        做法：配一个真密钥、用 fake provider 真跑一次判分（会写缓存 + 用量计数），
        然后把「可能藏密钥的两张表」整段导出来做子串断言。
        """
        secret = "sk-test-DO-NOT-PERSIST-7788"
        monkeypatch.setattr(settings, "grading_api_key", secret)
        set_provider_factory(lambda: FakeProvider())

        ids = seed_writing()
        qtype = get_question_type("writing")
        db = SessionLocal()
        try:
            grade_and_cache(
                db, question_id=ids["question"], qtype=qtype,
                answer=_answer_of(ids["question"]), response={"text": ESSAY},
            )
            db.commit()
        finally:
            db.close()

        dumped = _dump_db_text()
        assert dumped, "缓存/用量两处都没内容 —— 这条断言会恒真，必须修好"
        assert secret not in dumped, "密钥被写进了数据库"


class TestJobIdempotency:
    def test_already_graded_response_is_skipped(self, fake_provider: FakeProvider) -> None:
        """重复入队/重试不会二次计费：已判分的作答直接跳过。"""
        ids = seed_writing()
        jobs_service.enqueue(jobs_service.KIND_GRADE_WRITING, ids["response"])

        worker = Worker(
            cpu_threads=1, io_threads=1, mode="external", recover=False,
            pools=(jobs_service.POOL_IO,),
        )
        try:
            worker.start()
            assert worker.wait_idle(timeout=15.0)
        finally:
            worker.stop()
        assert fake_provider.calls == 1

        # 手工再入队一次（模拟重试），worker 再跑一遍
        db = SessionLocal()
        try:
            db.query(Job).filter(Job.kind == jobs_service.KIND_GRADE_WRITING).delete()
            db.commit()
        finally:
            db.close()
        jobs_service.enqueue(jobs_service.KIND_GRADE_WRITING, ids["response"])

        worker = Worker(
            cpu_threads=1, io_threads=1, mode="external", recover=False,
            pools=(jobs_service.POOL_IO,),
        )
        try:
            worker.start()
            assert worker.wait_idle(timeout=15.0)
        finally:
            worker.stop()

        assert fake_provider.calls == 1, "已判分的作答不该再调用外部服务"
        assert _response_row(ids["response"]).detail["mode"] == "graded"


class TestBadQuestionData:
    def test_bad_rubric_converges_to_ungraded(self) -> None:
        """题目连范文/评分标准都没有 → 该题记 `ungraded`，会话收敛到 `degraded`。

        为什么重要：若让 job 失败，它会重试 3 次再 failed，而会话会**永远**停在
        `grading`（前端永远轮询）。这里断言「坏数据也能收敛」。
        """
        ids = seed_writing(answer={})
        jobs_service.enqueue(jobs_service.KIND_GRADE_WRITING, ids["response"])

        worker = Worker(
            cpu_threads=1, io_threads=1, mode="external", recover=False,
            pools=(jobs_service.POOL_IO,),
        )
        try:
            worker.start()
            assert worker.wait_idle(timeout=15.0)
        finally:
            worker.stop()

        row = _response_row(ids["response"])
        assert row.graded_at is not None, "必须落 graded_at，否则会话永远 grading"
        assert row.detail["mode"] == "ungraded"
        assert "reference_answer" in row.detail["reason"]
        assert _session_status(ids["session"]) == "degraded"

        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.kind == jobs_service.KIND_GRADE_WRITING).one()
        finally:
            db.close()
        assert job.status == "done", "坏数据不该把 job 拖成 failed"


def _dump_db_text() -> str:
    """把「可能藏密钥」的表全导成文本（用于断言原文不存在）。"""
    db = SessionLocal()
    try:
        chunks = [json.dumps(row.payload, ensure_ascii=False) for row in db.query(WritingGradeCache)]
        chunks += [f"{row.key}={row.value}" for row in db.query(Setting)]
        return "\n".join(chunks)
    finally:
        db.close()
