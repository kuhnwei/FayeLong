"""P4-3 端点验收：`/api/papers*` 与 `/api/sessions*`。

这些断言在守什么（每条都对应一个真实会踩的坑）
============================================
1. **`answer` 绝不下发**：用一段独一无二的「秘密答案串」，断言它**一个字都不出现**
   在整个响应体里；同时断言 report 阶段 `explanation` **确实出现** —— 否则「秘密不
   出现」可能只是因为那条路根本没实现。
2. **N+1**：`GET /api/papers` 的查询条数必须与试卷数量无关。用 SQLAlchemy 的
   `before_cursor_execute` 事件数语句，断言 `FROM papers` 恰好 1 条。
3. **upsert**：同一题暂存两次只能有 1 行（`uq_responses_session_question` 的语义），
   且第二次是覆盖。
4. **交卷幂等**：连交两次不重复判分、不重复入队。
5. **判分分流**：sync 题当场有分；async 题交卷后 `score is None` + 入队一条
   `grade_writing`，会话停在 `grading`（**绝不同步等外部批改**）。
6. **401**：六个端点全部受登录门禁保护。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import event

from app.db import SessionLocal, engine
from app.models import (
    Job,
    Paper,
    Passage,
    PracticeSession,
    Question,
    Response,
    Section,
    Setting,
    WritingGradeCache,
)
from app.services import jobs as jobs_service
from app.services import papers as papers_service

#: 独一无二的「秘密」串：出现在响应体里就说明答案泄漏了。
SECRET_ANSWER = "SECRET-ANSWER-DO-NOT-LEAK-7f3a"
SECRET_EXPLANATION = "SECRET-EXPLANATION-ONLY-IN-REPORT-91c2"
SECRET_REFERENCE = "SECRET-REFERENCE-ESSAY-5b8d"


@pytest.fixture(autouse=True)
def _clean_ielts() -> Any:
    """每个用例前后清空 IELTS 相关表（共享 session 级临时库，必须自己收尾）。"""
    _purge()
    yield
    _purge()


def _purge() -> None:
    """按「子 → 父」顺序删除，并清掉批改缓存 / 用量计数 / 批改任务行。"""
    db = SessionLocal()
    try:
        db.query(Response).delete()
        db.query(PracticeSession).delete()
        db.query(Question).delete()
        db.query(Passage).delete()
        db.query(Section).delete()
        db.query(Paper).delete()
        db.query(WritingGradeCache).delete()
        db.query(Job).filter(Job.kind == jobs_service.KIND_GRADE_WRITING).delete()
        db.query(Setting).filter(Setting.key.like("grading.usage.%")).delete()
        db.commit()
    finally:
        db.close()


def seed_paper(
    *,
    title: str = "C4 Test 1",
    with_writing: bool = True,
    with_passage: bool = True,
) -> dict[str, int]:
    """造一张结构完整的试卷（听力 2 题 + 阅读 1 题 + 可选写作 1 题）。

    Args:
        title: 卷名。
        with_writing: 是否加一道 `writing` 题（async）。
        with_passage: 阅读 section 是否带文章（题挂在文章下）。

    Returns:
        `{"paper", "listening", "reading", "writing", "dictation", "dictation2",
        "passage", "mcq", "writing_question"}` —— 缺的项不出现在返回值里。
    """
    db = SessionLocal()
    try:
        paper = Paper(title=title, mode="full_mock", source="Cambridge", tags=["听力", "阅读"])
        db.add(paper)
        db.flush()

        listening = Section(
            paper_id=paper.id, kind="listening", ordinal=0, time_limit_sec=1800,
            instructions="听录音答题", media_id=None,
        )
        db.add(listening)
        db.flush()

        dictation = Question(
            section_id=listening.id, ordinal=0, type="dictation",
            stem="写下你听到的句子", options=[],
            answer={"expected_text": "The quick brown fox."},
            explanation=SECRET_EXPLANATION, ref_sentence_id=None,
        )
        dictation2 = Question(
            section_id=listening.id, ordinal=1, type="dictation",
            stem="写下第二句", options=[],
            answer={"expected_text": SECRET_ANSWER},
            explanation="", ref_sentence_id=None,
        )
        db.add_all([dictation, dictation2])
        db.flush()

        reading = Section(
            paper_id=paper.id, kind="reading", ordinal=1, time_limit_sec=3600,
            instructions="Read and answer", media_id=None,
        )
        db.add(reading)
        db.flush()

        ids: dict[str, int] = {
            "paper": int(paper.id),
            "listening": int(listening.id),
            "reading": int(reading.id),
            "dictation": int(dictation.id),
            "dictation2": int(dictation2.id),
        }

        if with_passage:
            passage = Passage(
                section_id=reading.id, ordinal=0, title="Passage 1", body_md="# The fox"
            )
            db.add(passage)
            db.flush()
            ids["passage"] = int(passage.id)
            # 故意用一个**未注册**的题型：它同时验证「题型缺失 → 该题 ungraded，
            # 但交卷仍然成功」这条兜底（绝不因为一道题让整卷交不上）。
            mcq = Question(
                section_id=reading.id, passage_id=passage.id, ordinal=0, type="reading_mcq",
                stem="What is the colour of the fox?", options=["A brown", "B blue"],
                answer={"correct": "A"}, explanation=SECRET_EXPLANATION,
            )
            db.add(mcq)
            db.flush()
            ids["mcq"] = int(mcq.id)

        if with_writing:
            writing_section = Section(
                paper_id=paper.id, kind="writing", ordinal=2, time_limit_sec=3600,
                instructions="Write at least 250 words", media_id=None,
            )
            db.add(writing_section)
            db.flush()
            ids["writing"] = int(writing_section.id)
            writing_question = Question(
                section_id=writing_section.id, ordinal=0, type="writing",
                stem="Some people think ... Discuss both views.",
                options=[],
                answer={
                    "prompt": "Some people think ... Discuss both views.",
                    "reference_answer": SECRET_REFERENCE,
                    "criteria": [{"name": "任务完成度", "max": 3}, {"name": "连贯与衔接", "max": 3}],
                    "self_checklist": ["是否回应了双方观点？", "是否有明确的立场？"],
                    "min_words": 250,
                },
                explanation=SECRET_EXPLANATION,
            )
            db.add(writing_question)
            db.flush()
            ids["writing_question"] = int(writing_question.id)

        db.commit()
        return ids
    finally:
        db.close()


def _start(client, paper_id: int) -> dict[str, Any]:
    """开一次会话并返回响应体。"""
    resp = client.post(f"/api/papers/{paper_id}/sessions")
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# 登录门禁
# ---------------------------------------------------------------------------

PROTECTED = [
    ("GET", "/api/papers", None),
    ("GET", "/api/papers/1", None),
    ("POST", "/api/papers/1/sessions", None),
    ("PATCH", "/api/sessions/1/responses", {"responses": []}),
    ("POST", "/api/sessions/1/submit", None),
    ("GET", "/api/sessions/1/report", None),
]


class TestGuard:
    @pytest.mark.parametrize(("method", "path", "body"), PROTECTED)
    def test_requires_login(self, client, method: str, path: str, body: Any) -> None:
        """六个新端点全部受全局登录门禁保护（默认拒绝）。"""
        client.cookies.clear()
        resp = client.request(method, path, json=body)
        assert resp.status_code == 401, f"{method} {path} -> {resp.status_code}"
        assert resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/papers
# ---------------------------------------------------------------------------


class TestListPapers:
    def test_counts_and_tags(self, authed_client) -> None:
        first = seed_paper(title="卷A")
        seed_paper(title="卷B", with_writing=False, with_passage=False)

        resp = authed_client.get("/api/papers")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 2
        by_title = {item["title"]: item for item in body["items"]}
        assert by_title["卷A"]["section_count"] == 3        # listening/reading/writing
        assert by_title["卷A"]["question_count"] == 4        # 2 dictation + mcq + writing
        assert by_title["卷B"]["section_count"] == 2         # listening/reading
        # with_passage=False ⇒ 阅读那题（挂在文章下）根本没建 → 只有 2 个 dictation
        assert by_title["卷B"]["question_count"] == 2
        assert by_title["卷A"]["tags"] == ["听力", "阅读"]
        assert by_title["卷A"]["mode"] == "full_mock"
        # 列表项绝不带结构（否则「列表」会把整棵题库树拖下来）
        assert "sections" not in by_title["卷A"]
        assert first["paper"] > 0

    def test_query_count_is_constant(self, authed_client) -> None:
        """N+1 回归：报告条数必须与试卷数量无关（`FROM papers` 恰好 1 条）。

        判据：为同一个端点，在「1 张卷」与「4 张卷」两种数据规模下各数一次
        `FROM papers` / `FROM sections` / `FROM questions` 的语句数，必须都是 1。
        """
        counts: dict[int, dict[str, int]] = {}
        for total in (1, 4):
            _purge()
            for index in range(total):
                seed_paper(title=f"卷{index}")
            statements = _capture_selects(lambda: authed_client.get("/api/papers"))
            counts[total] = {
                table: sum(
                    1 for sql in statements if f"FROM {table}" in sql or f"JOIN {table}" in sql
                )
                for table in ("papers", "sections", "questions")
            }

        assert counts[1] == counts[4] == {"papers": 1, "sections": 1, "questions": 1}, counts


def _capture_selects(call: Any) -> list[str]:
    """执行 `call()`，返回期间引擎上执行的全部 SELECT 语句。"""
    statements: list[str] = []

    def _before(_conn, _cursor, statement, _params, _context, _many) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.split()))

    event.listen(engine, "before_cursor_execute", _before)
    try:
        call()
    finally:
        event.remove(engine, "before_cursor_execute", _before)
    return statements


# ---------------------------------------------------------------------------
# GET /api/papers/{id}
# ---------------------------------------------------------------------------


class TestPaperDetail:
    def test_structure_and_answer_never_leaks(self, authed_client) -> None:
        ids = seed_paper()
        resp = authed_client.get(f"/api/papers/{ids['paper']}")
        assert resp.status_code == 200, resp.text

        raw = resp.text
        # ① 秘密串一个字都不能出现在结构树里
        for secret in (SECRET_ANSWER, SECRET_REFERENCE, SECRET_EXPLANATION):
            assert secret not in raw, f"响应体泄漏了 {secret}"
        # ② 连字段名都不该有
        kind_by_section = {
            section["kind"]: section for section in resp.json()["sections"]
        }
        all_questions = []
        for section in kind_by_section.values():
            all_questions.extend(section["questions"])
            for passage in section["passages"]:
                all_questions.extend(passage["questions"])
        assert len(all_questions) == 4
        for question in all_questions:
            assert "answer" not in question, question
            assert "explanation" not in question, question

        # ③ 结构正确：阅读的题挂在文章下（每道题只出现一次）
        reading = kind_by_section["reading"]
        assert reading["questions"] == [], "passage 下的题不该同时出现在 section 上"
        assert [p["title"] for p in reading["passages"]] == ["Passage 1"]
        assert [q["type"] for q in reading["passages"][0]["questions"]] == ["reading_mcq"]

        writing = kind_by_section["writing"]
        assert writing["time_limit_sec"] == 3600
        assert [q["type"] for q in writing["questions"]] == ["writing"]

    def test_unknown_paper_is_404(self, authed_client) -> None:
        assert authed_client.get("/api/papers/999999").status_code == 404


# ---------------------------------------------------------------------------
# POST /api/papers/{id}/sessions
# ---------------------------------------------------------------------------


class TestCreateSession:
    def test_creates_in_progress_session(self, authed_client) -> None:
        ids = seed_paper()
        body = _start(authed_client, ids["paper"])
        assert body["status"] == "in_progress"
        assert body["paper_id"] == ids["paper"]
        assert body["answered"] == 0
        assert body["submitted_at"] is None
        assert body["responses"] == []

    def test_unknown_paper_is_404(self, authed_client) -> None:
        assert authed_client.post("/api/papers/999999/sessions").status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/sessions/{id}/responses
# ---------------------------------------------------------------------------


class TestPatchResponses:
    def test_upsert_is_idempotent_per_question(self, authed_client) -> None:
        ids = seed_paper()
        session = _start(authed_client, ids["paper"])
        path = f"/api/sessions/{session['id']}/responses"

        first = authed_client.patch(
            path,
            json={
                "responses": [
                    {"question_id": ids["dictation"], "answer": {"text": "wrong first try"}},
                    {"question_id": ids["writing_question"], "answer": {"text": "draft essay"}},
                ],
                "time_spent_sec": 42,
            },
        )
        assert first.status_code == 200, first.text
        assert first.json()["answered"] == 2
        assert first.json()["time_spent_sec"] == 42

        second = authed_client.patch(
            path,
            json={"responses": [{"question_id": ids["dictation"], "answer": {"text": "The quick brown fox."}}]},
        )
        assert second.status_code == 200, second.text
        body = second.json()
        # 覆盖而不是新增
        assert body["answered"] == 2
        by_question = {row["question_id"]: row for row in body["responses"]}
        assert by_question[ids["dictation"]]["user_answer"] == {"text": "The quick brown fox."}

        # PATCH 的响应里不能出现 detail（防「暂存即拿到判分明细」这条侧路）
        for row in body["responses"]:
            assert "detail" not in row, row

        db = SessionLocal()
        try:
            assert db.query(Response).filter(Response.session_id == session["id"]).count() == 2
        finally:
            db.close()

    def test_unknown_question_is_400(self, authed_client) -> None:
        ids = seed_paper()
        session = _start(authed_client, ids["paper"])
        resp = authed_client.patch(
            f"/api/sessions/{session['id']}/responses",
            json={"responses": [{"question_id": 999999, "answer": {"text": "x"}}]},
        )
        assert resp.status_code == 400, resp.text
        assert "999999" in resp.json()["detail"]

    def test_unknown_session_is_404(self, authed_client) -> None:
        resp = authed_client.patch(
            "/api/sessions/999999/responses", json={"responses": []}
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/sessions/{id}/submit
# ---------------------------------------------------------------------------


class TestSubmit:
    def test_empty_submission_is_409(self, authed_client) -> None:
        ids = seed_paper()
        session = _start(authed_client, ids["paper"])
        resp = authed_client.post(f"/api/sessions/{session['id']}/submit")
        assert resp.status_code == 409, resp.text

    def test_sync_graded_immediately_async_queued(self, authed_client) -> None:
        """sync 当场判分；async 只入队 —— 会话停在 `grading` 而不是阻塞等外部服务。"""
        ids = seed_paper()
        session = _start(authed_client, ids["paper"])
        authed_client.patch(
            f"/api/sessions/{session['id']}/responses",
            json={
                "responses": [
                    {"question_id": ids["dictation"], "answer": {"text": "The quick brown fox."}},
                    {"question_id": ids["dictation2"], "answer": {"text": "totally wrong"}},
                    {"question_id": ids["mcq"], "answer": {"text": "A"}},
                    {"question_id": ids["writing_question"], "answer": {"text": "My essay body."}},
                ]
            },
        )

        resp = authed_client.post(f"/api/sessions/{session['id']}/submit")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "grading", "有 async 题时交卷后必须是 grading"
        assert body["pending"] == 1
        # 2 个 dictation 当场判了（第 3 题是未注册题型 → ungraded，不算 graded）
        assert body["graded"] == 2
        assert body["total_score"] == pytest.approx(4.0)   # 4 词全对 + 0 词

        by_question = {row["question_id"]: row for row in body["responses"]}
        assert by_question[ids["dictation"]]["score"] == 4.0
        assert by_question[ids["dictation2"]]["score"] == 0.0
        # ⚠️ 交卷响应里**没有** `detail`（判分明细只经 report 下发，见 schemas 注释）
        for row in body["responses"]:
            assert "detail" not in row, row
        # 未注册题型：不阻塞交卷，但「没被判」这件事必须看得出来
        assert by_question[ids["mcq"]]["graded_at"] is None
        # async 题：还没有分，且已入队
        assert by_question[ids["writing_question"]]["score"] is None
        assert by_question[ids["writing_question"]]["graded_at"] is None

        # 报表侧再确认一次分类（交卷后允许读）
        report = authed_client.get(f"/api/sessions/{session['id']}/report").json()
        items = {item["question_id"]: item for item in report["items"]}
        assert items[ids["mcq"]]["detail"]["mode"] == "ungraded"
        assert items[ids["mcq"]]["graded"] is False
        assert items[ids["writing_question"]]["graded"] is False

        response_id = by_question[ids["writing_question"]]["id"]
        db = SessionLocal()
        try:
            job = (
                db.query(Job)
                .filter(Job.kind == jobs_service.KIND_GRADE_WRITING, Job.ref_id == response_id)
                .one_or_none()
            )
        finally:
            db.close()
        assert job is not None and job.status == "pending"

    def test_submit_is_idempotent(self, authed_client) -> None:
        """连交两次：不重复判分（分数不变）、不重复入队（仍只有 1 条 job）。"""
        ids = seed_paper(with_writing=False)
        session = _start(authed_client, ids["paper"])
        authed_client.patch(
            f"/api/sessions/{session['id']}/responses",
            json={"responses": [{"question_id": ids["dictation"], "answer": {"text": "The quick brown fox."}}]},
        )
        first = authed_client.post(f"/api/sessions/{session['id']}/submit").json()
        # 只暂存了 1 条作答（dictation 全对）→ 全部判成功 → graded
        assert first["status"] == "graded", first
        second = authed_client.post(f"/api/sessions/{session['id']}/submit").json()
        assert second["status"] == first["status"]
        assert second["total_score"] == first["total_score"]
        assert second["submitted_at"] == first["submitted_at"]

        db = SessionLocal()
        try:
            assert (
                db.query(Job).filter(Job.kind == jobs_service.KIND_GRADE_WRITING).count() == 0
            ), "没有写作题时不该入队"
        finally:
            db.close()

    def test_patch_after_submit_is_409(self, authed_client) -> None:
        ids = seed_paper(with_writing=False)
        session = _start(authed_client, ids["paper"])
        authed_client.patch(
            f"/api/sessions/{session['id']}/responses",
            json={"responses": [{"question_id": ids["dictation"], "answer": {"text": "x"}}]},
        )
        authed_client.post(f"/api/sessions/{session['id']}/submit")
        resp = authed_client.patch(
            f"/api/sessions/{session['id']}/responses",
            json={"responses": [{"question_id": ids["dictation"], "answer": {"text": "y"}}]},
        )
        assert resp.status_code == 409, resp.text


# ---------------------------------------------------------------------------
# GET /api/sessions/{id}/report
# ---------------------------------------------------------------------------


class TestReport:
    def test_unsubmitted_report_is_409(self, authed_client) -> None:
        """**未交卷 → 409**：报告是交卷后的成绩单，未交卷不该存在。

        没有这道闸时：PATCH 几道作答 → 不交卷 → 直接 GET report 就能拿到
        `explanation`（QA 实测命中过 SECRET_EXPLANATION）。P5 的考试场景会把
        它放大成公平性问题。
        """
        ids = seed_paper()
        session = _start(authed_client, ids["paper"])
        authed_client.patch(
            f"/api/sessions/{session['id']}/responses",
            json={"responses": [{"question_id": ids["dictation"], "answer": {"text": "x"}}]},
        )

        resp = authed_client.get(f"/api/sessions/{session['id']}/report")
        assert resp.status_code == 409, resp.text
        assert "交卷" in resp.json()["detail"]
        # 关键：409 的响应体里不能捎带任何解析文本
        assert SECRET_EXPLANATION not in resp.text

    def test_gate_lives_in_domain_layer(self, db_session) -> None:
        """闸必须在**领域层**：直接调 `services.papers.report()` 也必须被拒。

        只在 API 层 `if` 的话，将来「导出 / SSE / 批处理」这些入口会绕过它 ——
        报告里带 `explanation`，那等于把答案送出去。这条用例绕开 HTTP 直接打领域
        函数，正是为了证明闸不在 HTTP 层。
        """
        ids = seed_paper()
        session = papers_service.create_session(db_session, ids["paper"])
        assert session.submitted_at is None

        with pytest.raises(papers_service.SessionNotSubmittedError):
            papers_service.report(db_session, session)

    def test_report_allowed_while_grading(self, authed_client) -> None:
        """`grading`（写作还在 worker 里判）**允许**读：已交卷，`pending>0` 供轮询。"""
        ids = seed_paper()
        session = _start(authed_client, ids["paper"])
        authed_client.patch(
            f"/api/sessions/{session['id']}/responses",
            json={
                "responses": [
                    {"question_id": ids["dictation"], "answer": {"text": "The quick brown fox."}},
                    {"question_id": ids["writing_question"], "answer": {"text": "essay"}},
                ]
            },
        )
        authed_client.post(f"/api/sessions/{session['id']}/submit")

        resp = authed_client.get(f"/api/sessions/{session['id']}/report")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["session"]["status"] == "grading"
        assert body["pending"] == 1
        items = {item["question_id"]: item for item in body["items"]}
        # 写作还没判：分数为 NULL，detail 里也没有范文（那是 worker 判完才写入的）
        writing = items[ids["writing_question"]]
        assert writing["score"] is None and writing["max_score"] is None
        assert writing["graded"] is False
        assert writing["detail"] == {}
        # 已判完的题正常出分明细
        assert items[ids["dictation"]]["score"] == 4.0
        assert items[ids["dictation"]]["detail"]["accuracy"] == 100.0

    def test_report_shows_pending_then_explanation(self, authed_client) -> None:
        ids = seed_paper()
        session = _start(authed_client, ids["paper"])
        path = f"/api/sessions/{session['id']}"
        authed_client.patch(
            f"{path}/responses",
            json={
                "responses": [
                    {"question_id": ids["dictation"], "answer": {"text": "The quick brown fox."}},
                    {"question_id": ids["writing_question"], "answer": {"text": "essay"}},
                ]
            },
        )
        authed_client.post(f"{path}/submit")

        resp = authed_client.get(f"{path}/report")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["pending"] == 1
        assert body["session"]["status"] == "grading"
        items = {item["question_id"]: item for item in body["items"]}
        assert items[ids["dictation"]]["graded"] is True
        assert items[ids["writing_question"]]["graded"] is False
        assert items[ids["writing_question"]]["score"] is None
        # 交卷后**可以**看到解析（学习用途），且不是从结构树泄漏的
        assert items[ids["dictation"]]["explanation"] == SECRET_EXPLANATION

    def test_unknown_session_is_404(self, authed_client) -> None:
        assert authed_client.get("/api/sessions/999999/report").status_code == 404
