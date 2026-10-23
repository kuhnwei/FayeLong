// 本文件由 scripts/gen-api-types.mjs 自动生成，请勿手改。
// 数据来源：contracts/openapi-v1.json（后端 app.openapi() 的冻结基线）。
// 重新生成：node scripts/gen-api-types.mjs

export interface paths {
    "/api/admin/users": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Users
         * @description 用户列表（含每人的学习统计摘要，供对比）。
         */
        get: operations["list_users_api_admin_users_get"];
        put?: never;
        /**
         * Create User
         * @description 创建用户（默认普通用户，可显式建管理员）。
         */
        post: operations["create_user_api_admin_users_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/admin/users/compare": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Compare Users
         * @description 多用户学习状态对比（与 `/users` 同口径，语义化别名）。
         */
        get: operations["compare_users_api_admin_users_compare_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/admin/users/{user_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /**
         * Delete User
         * @description 软删除用户（`is_active=false`，数据保留）；旧会话立即失效。
         */
        delete: operations["delete_user_api_admin_users__user_id__delete"];
        options?: never;
        head?: never;
        /**
         * Update User
         * @description 启停 / 改角色。停用或降级会让该用户的旧会话立即失效。
         */
        patch: operations["update_user_api_admin_users__user_id__patch"];
        trace?: never;
    };
    "/api/admin/users/{user_id}/reset-password": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Reset Password
         * @description 重置密码（admin 指定新密码）；重置后旧会话立即失效。
         */
        post: operations["reset_password_api_admin_users__user_id__reset_password_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/admin/users/{user_id}/stats": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get User Stats
         * @description 单个用户的详细学习统计。
         */
        get: operations["get_user_stats_api_admin_users__user_id__stats_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/attempts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Create Attempt
         * @description 提交一次听写：与标准答案比对，记录结果并返回词级明细。
         */
        post: operations["create_attempt_api_attempts_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Login
         * @description 登录。失败次数过多会临时封禁该来源 IP。
         */
        post: operations["login_api_auth_login_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/logout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Logout
         * @description 退出登录：只清 cookie（token 无状态，服务端无需额外作废）。
         */
        post: operations["logout_api_auth_logout_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/password": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Change Password
         * @description 修改密码。需已登录且知道当前密码；改密后旧 cookie 立即失效、重发新会话。
         */
        post: operations["change_password_api_auth_password_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/setup": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Setup
         * @description 首次初始化：创建**管理员**账号。已存在任何账号时一律拒绝（防止公网上被抢占/重置）。
         */
        post: operations["setup_api_auth_setup_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/auth/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Auth Status
         * @description 鉴权状态。前端据此决定渲染「首次设置」「登录页」还是应用本体。
         */
        get: operations["auth_status_api_auth_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/categories": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Categories
         * @description 全部分类（含每个分类的素材数）+ 「未分类」素材数。
         */
        get: operations["list_categories_api_categories_get"];
        put?: never;
        /**
         * Create Category
         * @description 新建分类（仅管理员）。`sort_order = COALESCE(MAX(sort_order), -1) + 1`。
         */
        post: operations["create_category_api_categories_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/categories/order": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Reorder Categories
         * @description 按提交的 ids 顺序重写 `sort_order`（0 基）。仅管理员。
         *
         *     `ids` 必须是当前**全部分类 id 的完整有序集合**：不得有未知 id、不得缺项、不得重复，
         *     否则 400。
         */
        patch: operations["reorder_categories_api_categories_order_patch"];
        trace?: never;
    };
    "/api/categories/{category_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /**
         * Delete Category
         * @description 删除分类（仅管理员）：先把旗下素材退回「未分类」，再删分类行；**不删任何素材**。
         *
         *     显式 `UPDATE media SET category_id=NULL` 而不依赖 DB 级联 —— 即使某条连接未开
         *     FK，回落语义也正确；DB 级 `ON DELETE SET NULL` 只作第二道防线。
         */
        delete: operations["delete_category_api_categories__category_id__delete"];
        options?: never;
        head?: never;
        /**
         * Update Category
         * @description 重命名分类（本轮只允许改 name）。仅管理员。
         */
        patch: operations["update_category_api_categories__category_id__patch"];
        trace?: never;
    };
    "/api/dict/{word}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Lookup Word
         * @description 查询一个英文单词（含词形还原）。
         */
        get: operations["lookup_word_api_dict__word__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Health
         * @description 返回服务状态、关键依赖自检结果与数据目录位置。
         */
        get: operations["health_api_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/media": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Media
         * @description 素材列表。可选 `category_id` 过滤：
         *
         *     - 缺省 → 不加条件（保持既有「全部」行为，契约兼容）
         *     - 字面量 `none` → 只看「未分类」（`category_id IS NULL`）
         *     - 整数串 → 只看该分类
         *     - 其他非法值 → 400
         */
        get: operations["list_media_api_media_get"];
        put?: never;
        /**
         * Upload Media
         * @description 上传一个音频 / 视频文件（视频仅取音轨）；可选指定分类。仅管理员可上传。
         */
        post: operations["upload_media_api_media_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/media/batch-category": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Batch Set Category
         * @description 批量把素材移动到某个分类（`category_id=null` = 移到「未分类」）。仅管理员。
         *
         *     - `ids` 为空 → 400；`category_id` 指向的分类不存在 → 404。
         *     - `ids` 中不存在的媒体 id 不报错，收进 `missing` 回报，便于前端提示「N 个已失效」。
         */
        post: operations["batch_set_category_api_media_batch_category_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/media/import": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Import From Inbox
         * @description 从收件箱导入；不传 files 则导入全部尚未导入的受支持文件。仅管理员。
         */
        post: operations["import_from_inbox_api_media_import_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/media/inbox": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Inbox
         * @description 列出收件箱里的素材（仅管理员；用户直接把文件放进该目录即可）。
         */
        get: operations["get_inbox_api_media_inbox_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/media/{media_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Media */
        get: operations["get_media_api_media__media_id__get"];
        put?: never;
        post?: never;
        /** Delete Media */
        delete: operations["delete_media_api_media__media_id__delete"];
        options?: never;
        head?: never;
        /** Update Media */
        patch: operations["update_media_api_media__media_id__patch"];
        trace?: never;
    };
    "/api/media/{media_id}/clips": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /**
         * Clear Clips
         * @description 清理切片以回收磁盘（学习页仍可整段播放）。仅管理员。
         */
        delete: operations["clear_clips_api_media__media_id__clips_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/media/{media_id}/clips/{idx}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Clip
         * @description 取某一句的音频切片（支持 Range，便于单句循环与拖动）。
         */
        get: operations["get_clip_api_media__media_id__clips__idx__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/media/{media_id}/notes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Media Notes
         * @description 某个媒体的句子笔记汇总（供学习页「笔记」面板）。
         */
        get: operations["list_media_notes_api_media__media_id__notes_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/media/{media_id}/notes/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Export Media Notes
         * @description 导出某个媒体的句子笔记为 Markdown 文件（浏览器下载）。
         */
        get: operations["export_media_notes_api_media__media_id__notes_export_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/media/{media_id}/progress": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Media Progress
         * @description 以 SSE 推送处理进度，直到 `done` / `failed` 后自动结束。
         */
        get: operations["media_progress_api_media__media_id__progress_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/media/{media_id}/retranscribe": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Retranscribe Media
         * @description 重新识别（保留已转码音频，只重跑 识别→翻译→切片）。仅管理员。
         *
         *     注意：会按识别结果重建句表，原有句子笔记与听写记录将一并清除。
         */
        post: operations["retranscribe_media_api_media__media_id__retranscribe_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/media/{media_id}/retry": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Retry Media
         * @description 重新处理（失败重试 / 手动重跑转码）。仅管理员。
         */
        post: operations["retry_media_api_media__media_id__retry_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/media/{media_id}/stream": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Stream Media
         * @description 流式播放：优先转码后的标准音频；转码完成前回退播放原始音频文件。
         */
        get: operations["stream_media_api_media__media_id__stream_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/notes/{sentence_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Note
         * @description 读取某句的笔记。
         */
        get: operations["get_note_api_notes__sentence_id__get"];
        /**
         * Save Note
         * @description 保存某句的笔记（upsert；内容为空则删除该笔记）。
         */
        put: operations["save_note_api_notes__sentence_id__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/papers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Papers
         * @description 试卷列表（新的在前）。
         *
         *     Notes:
         *         计数（`section_count` / `question_count`）由两个聚合子查询一次算完，
         *         **不会**为每张卷子再查一次（N+1 是这类列表接口最常见的性能坑）。
         */
        get: operations["list_papers_api_papers_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/papers/{paper_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Paper
         * @description 试卷结构（无答案）。
         *
         *     Raises:
         *         HTTPException: 404 —— 试卷不存在。
         */
        get: operations["get_paper_api_papers__paper_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/papers/{paper_id}/sessions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Create Session
         * @description 开始一次作答（`status='in_progress'`）。
         *
         *     Raises:
         *         HTTPException: 404 —— 试卷不存在。
         */
        post: operations["create_session_api_papers__paper_id__sessions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/question-types": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Question Types
         * @description 下发全部已注册题型（code / label / grade_mode / requires_external）。
         *
         *     Returns:
         *         `{"types": [...]}`，按 `code` 升序；注册表为空时返回 `{"types": []}`。
         *
         *     Notes:
         *         端点以 **GET `/api/question-types`** 暴露（与现有 34 个端点同一风格：
         *         复数资源名 + 无尾部斜杠）。它受 `main.py` 的全局登录门禁保护 ——
         *         清单里不含任何题目内容，但仍然不该给未登录者看站点结构。
         */
        get: operations["list_question_types_api_question_types_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/sentences/{sentence_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Update Sentence
         * @description 编辑单句（原文 / 翻译 / 时间边界）。仅管理员。
         */
        patch: operations["update_sentence_api_sentences__sentence_id__patch"];
        trace?: never;
    };
    "/api/sentences/{sentence_id}/attempts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Attempts
         * @description 某句的听写历史（按时间倒序），每条记录附带词级明细。
         *
         *     明细是**读取时按当前原文实时重算的复盘视图**，不落库（`attempts` 表只追加、
         *     不存词级明细）。因此比对基准始终是句子当前的标准答案 `text_en`；若原文后来被
         *     校对改过，明细会随之变化，但每条记录的 `accuracy` / `is_correct` 仍是**提交当时
         *     写入数据库的历史值**（历史成绩是当时的事实，不因改原文而变）。
         */
        get: operations["list_attempts_api_sentences__sentence_id__attempts_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/sentences/{sentence_id}/marks": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Update Marks
         * @description 整体替换当前用户在该句上的「易听错」标记（空数组 = 清空）。
         */
        put: operations["update_marks_api_sentences__sentence_id__marks_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/sentences/{sentence_id}/merge": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Merge Sentence
         * @description 与相邻句合并（默认向后合并）。仅管理员。
         */
        post: operations["merge_sentence_api_sentences__sentence_id__merge_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/sentences/{sentence_id}/retranslate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Retranslate Sentence
         * @description 单句重新翻译（在线引擎 + 缓存）。仅管理员。
         */
        post: operations["retranslate_sentence_api_sentences__sentence_id__retranslate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/sentences/{sentence_id}/split": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Split Sentence
         * @description 在 `at_ms` 处把一句拆成两句。仅管理员。
         */
        post: operations["split_sentence_api_sentences__sentence_id__split_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/sessions/{session_id}/report": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Report
         * @description 成绩报告（`pending > 0` 时说明还有题在等判分，不是错误）。
         *
         *     Raises:
         *         HTTPException: 404 会话不存在；**409 尚未交卷**（报告是交卷后的成绩单）。
         */
        get: operations["get_report_api_sessions__session_id__report_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/sessions/{session_id}/responses": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Patch Responses
         * @description 暂存/更新作答（批量 upsert：同一题重复提交是覆盖，不是新增）。
         *
         *     Raises:
         *         HTTPException: 404 会话不存在；409 已交卷；400 题号不属于本试卷。
         */
        patch: operations["patch_responses_api_sessions__session_id__responses_patch"];
        trace?: never;
    };
    "/api/sessions/{session_id}/submit": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Submit Session
         * @description 交卷判分。
         *
         *     Notes:
         *         * **幂等**：重复提交不重新判分；只会为「已交卷但还没入队」的异步题补入队。
         *         * 返回值里 `status='grading'` + `pending>0` 意味着写作批改还在 worker 里跑，
         *           前端应轮询 `GET /api/sessions/{id}/report`（**交卷请求绝不阻塞**）。
         *         * 请求线程**绝不**调用外部批改服务：async 题只入队。
         *
         *     Raises:
         *         HTTPException: 404 会话不存在；409 还没有作答。
         */
        post: operations["submit_session_api_sessions__session_id__submit_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/stats": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Stats
         * @description 返回当前用户的全局学习概览（媒体/句子是共享内容，其余按用户隔离）。
         */
        get: operations["get_stats_api_stats_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/stats/overview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Overview
         * @description 统计页 14 天学习概览（ARCH §6.1）。
         *
         *     口径：
         *     - 所有「按日」聚合用 `func.date(..., 'localtime')` 得到**本地日** `YYYY-MM-DD`；
         *     - `daily` 恒为 `days` 长（0 填充，无听写日 attempts/accuracy/new_vocab 显式 0）；
         *     - `streak_days`：从今天向前数连续 `attempts>0` 的天数，今天无听写 → 0；
         *     - `courses.pct` 0–100 float，`total=0` 时 0；按 pct desc 取前 10；
         *     - `recent` 按 `created_at desc` 取 6 条；
         *     - 空库返回 HTTP 200 全零结构（非 404）。
         *     - 多用户：所有个人口径（听写/生词/最近）按当前用户 `user_id` 隔离。
         */
        get: operations["get_overview_api_stats_overview_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/vocab": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Vocab */
        get: operations["list_vocab_api_vocab_get"];
        put?: never;
        /**
         * Create Vocab
         * @description 把一个生词加入生词本（同一词重复添加不会产生第二条）。
         */
        post: operations["create_vocab_api_vocab_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/vocab/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Export Vocab
         * @description 导出整个生词本为 Markdown 文件。
         */
        get: operations["export_vocab_api_vocab_export_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/vocab/{vocab_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Delete Vocab */
        delete: operations["delete_vocab_api_vocab__vocab_id__delete"];
        options?: never;
        head?: never;
        /** Update Vocab */
        patch: operations["update_vocab_api_vocab__vocab_id__patch"];
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * AdminPasswordReset
         * @description 重置密码（admin 指定新密码）。
         */
        AdminPasswordReset: {
            /** New Password */
            new_password: string;
        };
        /**
         * AdminUserCreate
         * @description 创建普通/管理员用户（仅 admin 可调）。
         */
        AdminUserCreate: {
            /** Password */
            password: string;
            /**
             * Role
             * @default user
             * @enum {string}
             */
            role: "admin" | "user";
            /** Username */
            username: string;
        };
        /** AdminUserList */
        AdminUserList: {
            /** Items */
            items: components["schemas"]["AdminUserOut"][];
            /** Total */
            total: number;
        };
        /**
         * AdminUserOut
         * @description 用户列表项（含统计摘要，供对比）。
         */
        AdminUserOut: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Id */
            id: number;
            /** Is Active */
            is_active: boolean;
            /** Last Login At */
            last_login_at: string | null;
            /** Role */
            role: string;
            stats: components["schemas"]["AdminUserSummary"];
            /** Username */
            username: string;
        };
        /**
         * AdminUserSummary
         * @description 单个用户的学习统计摘要（全部按 `user_id` 聚合）。
         */
        AdminUserSummary: {
            /**
             * Attempted Sentences
             * @default 0
             */
            attempted_sentences: number;
            /** Attempts Avg Accuracy */
            attempts_avg_accuracy?: number | null;
            /**
             * Attempts Total
             * @default 0
             */
            attempts_total: number;
            /**
             * Mastered Sentences
             * @default 0
             */
            mastered_sentences: number;
            /**
             * Notes Count
             * @default 0
             */
            notes_count: number;
            /**
             * Sessions Total
             * @default 0
             */
            sessions_total: number;
            /**
             * Streak Days
             * @default 0
             */
            streak_days: number;
            /**
             * Vocab Mastered
             * @default 0
             */
            vocab_mastered: number;
            /**
             * Vocab Total
             * @default 0
             */
            vocab_total: number;
        };
        /**
         * AdminUserUpdate
         * @description 启停 / 改角色（字段均可选）。
         */
        AdminUserUpdate: {
            /** Is Active */
            is_active?: boolean | null;
            /** Role */
            role?: ("admin" | "user") | null;
        };
        /**
         * AttemptCreate
         * @description 提交一次听写。
         */
        AttemptCreate: {
            /**
             * Input
             * @default
             */
            input: string;
            /** Sentence Id */
            sentence_id: number;
        };
        /** AttemptListResponse */
        AttemptListResponse: {
            /** Items */
            items: components["schemas"]["AttemptRecord"][];
            /** Total */
            total: number;
        };
        /**
         * AttemptRecord
         * @description 一条历史听写记录（含词级明细）。
         *
         *     词级明细（`tokens` 与四类计数）是**读取时按当前原文实时重算的复盘视图**，
         *     并不落库（`attempts` 表只追加、不存明细）；而 `accuracy` / `is_correct`
         *     取的是**提交当时写入数据库的历史值**，因此若原文后来被校对改过，
         *     明细的比对基准是当前原文，成绩仍是历史值，二者可能不一致——这是有意为之。
         */
        AttemptRecord: {
            /** Accuracy */
            accuracy: number;
            /**
             * Correct
             * @default 0
             */
            correct: number;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Extra
             * @default 0
             */
            extra: number;
            /** Id */
            id: number;
            /** Input */
            input: string;
            /** Is Correct */
            is_correct: boolean;
            /**
             * Missing
             * @default 0
             */
            missing: number;
            /** Tokens */
            tokens?: components["schemas"]["DiffToken"][];
            /**
             * Total Words
             * @default 0
             */
            total_words: number;
            /**
             * Wrong
             * @default 0
             */
            wrong: number;
        };
        /**
         * AttemptResult
         * @description 一次听写的校验结果 + 该句累计统计。
         */
        AttemptResult: {
            /** Accuracy */
            accuracy: number;
            /**
             * Attempt Count
             * @default 0
             */
            attempt_count: number;
            /** Attempt Id */
            attempt_id: number;
            /**
             * Best Accuracy
             * @default 0
             */
            best_accuracy: number;
            /**
             * Correct
             * @default 0
             */
            correct: number;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Extra
             * @default 0
             */
            extra: number;
            /** Input */
            input: string;
            /** Is Correct */
            is_correct: boolean;
            /**
             * Mastered
             * @default false
             */
            mastered: boolean;
            /**
             * Missing
             * @default 0
             */
            missing: number;
            /** Sentence Id */
            sentence_id: number;
            /** Tokens */
            tokens?: components["schemas"]["DiffToken"][];
            /**
             * Total Words
             * @default 0
             */
            total_words: number;
            /**
             * Wrong
             * @default 0
             */
            wrong: number;
        };
        /** AttemptStatsOut */
        AttemptStatsOut: {
            /**
             * Attempted Sentences
             * @default 0
             */
            attempted_sentences: number;
            /**
             * Mastered Sentences
             * @default 0
             */
            mastered_sentences: number;
            /**
             * Total
             * @default 0
             */
            total: number;
        };
        /**
         * AuthStatus
         * @description 前端启动时最先拉取的鉴权状态。
         */
        AuthStatus: {
            /** Authenticated */
            authenticated: boolean;
            /** Id */
            id?: number | null;
            /** Is Active */
            is_active?: boolean | null;
            /**
             * Min Password Length
             * @default 8
             */
            min_password_length: number;
            /** Needs Setup */
            needs_setup: boolean;
            /** Role */
            role?: string | null;
            /** Username */
            username?: string | null;
        };
        /**
         * BatchCategoryRequest
         * @description 批量把素材移动到某个分类。
         *
         *     `category_id` **必填**（规格 §3.2b）：显式传 `null` = 移到「未分类」，
         *     从而区分「有意移到未分类」与「客户端漏传」。
         */
        BatchCategoryRequest: {
            /** Category Id */
            category_id: number | null;
            /** Ids */
            ids: number[];
        };
        /** Body_upload_media_api_media_post */
        Body_upload_media_api_media_post: {
            /** Category Id */
            category_id?: number | null;
            /** File */
            file: string;
        };
        /**
         * CategoryCreate
         * @description 新建分类。
         */
        CategoryCreate: {
            /** Name */
            name: string;
        };
        /**
         * CategoryListResponse
         * @description 分类列表 + 「未分类」计数。
         */
        CategoryListResponse: {
            /** Items */
            items: components["schemas"]["CategoryOut"][];
            /** Total */
            total: number;
            /** Uncategorized Count */
            uncategorized_count: number;
        };
        /**
         * CategoryOut
         * @description 单个分类。
         */
        CategoryOut: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Id */
            id: number;
            /** Media Count */
            media_count: number;
            /** Name */
            name: string;
            /** Sort Order */
            sort_order: number;
        };
        /**
         * CategoryReorder
         * @description 提交整份分类顺序。ids 必须是当前全部分类 id 的完整有序集合。
         */
        CategoryReorder: {
            /** Ids */
            ids: number[];
        };
        /**
         * CategoryUpdate
         * @description 重命名分类（本轮只允许改 name）。
         */
        CategoryUpdate: {
            /** Name */
            name: string;
        };
        /**
         * CourseProgressOut
         * @description 单个素材的听写完成度。
         */
        CourseProgressOut: {
            /**
             * Attempted
             * @default 0
             */
            attempted: number;
            /** Media Id */
            media_id: number;
            /**
             * Pct
             * @default 0
             */
            pct: number;
            /** Title */
            title: string;
            /**
             * Total
             * @default 0
             */
            total: number;
        };
        /** Credentials */
        Credentials: {
            /** Password */
            password: string;
            /** Username */
            username: string;
        };
        /**
         * DailyPoint
         * @description 单日听写量点。无听写日为显式 0（前端不判空）。
         */
        DailyPoint: {
            /**
             * Accuracy
             * @default 0
             */
            accuracy: number;
            /**
             * Attempts
             * @default 0
             */
            attempts: number;
            /** Date */
            date: string;
            /**
             * New Vocab
             * @default 0
             */
            new_vocab: number;
        };
        /**
         * DictForm
         * @description 词形变化的一项，如 `过去式：went`。
         */
        DictForm: {
            /** Label */
            label: string;
            /** Value */
            value: string;
        };
        /**
         * DictResult
         * @description 一次查词的结果。
         *
         *     - `found=False` 时 `notice` 会给出原因（未安装词库 / 未收录），前端据此展示。
         *     - `lemma` 非空表示查询词是变形，已还原到原型（`word` 为原型）。
         */
        DictResult: {
            /**
             * Collins
             * @default 0
             */
            collins: number;
            /** Definition */
            definition?: string[];
            /** Exchange */
            exchange?: {
                [key: string]: string;
            };
            /** Forms */
            forms?: components["schemas"]["DictForm"][];
            /**
             * Found
             * @default false
             */
            found: boolean;
            /** Lemma */
            lemma?: string | null;
            /**
             * Longman Url
             * @default
             */
            longman_url: string;
            /** Notice */
            notice?: string | null;
            /**
             * Oxford
             * @default 0
             */
            oxford: number;
            /**
             * Oxford Url
             * @default
             */
            oxford_url: string;
            /**
             * Phonetic
             * @default
             */
            phonetic: string;
            /**
             * Pos
             * @default
             */
            pos: string;
            /** Query */
            query: string;
            /**
             * Source
             * @default ecdict
             */
            source: string;
            /** Tags */
            tags?: string[];
            /** Translation */
            translation?: string[];
            /**
             * Via
             * @default
             */
            via: string;
            /**
             * Word
             * @default
             */
            word: string;
        };
        /**
         * DictationSummary
         * @description 整个媒体的听写进度汇总（学习页头部）。
         */
        DictationSummary: {
            /**
             * Attempted
             * @default 0
             */
            attempted: number;
            /**
             * Avg Best Accuracy
             * @default 0
             */
            avg_best_accuracy: number;
            /**
             * Mastered
             * @default 0
             */
            mastered: number;
            /**
             * Sentences
             * @default 0
             */
            sentences: number;
            /**
             * Total Attempts
             * @default 0
             */
            total_attempts: number;
        };
        /**
         * DiffToken
         * @description 对齐结果中的一个位置。
         *
         *     - `correct`：正常色，`expected == actual`
         *     - `wrong`  ：标红，显示用户写的 `actual`，`expected` 为正确形式
         *     - `missing`：红色下划线，显示 `expected`（用户漏掉的词）
         *     - `extra`  ：灰色删除线，只显示 `actual`（用户多写的词）
         */
        DiffToken: {
            /** Actual */
            actual?: string | null;
            /** Expected */
            expected?: string | null;
            /**
             * Type
             * @enum {string}
             */
            type: "correct" | "wrong" | "missing" | "extra";
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /**
         * ImportRequest
         * @description 从收件箱导入；files 为空表示导入全部未导入的受支持文件。
         */
        ImportRequest: {
            /** Category Id */
            category_id?: number | null;
            /** Files */
            files?: string[] | null;
        };
        /** InboxItem */
        InboxItem: {
            /** Ext */
            ext: string;
            /** Imported */
            imported: boolean;
            /** Name */
            name: string;
            /** Path */
            path: string;
            /** Size Bytes */
            size_bytes: number;
            /** Supported */
            supported: boolean;
        };
        /** InboxResponse */
        InboxResponse: {
            /** Inbox Dir */
            inbox_dir: string;
            /** Items */
            items: components["schemas"]["InboxItem"][];
        };
        /**
         * KpiOut
         * @description 顶部 KPI 四卡。
         */
        KpiOut: {
            /**
             * Streak Days
             * @default 0
             */
            streak_days: number;
            /**
             * Today Accuracy
             * @default 0
             */
            today_accuracy: number;
            /**
             * Today Attempts
             * @default 0
             */
            today_attempts: number;
            /**
             * Today New Vocab
             * @default 0
             */
            today_new_vocab: number;
        };
        /**
         * MarksUpdate
         * @description 整体替换某句的「易听错」标记（空数组 = 清空）。个人数据，按当前用户隔离。
         */
        MarksUpdate: {
            /** Marks */
            marks: number[][];
        };
        /** MediaDetailOut */
        MediaDetailOut: {
            /** Category Id */
            category_id?: number | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            dictation?: components["schemas"]["DictationSummary"] | null;
            /** Duration Ms */
            duration_ms: number;
            /** Error */
            error?: string | null;
            /** Has Audio */
            has_audio: boolean;
            /** Id */
            id: number;
            /** Origin */
            origin: string;
            /** Original Name */
            original_name: string;
            /** Progress */
            progress: number;
            /**
             * Sentence Count
             * @default 0
             */
            sentence_count: number;
            /** Sentences */
            sentences?: components["schemas"]["SentenceOut"][];
            /** Size Bytes */
            size_bytes: number;
            /** Status */
            status: string;
            /** Stream Url */
            stream_url: string;
            /** Title */
            title: string;
            /** Type */
            type: string;
        };
        /** MediaListResponse */
        MediaListResponse: {
            /** Items */
            items: components["schemas"]["MediaOut"][];
            /** Total */
            total: number;
        };
        /**
         * MediaNoteItem
         * @description 汇总面板 / 导出里的一个条目：句子 + 笔记 + 听写概要。
         */
        MediaNoteItem: {
            /**
             * Attempt Count
             * @default 0
             */
            attempt_count: number;
            /**
             * Best Accuracy
             * @default 0
             */
            best_accuracy: number;
            /**
             * Content
             * @default
             */
            content: string;
            /** Idx */
            idx: number;
            /**
             * Mastered
             * @default false
             */
            mastered: boolean;
            /** Sentence Id */
            sentence_id: number;
            /**
             * Text En
             * @default
             */
            text_en: string;
            /**
             * Text Zh
             * @default
             */
            text_zh: string;
            /** Updated At */
            updated_at?: string | null;
        };
        /**
         * MediaNotesResponse
         * @description 某个媒体的全部句子笔记（按句序）。
         */
        MediaNotesResponse: {
            /** Items */
            items?: components["schemas"]["MediaNoteItem"][];
            /** Media Id */
            media_id: number;
            /**
             * Sentence Count
             * @default 0
             */
            sentence_count: number;
            /** Title */
            title: string;
            /**
             * Total
             * @default 0
             */
            total: number;
        };
        /**
         * MediaOut
         * @description 媒体列表项。
         */
        MediaOut: {
            /** Category Id */
            category_id?: number | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Duration Ms */
            duration_ms: number;
            /** Error */
            error?: string | null;
            /** Has Audio */
            has_audio: boolean;
            /** Id */
            id: number;
            /** Origin */
            origin: string;
            /** Original Name */
            original_name: string;
            /** Progress */
            progress: number;
            /**
             * Sentence Count
             * @default 0
             */
            sentence_count: number;
            /** Size Bytes */
            size_bytes: number;
            /** Status */
            status: string;
            /** Stream Url */
            stream_url: string;
            /** Title */
            title: string;
            /** Type */
            type: string;
        };
        /** MediaStatsOut */
        MediaStatsOut: {
            /**
             * Done
             * @default 0
             */
            done: number;
            /**
             * Failed
             * @default 0
             */
            failed: number;
            /**
             * Processing
             * @default 0
             */
            processing: number;
            /**
             * Total
             * @default 0
             */
            total: number;
        };
        /**
         * MediaUpdate
         * @description PATCH 单个媒体：仅传需要修改的字段。
         *
         *     `category_id` 用于归类：显式传 `null` = 移到「未分类」；
         *     「未传」与「传 null」由 `model_fields_set` 区分（见 app/api/media.py）。
         */
        MediaUpdate: {
            /** Category Id */
            category_id?: number | null;
            /** Title */
            title?: string | null;
        };
        /**
         * NoteOut
         * @description 一句的笔记（每句至多一条）。
         */
        NoteOut: {
            /**
             * Content
             * @default
             */
            content: string;
            /**
             * Exists
             * @default false
             */
            exists: boolean;
            /** Sentence Id */
            sentence_id: number;
            /** Updated At */
            updated_at?: string | null;
        };
        /**
         * NoteUpsert
         * @description 保存句子笔记。内容为空字符串表示删除该笔记。
         */
        NoteUpsert: {
            /**
             * Content
             * @default
             */
            content: string;
        };
        /**
         * OverviewOut
         * @description 统计页 overview 全量响应。
         */
        OverviewOut: {
            /** Courses */
            courses: components["schemas"]["CourseProgressOut"][];
            /** Daily */
            daily: components["schemas"]["DailyPoint"][];
            /**
             * Days
             * @default 14
             */
            days: number;
            kpi: components["schemas"]["KpiOut"];
            /** Recent */
            recent: components["schemas"]["RecentAttemptOut"][];
            vocab: components["schemas"]["VocabStatsOut"];
        };
        /**
         * PaperDetailOut
         * @description `GET /api/papers/{id}` 的响应（结构树，无任何答案）。
         */
        PaperDetailOut: {
            /** Created At */
            created_at?: string | null;
            /** Id */
            id: number;
            /**
             * Mode
             * @default
             */
            mode: string;
            /** Sections */
            sections?: components["schemas"]["SectionOut"][];
            /**
             * Source
             * @default
             */
            source: string;
            /** Tags */
            tags?: string[];
            /**
             * Title
             * @default
             */
            title: string;
        };
        /**
         * PaperListResponse
         * @description `GET /api/papers` 的响应。
         */
        PaperListResponse: {
            /** Items */
            items?: components["schemas"]["PaperOut"][];
            /**
             * Total
             * @default 0
             */
            total: number;
        };
        /**
         * PaperOut
         * @description 试卷列表项（含计数，避免前端为每张卷子再发一次请求）。
         */
        PaperOut: {
            /** Created At */
            created_at?: string | null;
            /** Id */
            id: number;
            /**
             * Mode
             * @description full_mock | section_drill
             */
            mode: string;
            /**
             * Question Count
             * @default 0
             */
            question_count: number;
            /**
             * Section Count
             * @default 0
             */
            section_count: number;
            /**
             * Source
             * @default
             */
            source: string;
            /** Tags */
            tags?: string[];
            /**
             * Title
             * @default
             */
            title: string;
        };
        /**
         * PassageOut
         * @description 一篇文章 + 它的题（**只包含 passage_id 指向它的题**）。
         */
        PassageOut: {
            /**
             * Body Md
             * @default
             */
            body_md: string;
            /** Id */
            id: number;
            /** Ordinal */
            ordinal: number;
            /** Questions */
            questions?: components["schemas"]["QuestionOut"][];
            /** Section Id */
            section_id: number;
            /**
             * Title
             * @default
             */
            title: string;
        };
        /** PasswordChange */
        PasswordChange: {
            /** Current Password */
            current_password: string;
            /** New Password */
            new_password: string;
        };
        /**
         * QuestionOut
         * @description 一道题的**公开**视图（无 answer / explanation）。
         */
        QuestionOut: {
            /** Id */
            id: number;
            /**
             * Options
             * @description 选项；非选择题为空
             */
            options?: unknown[];
            /**
             * Ordinal
             * @description 卷内题号（0 基）
             */
            ordinal: number;
            /**
             * Passage Id
             * @description 归属文章；听力/独立题为 null
             */
            passage_id?: number | null;
            /**
             * Ref Sentence Id
             * @description 听写题复用的句子 id（句子内容走 /api/sentences）
             */
            ref_sentence_id?: number | null;
            /** Section Id */
            section_id: number;
            /**
             * Stem
             * @description 题干
             * @default
             */
            stem: string;
            /**
             * Type
             * @description 题型 code，与 /api/question-types 对齐
             */
            type: string;
        };
        /**
         * QuestionTypeListOut
         * @description `GET /api/question-types` 的响应体；注册表为空时 `types == []`。
         */
        QuestionTypeListOut: {
            /** Types */
            types?: components["schemas"]["QuestionTypeOut"][];
        };
        /**
         * QuestionTypeOut
         * @description 一个题型的契约四元组。
         */
        QuestionTypeOut: {
            /**
             * Code
             * @description 题型标识，与前端 question-types 目录同名
             */
            code: string;
            /**
             * Grade Mode
             * @description 判分模式：sync=纯函数就地判分；async=入 jobs 表由 IO 池判分
             * @enum {string}
             */
            grade_mode: "sync" | "async";
            /**
             * Label
             * @description 中文展示名（为空时后端已按 code 兜底）
             */
            label: string;
            /**
             * Requires External
             * @description 判分是否依赖外部服务；为真时前端应展示降级提示
             * @default false
             */
            requires_external: boolean;
        };
        /**
         * RecentAttemptOut
         * @description 最近一次听写。
         */
        RecentAttemptOut: {
            /** Accuracy */
            accuracy: number;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Sentence Text */
            sentence_text: string;
        };
        /**
         * ReportItemOut
         * @description 成绩报告里的单题明细。
         *
         *     与 `QuestionOut` 的区别：**这里下发 `explanation`** —— 交卷之后看解析是学习，
         *     不是作弊（未交卷时 `GET /api/papers/{id}` 仍然不含它）。
         */
        ReportItemOut: {
            /** Detail */
            detail?: {
                [key: string]: unknown;
            };
            /**
             * Explanation
             * @default
             */
            explanation: string;
            /**
             * Graded
             * @default false
             */
            graded: boolean;
            /** Max Score */
            max_score?: number | null;
            /**
             * Ordinal
             * @default 0
             */
            ordinal: number;
            /** Question Id */
            question_id: number;
            /** Response Id */
            response_id?: number | null;
            /** Score */
            score?: number | null;
            /**
             * Stem
             * @default
             */
            stem: string;
            /**
             * Type
             * @default
             */
            type: string;
            /** User Answer */
            user_answer?: {
                [key: string]: unknown;
            };
        };
        /**
         * ReportOut
         * @description `GET /api/sessions/{id}/report` 的响应。
         *
         *     `pending > 0` 时报告**不是错误**：写作批改还在 worker 里跑，前端应继续轮询
         *     （这正是「交卷不阻塞」的代价与证据）。
         */
        ReportOut: {
            /** Items */
            items?: components["schemas"]["ReportItemOut"][];
            /**
             * Max Score
             * @default 0
             */
            max_score: number;
            /**
             * Pending
             * @default 0
             */
            pending: number;
            session: components["schemas"]["SessionOut"];
            /**
             * Total Score
             * @default 0
             */
            total_score: number;
        };
        /**
         * ResponseIn
         * @description 暂存作答的单条输入。
         */
        ResponseIn: {
            /**
             * Answer
             * @description 作答内容（形状由题型决定）
             */
            answer?: {
                [key: string]: unknown;
            };
            /** Question Id */
            question_id: number;
        };
        /**
         * ResponseOut
         * @description 一条作答（**不含判分明细**）。
         *
         *     🔴 **刻意没有 `detail` 字段**：`detail` 会包含听写题的 `expected`（正确答案）
         *     与写作题的 `reference_answer`，属「交卷后才允许披露」的内容。它只经
         *     `ReportItemOut`（`GET /api/sessions/{id}/report`，未交卷直接 409）下发。
         *     暂存/交卷两条响应都返回 `SessionOut`，因此在这两侧都**不可能**把它带出来 ——
         *     这比「序列化时记得删掉」可靠得多。
         */
        ResponseOut: {
            /** Graded At */
            graded_at?: string | null;
            /** Id */
            id: number;
            /**
             * Max Score
             * @description null = 尚未判分
             */
            max_score?: number | null;
            /** Question Id */
            question_id: number;
            /**
             * Score
             * @description null = 尚未判分
             */
            score?: number | null;
            /** User Answer */
            user_answer?: {
                [key: string]: unknown;
            };
        };
        /**
         * ResponsesPatch
         * @description `PATCH /api/sessions/{id}/responses` 的请求体（**批量 upsert**）。
         */
        ResponsesPatch: {
            /** Responses */
            responses?: components["schemas"]["ResponseIn"][];
            /**
             * Time Spent Sec
             * @description 客户端已用时长（秒）；不传则不改
             */
            time_spent_sec?: number | null;
        };
        /**
         * SectionOut
         * @description 一个分卷 + 直属题（passage_id 为空的题，例如听力/写作）。
         */
        SectionOut: {
            /** Id */
            id: number;
            /**
             * Instructions
             * @default
             */
            instructions: string;
            /**
             * Kind
             * @description listening | reading | writing | speaking
             */
            kind: string;
            /**
             * Media Id
             * @description 听力复用的音频（media.id）；其它题型为 null
             */
            media_id?: number | null;
            /** Ordinal */
            ordinal: number;
            /** Paper Id */
            paper_id: number;
            /** Passages */
            passages?: components["schemas"]["PassageOut"][];
            /** Questions */
            questions?: components["schemas"]["QuestionOut"][];
            /**
             * Time Limit Sec
             * @description 限时（秒）；0 = 不限时
             * @default 0
             */
            time_limit_sec: number;
        };
        /**
         * SentenceMergeIn
         * @description 与相邻句合并。
         */
        SentenceMergeIn: {
            /**
             * Direction
             * @default next
             * @enum {string}
             */
            direction: "next" | "prev";
        };
        /**
         * SentenceOut
         * @description 句子（M2 起才会有数据；听写统计字段由 M3 填充）。
         */
        SentenceOut: {
            /**
             * Attempt Count
             * @default 0
             */
            attempt_count: number;
            /**
             * Best Accuracy
             * @default 0
             */
            best_accuracy: number;
            /** Clip Url */
            clip_url?: string | null;
            /** End Ms */
            end_ms: number;
            /** Id */
            id: number;
            /** Idx */
            idx: number;
            /** Is Edited */
            is_edited: boolean;
            /** Last Accuracy */
            last_accuracy?: number | null;
            /**
             * Last Input
             * @default
             */
            last_input: string;
            /** Marks */
            marks?: number[][];
            /**
             * Mastered
             * @default false
             */
            mastered: boolean;
            /** Start Ms */
            start_ms: number;
            /** Text En */
            text_en: string;
            /** Text Zh */
            text_zh: string;
        };
        /**
         * SentenceSplitIn
         * @description 在 `at_ms` 处把一句拆成两句。
         */
        SentenceSplitIn: {
            /** At Ms */
            at_ms: number;
            /** Text Left */
            text_left?: string | null;
            /** Text Right */
            text_right?: string | null;
        };
        /**
         * SentenceUpdate
         * @description PATCH 单句：仅传需要修改的字段（FR-M6 人工校对）。
         *
         *     ⚠️ `marks` 已废弃：多用户后「易听错」标记是个人数据，改走独立的
         *     `PUT /api/sentences/{id}/marks`（见 `MarksUpdate`）。本字段保留仅为契约兼容，
         *     后端不再据此改动任何标记。
         */
        SentenceUpdate: {
            /** End Ms */
            end_ms?: number | null;
            /** Marks */
            marks?: number[][] | null;
            /** Start Ms */
            start_ms?: number | null;
            /** Text En */
            text_en?: string | null;
            /** Text Zh */
            text_zh?: string | null;
        };
        /**
         * SessionOut
         * @description 会话视图（作答进度 + 汇总）。
         */
        SessionOut: {
            /**
             * Answered
             * @description 已作答条数
             * @default 0
             */
            answered: number;
            /** Draft Kind */
            draft_kind?: string | null;
            /**
             * Graded
             * @description 已判分条数
             * @default 0
             */
            graded: number;
            /** Id */
            id: number;
            /**
             * Max Score
             * @default 0
             */
            max_score: number;
            /** Paper Id */
            paper_id?: number | null;
            /**
             * Pending
             * @description 尚未判分条数（>0 时前端应轮询）
             * @default 0
             */
            pending: number;
            /** Responses */
            responses?: components["schemas"]["ResponseOut"][];
            /** Started At */
            started_at?: string | null;
            /**
             * Status
             * @description in_progress | grading | graded | degraded
             */
            status: string;
            /** Submitted At */
            submitted_at?: string | null;
            /**
             * Time Spent Sec
             * @default 0
             */
            time_spent_sec: number;
            /**
             * Total Score
             * @default 0
             */
            total_score: number;
        };
        /**
         * StatsOut
         * @description 全局学习概览。
         */
        StatsOut: {
            attempts: components["schemas"]["AttemptStatsOut"];
            media: components["schemas"]["MediaStatsOut"];
            /**
             * Notes
             * @default 0
             */
            notes: number;
            /**
             * Sentences
             * @default 0
             */
            sentences: number;
            vocab: components["schemas"]["VocabStatsOut"];
        };
        /** ValidationError */
        ValidationError: {
            /** Context */
            ctx?: Record<string, never>;
            /** Input */
            input?: unknown;
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
        /**
         * VocabCreate
         * @description 加入生词本。
         *
         *     `context` 为出现该词的上下文句子，`media_id` / `sentence_id` 用于溯源。
         */
        VocabCreate: {
            /** Context */
            context?: string | null;
            /** Lemma */
            lemma?: string | null;
            /** Media Id */
            media_id?: number | null;
            /** Phonetic */
            phonetic?: string | null;
            /** Sentence Id */
            sentence_id?: number | null;
            /** Translation */
            translation?: string | null;
            /** Word */
            word: string;
        };
        /** VocabListResponse */
        VocabListResponse: {
            /** Items */
            items: components["schemas"]["VocabOut"][];
            /**
             * Mastered
             * @default 0
             */
            mastered: number;
            /** Total */
            total: number;
        };
        /** VocabOut */
        VocabOut: {
            /** Context */
            context?: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Duplicated
             * @default false
             */
            duplicated: boolean;
            /** Id */
            id: number;
            /** Lemma */
            lemma?: string | null;
            /**
             * Mastered
             * @default false
             */
            mastered: boolean;
            /** Media Id */
            media_id?: number | null;
            /** Media Title */
            media_title?: string | null;
            /** Phonetic */
            phonetic?: string | null;
            /** Sentence Id */
            sentence_id?: number | null;
            /** Translation */
            translation?: string | null;
            /** Word */
            word: string;
        };
        /** VocabStatsOut */
        VocabStatsOut: {
            /**
             * Mastered
             * @default 0
             */
            mastered: number;
            /**
             * Total
             * @default 0
             */
            total: number;
        };
        /**
         * VocabUpdate
         * @description 修改生词（仅传需要改的字段）。
         */
        VocabUpdate: {
            /** Context */
            context?: string | null;
            /** Mastered */
            mastered?: boolean | null;
            /** Translation */
            translation?: string | null;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    list_users_api_admin_users_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdminUserList"];
                };
            };
        };
    };
    create_user_api_admin_users_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AdminUserCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdminUserOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    compare_users_api_admin_users_compare_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdminUserList"];
                };
            };
        };
    };
    delete_user_api_admin_users__user_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_user_api_admin_users__user_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AdminUserUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdminUserOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reset_password_api_admin_users__user_id__reset_password_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AdminPasswordReset"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_user_stats_api_admin_users__user_id__stats_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AdminUserSummary"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_attempt_api_attempts_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AttemptCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AttemptResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    login_api_auth_login_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Credentials"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AuthStatus"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    logout_api_auth_logout_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AuthStatus"];
                };
            };
        };
    };
    change_password_api_auth_password_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PasswordChange"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AuthStatus"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    setup_api_auth_setup_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Credentials"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AuthStatus"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    auth_status_api_auth_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AuthStatus"];
                };
            };
        };
    };
    list_categories_api_categories_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CategoryListResponse"];
                };
            };
        };
    };
    create_category_api_categories_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CategoryCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CategoryOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    reorder_categories_api_categories_order_patch: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CategoryReorder"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CategoryListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_category_api_categories__category_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                category_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_category_api_categories__category_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                category_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CategoryUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CategoryOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    lookup_word_api_dict__word__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                word: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DictResult"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    health_api_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    list_media_api_media_get: {
        parameters: {
            query?: {
                category_id?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MediaListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upload_media_api_media_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_upload_media_api_media_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MediaOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    batch_set_category_api_media_batch_category_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["BatchCategoryRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    import_from_inbox_api_media_import_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ImportRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MediaListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_inbox_api_media_inbox_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InboxResponse"];
                };
            };
        };
    };
    get_media_api_media__media_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                media_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MediaDetailOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_media_api_media__media_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                media_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_media_api_media__media_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                media_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MediaUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MediaOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    clear_clips_api_media__media_id__clips_delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                media_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_clip_api_media__media_id__clips__idx__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                media_id: number;
                idx: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_media_notes_api_media__media_id__notes_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                media_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MediaNotesResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    export_media_notes_api_media__media_id__notes_export_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                media_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    media_progress_api_media__media_id__progress_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                media_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    retranscribe_media_api_media__media_id__retranscribe_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                media_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MediaOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    retry_media_api_media__media_id__retry_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                media_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MediaOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    stream_media_api_media__media_id__stream_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                media_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_note_api_notes__sentence_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                sentence_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NoteOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    save_note_api_notes__sentence_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                sentence_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["NoteUpsert"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NoteOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_papers_api_papers_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PaperListResponse"];
                };
            };
        };
    };
    get_paper_api_papers__paper_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                paper_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PaperDetailOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_session_api_papers__paper_id__sessions_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                paper_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_question_types_api_question_types_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["QuestionTypeListOut"];
                };
            };
        };
    };
    update_sentence_api_sentences__sentence_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                sentence_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SentenceUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MediaDetailOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_attempts_api_sentences__sentence_id__attempts_get: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: never;
            path: {
                sentence_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AttemptListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_marks_api_sentences__sentence_id__marks_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                sentence_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["MarksUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    merge_sentence_api_sentences__sentence_id__merge_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                sentence_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SentenceMergeIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MediaDetailOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    retranslate_sentence_api_sentences__sentence_id__retranslate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                sentence_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MediaDetailOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    split_sentence_api_sentences__sentence_id__split_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                sentence_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SentenceSplitIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MediaDetailOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_report_api_sessions__session_id__report_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReportOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    patch_responses_api_sessions__session_id__responses_patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ResponsesPatch"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    submit_session_api_sessions__session_id__submit_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_stats_api_stats_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StatsOut"];
                };
            };
        };
    };
    get_overview_api_stats_overview_get: {
        parameters: {
            query?: {
                days?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OverviewOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_vocab_api_vocab_get: {
        parameters: {
            query?: {
                /** @description 按是否已掌握筛选 */
                mastered?: boolean | null;
                /** @description 按单词 / 释义搜索 */
                q?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VocabListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_vocab_api_vocab_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["VocabCreate"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VocabOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    export_vocab_api_vocab_export_get: {
        parameters: {
            query?: {
                mastered?: boolean | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_vocab_api_vocab__vocab_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                vocab_id: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_vocab_api_vocab__vocab_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                vocab_id: number;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["VocabUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VocabOut"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}
