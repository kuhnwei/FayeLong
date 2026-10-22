"""API 层测试 · 媒体状态机与登录守卫（P0-6 之一）。

覆盖：
- **默认拒绝的守卫**（`main.py::guard_api`）：未登录访问任意 `/api/*` → 401；
  `/api/auth/*` 与 `/api/health` 豁免；**前端静态资源不拦**（非 401）；
- **状态机**：`pending→transcoding→ready→asr→translating→clipping→done | failed`
  的合法流转（经 `services/media._set_stage` / `_mark_failed` 落库）；
- **`requeue_unfinished()` 自愈**：仅「未完成」状态被重置为 `pending`，
  `done`/`failed` 不受影响，且被重置者会重新入队。
"""

from __future__ import annotations

import pytest

from app.core import config as cfg
from app.models import Media
from app.services import media as media_service

#: 需要登录的受保护接口样本（含一个不存在的路径，验证「默认拒绝」）。
PROTECTED_GETS = [
    "/api/media",
    "/api/media/1",
    "/api/vocab",
    "/api/stats",
    "/api/categories",
    "/api/notes",
    "/api/nonexistent-endpoint",
]


@pytest.fixture(autouse=True)
def _clear_media_table(app_client):
    """每个用例前清空 media 表 + 清 cookie，保证守卫/状态机用例彼此隔离。

    级联：`media` 删除会经 SQLite `ON DELETE CASCADE` 带走 `sentences` / `attempts`。
    仅作用于本次会话的**临时库**。
    """
    from app.db import SessionLocal

    app_client.cookies.clear()
    db = SessionLocal()
    try:
        db.query(Media).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    yield
    app_client.cookies.clear()


# ---------------------------------------------------------------------------
# 登录守卫
# ---------------------------------------------------------------------------
class TestGuard:
    @pytest.mark.parametrize("path", PROTECTED_GETS)
    def test_unauthenticated_get_returns_401(self, client, path):
        resp = client.get(path)
        assert resp.status_code == 401, f"{path} -> {resp.status_code}"
        assert resp.json()["detail"]  # 有可读中文提示

    def test_unauthenticated_post_returns_401(self, client):
        # 守卫是中间件，在路由/校验之前就拦截
        resp = client.post("/api/media")
        assert resp.status_code == 401

    def test_health_is_public(self, client):
        assert client.get("/api/health").status_code == 200

    def test_auth_status_is_public(self, client):
        assert client.get("/api/auth/status").status_code == 200

    @pytest.mark.parametrize("path", ["/", "/assets/missing.js", "/favicon.ico"])
    def test_static_paths_are_not_blocked(self, client, path):
        # 拦截点在接口层；静态资源不因未登录被 401
        assert client.get(path).status_code != 401

    def test_guard_rejects_tampered_cookie(self, client):
        resp = client.get(
            "/api/media",
            headers={"Cookie": "fayelong_session=not-a-valid-token"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 状态机
# ---------------------------------------------------------------------------
class TestStatusMachine:
    def test_unfinished_is_exactly_the_processing_chain(self):
        assert cfg.UNFINISHED_STATUSES == (
            cfg.STATUS_PENDING,
            cfg.STATUS_TRANSCODING,
            cfg.STATUS_READY,
            cfg.STATUS_ASR,
            cfg.STATUS_TRANSLATING,
            cfg.STATUS_CLIPPING,
        )
        assert cfg.STATUS_DONE not in cfg.UNFINISHED_STATUSES
        assert cfg.STATUS_FAILED not in cfg.UNFINISHED_STATUSES

    def test_audio_ready_statuses(self):
        assert cfg.AUDIO_READY_STATUSES == (
            cfg.STATUS_READY,
            cfg.STATUS_ASR,
            cfg.STATUS_TRANSLATING,
            cfg.STATUS_CLIPPING,
            cfg.STATUS_DONE,
        )
        assert cfg.STATUS_PENDING not in cfg.AUDIO_READY_STATUSES

    def test_legal_chain_recorded(self, db_session):
        media = Media(title="flow", file_path="/tmp/x.mp3", type="audio")
        db_session.add(media)
        db_session.commit()
        assert media.status == cfg.STATUS_PENDING
        assert media.progress == 0

        chain = [
            cfg.STATUS_TRANSCODING,
            cfg.STATUS_READY,
            cfg.STATUS_ASR,
            cfg.STATUS_TRANSLATING,
            cfg.STATUS_CLIPPING,
            cfg.STATUS_DONE,
        ]
        for index, status in enumerate(chain, start=1):
            media_service._set_stage(db_session, media, status, index * 10)
            assert media.status == status
            assert media.progress == index * 10
            assert media.error is None

    def test_mark_failed_sets_failed_and_clears_progress(self, db_session):
        media = Media(title="boom", file_path="/tmp/y.mp3", type="audio")
        db_session.add(media)
        db_session.commit()

        media_service._mark_failed(media.id, "转码失败：源文件损坏")
        db_session.expire_all()
        fresh = db_session.get(Media, media.id)
        assert fresh.status == cfg.STATUS_FAILED
        assert fresh.progress == 0
        assert fresh.error == "转码失败：源文件损坏"

    def test_mark_failed_truncates_long_message(self, db_session):
        media = Media(title="long", file_path="/tmp/z.mp3", type="audio")
        db_session.add(media)
        db_session.commit()

        media_service._mark_failed(media.id, "x" * 1000)
        db_session.expire_all()
        assert len(db_session.get(Media, media.id).error) == 500


# ---------------------------------------------------------------------------
# requeue_unfinished 自愈
# ---------------------------------------------------------------------------
class TestRequeueUnfinished:
    def test_resets_only_unfinished_and_reenqueues(self, monkeypatch):
        from app.db import SessionLocal

        seed_statuses = [
            cfg.STATUS_PENDING,
            cfg.STATUS_TRANSCODING,
            cfg.STATUS_READY,
            cfg.STATUS_ASR,
            cfg.STATUS_TRANSLATING,
            cfg.STATUS_CLIPPING,
            cfg.STATUS_DONE,
            cfg.STATUS_FAILED,
        ]
        db = SessionLocal()
        try:
            ids: dict[str, int] = {}
            for status in seed_statuses:
                row = Media(
                    title=status, file_path="/tmp/seed.mp3", type="audio",
                    status=status, progress=55,
                )
                db.add(row)
                db.commit()
                ids[status] = row.id
        finally:
            db.close()

        enqueued: list[int] = []
        monkeypatch.setattr(media_service, "enqueue", lambda mid: enqueued.append(mid))

        count = media_service.requeue_unfinished()

        unfinished = [
            cfg.STATUS_PENDING,
            cfg.STATUS_TRANSCODING,
            cfg.STATUS_READY,
            cfg.STATUS_ASR,
            cfg.STATUS_TRANSLATING,
            cfg.STATUS_CLIPPING,
        ]
        assert count == len(unfinished)

        db = SessionLocal()
        try:
            for status in unfinished:
                row = db.get(Media, ids[status])
                assert row.status == cfg.STATUS_PENDING, status
                assert row.progress == 0, status
            for status in (cfg.STATUS_DONE, cfg.STATUS_FAILED):
                row = db.get(Media, ids[status])
                assert row.status == status
                assert row.progress == 55
        finally:
            db.close()

        assert sorted(enqueued) == sorted(ids[s] for s in unfinished)

    def test_noop_when_nothing_unfinished(self, monkeypatch):
        enqueued: list[int] = []
        monkeypatch.setattr(media_service, "enqueue", lambda mid: enqueued.append(mid))
        assert media_service.requeue_unfinished() == 0
        assert enqueued == []

    def test_skips_media_that_already_has_active_job(self, monkeypatch):
        """P4 挂账 A2：已有活跃 job 的媒体必须**原样跳过**（不重置进度、不入队）。

        现场（P3-2 之后才可能出现）：worker 正在跑该媒体的 `media_asr`，而 web
        进程重启触发了 `requeue_unfinished()`。旧实现会把 `media.status` 重置成
        `pending`、进度归 0，还额外入队一条 `media_transcode`（跨 kind 不撞
        `uq_jobs_active`），用户看到进度条毫无道理地跳回 0。
        """
        from app.db import SessionLocal
        from app.models import Job
        from app.services import jobs as jobs_service

        db = SessionLocal()
        try:
            media = Media(
                title="running",
                file_path="/tmp/running.mp3",
                type="audio",
                status=cfg.STATUS_ASR,
                progress=55,
            )
            db.add(media)
            db.commit()
            media_id = int(media.id)
            # 模拟「worker 手上正有一条 running 的 media_asr」
            job = Job(
                kind=jobs_service.KIND_ASR,
                ref_id=media_id,
                status=jobs_service.JOB_RUNNING,
                progress=30,
                attempts=1,
                worker_id="worker-in-test",
            )
            db.add(job)
            db.commit()
        finally:
            db.close()

        enqueued: list[int] = []
        monkeypatch.setattr(media_service, "enqueue", lambda mid: enqueued.append(mid))
        try:
            # 返回「实际重新入队条数」→ 全部跳过时为 0
            assert media_service.requeue_unfinished() == 0
            assert enqueued == [], f"已有活跃 job 的媒体不该被重新入队：{enqueued}"

            db = SessionLocal()
            try:
                row = db.get(Media, media_id)
                assert row is not None
                assert row.status == cfg.STATUS_ASR, f"media.status 被重置成 {row.status!r}"
                assert row.progress == 55, f"media.progress 被清零成 {row.progress}"
            finally:
                db.close()
        finally:
            # 清掉本用例造的 job 行：media 表由 autouse fixture 清理，
            # 但 jobs 不会级联（ref_id 是刻意不加外键的多态引用）。
            cleanup = SessionLocal()
            try:
                cleanup.query(Job).filter(
                    Job.kind.like("media_%"), Job.ref_id == media_id
                ).delete(synchronize_session=False)
                cleanup.commit()
            finally:
                cleanup.close()

    def test_requeues_media_without_active_job(self, monkeypatch):
        """对照：**没有**活跃 job 的未完成媒体，照旧重置进度并重新入队。"""
        from app.db import SessionLocal

        db = SessionLocal()
        try:
            media = Media(
                title="orphan",
                file_path="/tmp/orphan.mp3",
                type="audio",
                status=cfg.STATUS_ASR,
                progress=55,
            )
            db.add(media)
            db.commit()
            media_id = int(media.id)
        finally:
            db.close()

        enqueued: list[int] = []
        monkeypatch.setattr(media_service, "enqueue", lambda mid: enqueued.append(mid))

        assert media_service.requeue_unfinished() == 1
        assert enqueued == [media_id]

        db = SessionLocal()
        try:
            row = db.get(Media, media_id)
            assert row is not None
            assert row.status == cfg.STATUS_PENDING
            assert row.progress == 0
        finally:
            db.close()
