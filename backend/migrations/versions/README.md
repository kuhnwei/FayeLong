# migrations/versions —— 只放迁移脚本

Alembic 的 `ScriptDirectory` 会扫描本目录下**所有 `*.py`**（不看文件名），
把每一个都当作迁移脚本加载。因此：

- ✅ 迁移脚本：`0001_baseline.py`、将来的 `0002_*.py` …（`revision` 必须唯一）
- ❌ **不要**把备份、临时脚本、变异测试副本放在这里
  （例如 `_backup.py` 会被当成第二个 `0001` 加载，直接报 `duplicate revision`，
   整套测试集体失败）

做破坏性验证时，请把 `backend/` 整体复制到临时目录，在**沙箱**里改，
不要改动交付物本身（见 `docs/REFACTOR-PLAN-001-执行计划.md` §0 第 6 条）。
