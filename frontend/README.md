# ⚠️ 已冻结：本目录被 `frontend-vue/` 取代

> **这套 React 前端已于 P5 切换时正式下线**，`frontend-vue/`（Vue 3 + Vite）是唯一的
> 现役前端。本目录**仅作历史参考与回滚兜底，不再维护** —— 不要在这里改 bug、加功能、
> 升级依赖，也不要再跑它的 `npm run build` 覆盖产物。
>
> - **冻结基线**：git tag **`frontend-react-final`**（本地 tag，未推远端）。要看冻结时的
>   完整代码：`git show frontend-react-final --stat` / `git worktree add ../fe-react frontend-react-final`。
> - **为什么不删**：回滚成本要压到 5 分钟以内。留着整套可运行源码 + 已构建的 `dist/`，
>   出问题时不依赖任何网络与工具链就能切回去（见下方回滚步骤）。
> - **禁止长期并行维护两套 SPA**：那是双倍成本，比不重构更糟（`docs/REFACTOR-PLAN-001-执行计划.md` §8 范围护栏）。

## 回滚步骤（< 5 分钟，后端零改动）

`backend/app/core/config.py::STATIC_CANDIDATES` 的语义是「**取第一个含 `index.html` 的候选**」，
顺序即回滚策略。当前顺序：

```python
STATIC_CANDIDATES = (
    ROOT_DIR / "frontend-vue" / "dist",   # 现役：Vue 版
    ROOT_DIR / "frontend" / "dist",       # 回滚兜底：本目录（tag: frontend-react-final）
    ROOT_DIR / "static",                  # 打包环境
)
```

1. 把 `frontend-vue/dist` 那一行**注释掉或与 `frontend/dist` 互换位置**（让 `frontend/dist` 排在前面）；
2. 重启后端（开发：`scripts\start-backend.bat`；云端：`systemctl restart fayelong`）；
3. 验证：`curl -s http://127.0.0.1:8000/ | head` —— 页面 `assets/` 指向的
   bundle 文件名应与本目录 `dist/assets/` 下的实际文件一致（React 包内含 `__reactContainer$`，
   不含 `__vue_app__`，这是区分两套产物最可靠的判据；两者 `index.html` 的挂载点**都是** `id="root"`，
   别拿 `id` 判断）。

前提：本目录 `dist/` 未被删除。若已误删，`cd frontend && npm install --ignore-scripts && npx vite build` 重建
（⚠️ `--ignore-scripts` 必须带，本机 esbuild 的 postinstall 会 EBUSY）。

## 双跑比对（如需再比对一次）

| 版本 | 启动 | 端口 |
|---|---|---|
| 现役 Vue | `scripts\start-frontend.bat` | 5174 |
| 旧 React | `scripts\start-frontend-react.bat` | 5173 |

两者默认都代理到 `http://127.0.0.1:8000`，可在同一后端上逐页对照。

## 这是什么

FayeLong 英语学习网站的原始前端：React 18 + Vite + Tailwind + TanStack Query + zustand。
入口 `src/main.tsx`、请求层 `src/api/client.ts`（699 行）、页面见 `src/pages/`。
历史功能与踩坑记录见 `docs/MEMORY.md` 与 `docs/REFACTOR-PLAN-001-执行计划.md` §4–§5。
