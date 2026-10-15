# 媒体库分类机制 · 规格卡（site-spec）

> 作者：文构间（需求架构师 / requirement-architect）
> 类型：**增量功能规格**（不是新建站）
> 适用对象：据此写代码的前端 / 后端工程师。**第五节的接口契约是全队唯一施工依据，字段名一次定死，不许任何一方改。**
> 状态：接口契约已冻结，无「待定」项。

---

## 1. 设计目标与范围

### 一句话目标
给 FayeLong 的媒体库增加**单层分类**能力：用户可在站内创建/重命名/删除/排序分类，把素材逐个或批量归入某一个分类，并按分类（含「未分类」）筛选浏览；上传与收件箱导入时可直接指定分类。

### 明确做什么
- 单层、互斥：每个素材**至多属于一个**分类（`category_id`）。
- 站内管理：分类的增/改/删与素材归类，**全部在应用页面内完成**。
- 四项管理能力：① 分类筛选浏览（含「未分类」入口）② 批量移动 ③ 分类增删改（删除后素材回落「未分类」）④ 计数与排序（显示素材数、支持手动排序）。
- 按类导入：上传 / 从收件箱导入时可指定分类。

### 明确不做什么（本轮排除）
- **不做多层分类**（无父子、无嵌套）。
- **不做多标签**（一个素材只能有一个分类，不是 N 个）。
- **不做磁盘目录联动**（分类是纯逻辑归属，`data/media/library/<id>/` 物理布局不变；不读磁盘子目录自动归类）。
- **不做分类颜色 / 图标 / 描述**（见 §2 color 论证，列为 P2）。
- **不改动** `media.status` 状态机与转码/识别/翻译/切片流程。

---

## 2. 数据模型

### 2.1 新增独立表 `categories`

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY，自增 | 分类主键 |
| `name` | VARCHAR(32) | NOT NULL，**唯一**，`index` | 分类名。入库前 `.strip()`；长度按**字符**计，1–32 |
| `sort_order` | INTEGER | NOT NULL，DEFAULT 0，`index` | 手动排序权重，升序显示；新建 = `COALESCE(MAX(sort_order), -1) + 1` |
| `created_at` | DATETIME | NOT NULL，`server_default=now()` | 创建时间 |

ORM（`backend/app/models/entities.py`）：

```python
class Category(Base):
    """媒体库分类（单层，互斥）。"""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

**约束细节**

- **名称唯一性**：DB 层 `UNIQUE(name)` 兜底（SQLite 默认**大小写敏感**）。应用层在创建/重命名时先 `strip()`，再用 `func.lower(Category.name) == name.lower()` 判重 → 命中返回 **409**。即 `BBC` 与 `bbc` 视为同名冲突，避免同一分类被拆成两条。
- **空名**：`strip()` 后为空 → **400**。不做「未命名」兜底（分类名必须用户自己有意义）。
- **超长**：`strip()` 后 > 32 字符 → **400**。Pydantic 层用 `max_length=32` 先拦一次，业务层再 trim 后校验一次（防「32 个空格包 1 个字」绕过）。
- **`sort_order` 并发与空表**：个人单用户场景，不做乐观锁；新建取 `COALESCE(MAX(sort_order), -1) + 1`，排序提交整份顺序。
  - **必须用 `COALESCE(..., -1)`**：空表时 `MAX(sort_order)` 返回 `NULL`，直接 `MAX + 1` 仍是 `NULL`，会让首个分类的 `sort_order` 落空。用 `-1` 兜底 → 首个分类得 **0**，之后 1、2、3… 递增。

**为什么用独立表，而不是 `media.category` 字符串列？**

1. **重命名一次到位**：改名 = 改 1 行；字符串列要 `UPDATE media SET category=新`，还可能与旧值不一致。
2. **删除语义天然**：删除分类要「旗下素材回落未分类」+ 返回受影响数量，FK + `IS NULL` 一步搞定；字符串列要么全表扫改、要么留脏字符串。
3. **计数/排序有落点**：`GROUP BY category_id` 走索引；`sort_order` 属于分类本身，不必在每个素材行重复存储。
4. **防碎片化**：`BBC` / `bbc` / `BBC ` 不会因手输差异被拆成 3 个假分类。
5. 代价：多一张表和一次 JOIN —— 对单用户 SQLite 可忽略。

### 2.2 `media` 新增列 `category_id`

| 项 | 规定 |
|---|---|
| 类型 | INTEGER |
| 可空性 | **nullable=True**（`NULL` = 未分类） |
| 外键 | `ForeignKey("categories.id", ondelete="SET NULL")` —— **不是 CASCADE** |
| 索引 | 需要（`index=True` + 老库显式建索引，见 §2.4） |

ORM 追加到 `Media`：

```python
category_id: Mapped[int | None] = mapped_column(
    ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
)
```

**为什么 `ON DELETE SET NULL` 而不是 `CASCADE`**：分类只是素材的一个「标签位」，删除分类**绝不能连带删除素材**（素材、句子、笔记、听写记录都是学习资产）。`SET NULL` 正好把素材退回「未分类」。`db.py` 已 `PRAGMA foreign_keys=ON`，FK 真实生效。

> **实现要求（重要）**：删除分类的端点**必须显式**先 `UPDATE media SET category_id=NULL WHERE category_id=?`，再删分类行。不依赖 DB 级联兜底 —— 这样即使某条连接未开 FK，语义也正确；DB 级 `SET NULL` 只作为第二道防线。

**登记进 `_ADDED_COLUMNS` 的 DDL 字符串**（`backend/app/db.py`）：

```python
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "sentences": {"marks": "TEXT DEFAULT ''"},
    # 新增：老库就地升级时补列（可空、默认 NULL → SQLite 允许 ALTER 带 REFERENCES）
    "media": {
        "category_id": "INTEGER REFERENCES categories(id) ON DELETE SET NULL",
    },
}
```

**为什么这条 `ALTER TABLE ... ADD COLUMN` 在 SQLite 上合法**（依据）：SQLite 对 `ADD COLUMN` 有明确限制 —— ① 不得含 `UNIQUE` / `PRIMARY KEY`；② 若声明 `NOT NULL`，必须同时给出非空默认值；③ **启用外键时，带 `REFERENCES` 的新列其默认值必须为 `NULL`**。本列是 `nullable=True` 且**不设 DEFAULT**（隐式默认 `NULL`），三条限制全部满足，故老库可直接 `ALTER` 加列，无需重建表（无需 `PRAGMA legacy_alter_table` 之类变通）。

**索引补齐**（老库只跑 `ALTER ADD COLUMN`，不会自动建索引，需显式幂等建索引）：

```python
_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_media_category_id ON media(category_id)",
)
```

在 `init_db()` 里于 `_ensure_columns()` 之后执行（或并入 `_ensure_columns()` 尾部），用 `conn.exec_driver_sql(...)` 逐条执行。`IF NOT EXISTS` 保证新库（`create_all` 已建同名索引）与老库都不报错。

### 2.3 「未分类」的表示法 —— `category_id IS NULL`

**结论：不建名为「未分类」的真实记录，一律用 `category_id IS NULL` 表达。**

理由：

1. **真实记录可被误删/误改**：用户重命名「未分类」或删除它，会让「未分类」这个概念消失或出现重复，语义崩塌。
2. **计数干净**：`uncategorized_count = COUNT(*) WHERE category_id IS NULL`，一条聚合；若用真实记录则它也是普通行，还得分清真假。
3. **回落语义天然**：删分类 → `SET NULL` 即回落，无需 `ON DELETE SET DEFAULT` + 保护「未分类」行不可删的额外守卫。
4. **零初始化**：新库 / 老库都不需要 seed 一条「未分类」，所有既有素材自动就是未分类。
5. **归类操作确定**：移到未分类 = 传 `category_id=null`，一个明确入参。

### 2.4 迁移路径与幂等性

| 场景 | 行为 |
|---|---|
| **全新库** | `Base.metadata.create_all` 建 `categories` 表、`media.category_id` 列、两处索引；`_ensure_columns` 与索引语句均为 no-op |
| **老库（就地更新：只换程序不碰 `data/`）** | `create_all` 跳过已存在的 `media`，但**新建** `categories`；`_ensure_columns` 对 `media` 执行 `ALTER TABLE media ADD COLUMN category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL`；随后 `CREATE INDEX IF NOT EXISTS` |
| **幂等性** | 补列前先 `PRAGMA table_info(media)` 判断列是否存在（沿用现有逻辑）；建索引用 `IF NOT EXISTS`。重复启动无副作用 |
| **既有素材默认归属** | 全部为 `category_id = NULL` → 出现在「未分类」。**不 backfill、不改任何老数据** |

> 执行顺序保证：`categories` 由 `create_all` 先建好，`ALTER` 的 `REFERENCES categories(id)` 目标已存在，不会报「引用表不存在」。

### 2.5 前端类型同步（`frontend/src/api/client.ts`）

```ts
// MediaItem 追加（仅新增可选字段，向后兼容）
category_id: number | null

// 新增
export interface CategoryItem {
  id: number
  name: string
  sort_order: number
  media_count: number
  created_at: string
}
export interface CategoryListResponse {
  items: CategoryItem[]
  total: number
  uncategorized_count: number
}
```

---

## 3. 接口契约（字段名已冻结）

### 3.1 分类 CRUD（新路由，`prefix="/api/categories"`）

| 方法 | 路径 | 入参（字段:类型:必填） | 出参 | 错误码 |
|---|---|---|---|---|
| GET | `/api/categories` | 无 | `CategoryListResponse` = `{items: CategoryOut[], total: number, uncategorized_count: number}`，`items` 按 `sort_order ASC, id ASC` | 500 |
| POST | `/api/categories` | `name: string:必填` | `201` + `CategoryOut` | 400 空名/超长 / 409 同名 / 500 |
| PATCH | `/api/categories/{category_id}` | `name: string:必填` | `CategoryOut` | 400 空名/超长 / 404 分类不存在 / 409 同名 / 500 |
| DELETE | `/api/categories/{category_id}` | 无 | `200` + `{id: number, name: string, released: number}`，`released` = 被移入「未分类」的素材数 | 404 分类不存在 / 500 |
| PATCH | `/api/categories/order` | `ids: number[]:必填` | `{items: CategoryOut[], total: number, uncategorized_count: number}` | 400 ids 集合与现有分类不符（缺/多/重复）/ 500 |

**`CategoryOut` 字段（精确）**

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | number | 分类 id |
| `name` | string | 分类名 |
| `sort_order` | number | 排序权重 |
| `media_count` | number | 该分类下素材数（`COUNT(media.id) WHERE category_id=id`） |
| `created_at` | string | ISO 8601 时间字符串 |

**语义补充**

- `GET /api/categories` 的 `items` **只含真实分类**；未分类不入 `items`，其数量单独放 `uncategorized_count`。
- `PATCH /api/categories/{category_id}` 本轮只允许改 `name`（`color` 等 P2 再加字段）。
- `PATCH /api/categories/order`：`ids` 必须是**当前全部分类 id 的完整有序集合**；服务端按数组下标重写 `sort_order`（0 基）。校验：不得有未知 id、不得缺项、不得重复，否则 400。
- `DELETE`：先 `UPDATE media SET category_id=NULL WHERE category_id={id}`（统计受影响行数→`released`），再删分类行；**不删任何素材**。
- **`/order` 与 `/{category_id}` 不冲突的前提（必须遵守）**：`PATCH /api/categories/order` 与 `PATCH /api/categories/{category_id}` 能共存，原理与既有先例一致 —— `media.py` 里 `GET /inbox`（字面量）与 `GET /{media_id}` 共存且工作正常，是因为 Starlette 的 `IntegerConvertor.regex` 为 `[0-9]+`，字面量 `inbox` / `order` 不匹配数字正则，于是自动回退到后一条路由。
  - **因此 `{category_id}` 路径参数必须标注为 `int`**（`def update_category(category_id: int, ...)`），从而生成 `[0-9]+` 正则；
  - **若误写成 `str`**，其正则 `[^/]+` 会**吞掉** `order`，导致 `/order` 被当成 id 处理 —— 这是本节唯一的实现陷阱，务必按 `int` 声明。
  - **防御性措施**：即使有了 int 约束，仍**建议把 `/order` 声明在 `/{id}` 之前注册**（顺序双保险），成本为零。
- **路由注册**：在 `backend/app/main.py` 的 `app.include_router(...)` 列表中新增 `categories`，位置在 SPA 兜底路由之前（与现有 router 一起，天然满足）。

### 3.2 素材归类

**（a）单个改分类 —— 复用 `PATCH /api/media/{id}`，不新开端点。**

理由：语义同类（改素材属性），复用可少一个前端封装与一个 404 路径；且 `MediaOut` 已带全部字段，改完直接返回即可。

`MediaUpdate` 扩展为：

```python
class MediaUpdate(BaseModel):
    title: str | None = None
    category_id: int | None = None   # 显式传 null = 移到「未分类」
```

**关键：区分「未传」与「传了 null」**（`null` 必须能表达「移到未分类」）：

```python
if "category_id" in payload.model_fields_set:   # Pydantic v2
    if payload.category_id is not None and db.get(Category, payload.category_id) is None:
        raise HTTPException(status_code=404, detail="分类不存在")
    media.category_id = payload.category_id     # 允许 None
```

| 方法 | 路径 | 入参 | 出参 | 错误码 |
|---|---|---|---|---|
| PATCH | `/api/media/{media_id}` | `title?: string`, `category_id?: number\|null`（二者至少传一个） | `MediaOut`（含新字段 `category_id`） | 404 媒体不存在 / 404 分类不存在 / 500 |

> 既有 `title` 行为保持不变（`if payload.title is not None` 那套逻辑不动），仅新增 `category_id` 分支。

> **分类名的显示（零后端改动）**：素材行要显示所属分类名 badge，但**分类名由前端本地映射** —— 用已缓存的 `['categories']` 查询结果建 `id → name` 映射，`MediaOut` **不新增 `category_name` 字段**、后端 list **不做 JOIN**（避免每次列表多一次联接；个人站分类少，前端映射成本为零）。未分类（`category_id === null`）显示灰字「未分类」。

**（b）批量移动 —— 新端点。**

| 方法 | 路径 | 入参（字段:类型:必填） | 出参 | 错误码 |
|---|---|---|---|---|
| POST | `/api/media/batch-category` | `ids: number[]:必填(非空)`, `category_id: number\|null:必填(允许 null)` | `{updated: number, category_id: number\|null, missing: number[]}` | 400 ids 为空/非数组 / 404 category_id 指向的分类不存在 / 500 |

语义：

- `category_id = null` → 批量移到「未分类」。
- `updated` = 实际更新成功的素材数；`missing` = `ids` 中不存在的媒体 id（**不报错**，忽略并回报，便于前端提示「N 个已失效」）。
- 实现：`UPDATE media SET category_id=? WHERE id IN (...)` 一条语句。
- **路由冲突检查**：该路径为 `POST /api/media/batch-category`（单段），现有 `/{media_id}` 相关路由里**没有 POST 单段**（`GET /{media_id}` 是 GET，`POST /{media_id}/retry` 是两段），故无冲突。放在 `media.py` 中与 `/import` 相邻即可。

**（c）导入时指定分类**

| 方法 | 路径 | 入参 | 出参 | 错误码 |
|---|---|---|---|---|
| POST | `/api/media/import` | `files: string[]\|null:选填`, **`category_id: number\|null:选填(默认 null)`** | `201` + `MediaListResponse` | 404 category_id 指向的分类不存在 / 500 |
| POST | `/api/media` | multipart：`file`(必填) + **`category_id`(选填, int)** | `201` + `MediaOut` | 400 文件名/类型不符 / 404 分类不存在 / 500 |

- `import`（JSON body）：`ImportRequest` 增字段 `category_id: int | None = None`；所有本次导入的素材统一归入该分类，默认「未分类」。
- `upload`（multipart）：函数签名加 `category_id: int | None = Form(None)`，透传给 `_register(...)` 写入。前端 `uploadMedia` 组装 `FormData` 时，当选择了分类则 `form.append('category_id', String(id))`。
- 两者在写库前都要校验 `category_id` 存在（非 null 时），否则 404。

### 3.3 列表过滤

| 方法 | 路径 | 入参 | 出参 | 错误码 |
|---|---|---|---|---|
| GET | `/api/media` | `category_id: string:选填`（缺省=全部；整数串=某分类；字面量 `none`=未分类） | `MediaListResponse`（`items`/`total` 均按筛选后计） | 400 category_id 非法（非整数且非 `none`）/ 500 |

- **「未分类」的表达**：`GET /api/media?category_id=none`（字符串字面量 `none`）。
  - 不用 `?category_id=null`：URL 里 `null` 是普通字符串，语义含糊易被误当 id；也不新增第二个参数（避免组合爆炸）。
- `?category_id=12` → `WHERE media.category_id = 12`。
- 缺省 → 不加条件（保持既有「全部」行为）。
- **契约兼容性**：仅新增**可选**查询参数，`MediaListResponse` 形状不变（`items`/`total`），`MediaOut` 仅**追加** `category_id`。老前端不传参时行为与今天完全一致。
- **分类名不上后端**：列表响应**不含**分类名，素材行显示的 `id → name` 由前端用 `['categories']` 结果映射（同 §3.2）。后端只管 `category_id`，不 JOIN `categories`。
- **与既有本地搜索 / 排序叠加**：
  - 分类维度走**服务端**（`category_id` 作为 react-query key 的一部分：`['media', categoryId ?? 'all']`），保证分页/计数一致；
  - 关键字搜索（`title` / `original_name`）与排序（recent / title / duration）**继续在前端对返回子集做**，逻辑不改。
  - 即：`服务端按分类筛 → 前端在结果内搜关键字 + 排序`。单用户本地规模下无性能问题，且改动面最小。
  - 处理中轮询逻辑不变：仍判断「当前 key 对应 `items` 中是否有处理中状态」，命中则 1.5s 刷新。

### 3.4 统计 `/api/stats` 是否需要分类维度

**结论：不改 `/api/stats`。**（这是决定，不是「可选」）

理由：

1. 分类维度的计数**已由 `GET /api/categories` 完整提供**（每个 `media_count` + `uncategorized_count`），侧栏/chips 所需数据一个请求就够，无需再塞进 `/stats`。
2. `/api/stats` 是**全局学习概览**（媒体/句子/生词/笔记/听写），被头部与多页 15s 轮询复用，扩展其响应体会影响多个调用方、增加回归面，收益却为零。
3. 分类是「媒体库管理」维度，与「学习进度」正交；混入会让 `StatsOut` 职责不清。

因此 `StatsOut` / `MediaStatsOut` **保持原样**，向后兼容。

---

## 4. 交互方案

**整体形态：横向分类 chips 条，不引入独立侧栏。**
理由：`Layout` 是「header / main(单列纵向滚动) / PlayerBar」三段式，加侧栏会与移动端单列布局和触摸约定打架；分类数量在个人站可控（一般 < 15），chips 足够。

### 4.1 分类浏览区（列表卡片头部）

```
┌─ 已导入素材  共 37 个            [搜索框] [排序▾] ┐
│ [全部 37] [未分类 5] [BBC 12] [VOA 20] [+ 管理分类] │   ← 桌面：换行
└───────────────────────────────────────────────┘
移动端：chips 单行横向滚动（overflow-x-auto，chip shrink-0）
```

- chip 内容：`名称 + 计数`；「全部」「未分类」为固定入口，永远显示。
- 选中态：深色底（`bg-slate-900 text-white`），未选：白底描边。
- 计数 0 的分类**仍显示**（便于作为移动目标），但可置灰。
- **计数语义要能区分（避免误读）**：chips 上的计数是**分类子集计数**（`GET /api/categories` 的 `media_count` / `uncategorized_count`），随当前分类口径变化；而顶部 4 个 `StatCard` 是**全局计数**（`/api/stats`，本次不改）。请在界面上保持文案口径可辨 —— 例如 StatCard 仍标「素材 · 共 N 个」（全局），chips 标「某分类 N」。二者不要用同一句文案，以免用户以为「筛选后总数变了」。
- 素材行显示所属**分类名 badge**（由 `['categories']` 前端映射，未分类显示灰字「未分类」），详见 §3.2 / §3.3。
- 右侧「管理分类」按钮进入 §4.3 面板。
- 计数来源：`GET /api/categories`（react-query key `['categories']`）。任何会改变归属或数量的操作后 `invalidateQueries(['categories'])` 与 `['media', ...]`。

### 4.2 批量移动

**进入多选**：

- 列表头部加「批量管理」按钮（P0）。点击进入多选态；**不依赖长按/右键**（移动端不可靠）。
- 进入后每行左侧出现 checkbox（点击热区 ≥ 32px）。
- 顶部出现操作条：`已选 N 项   [移动到分类 ▾]   [取消]`。

```
┌ 已选 3 项   [移动到分类 ▾]  [取消] ┐
│ ☐ 素材 A                          │
│ ☑ 素材 B                          │
│ ☑ 素材 C                          │
```

**选择目标分类**：

- 桌面：下拉菜单列出「未分类 + 各分类」。
- 移动端：**底部弹层（bottom sheet）**列出同样选项，每项点击热区 ≥ 32px。
- 未选任何素材时「移动到分类」按钮禁用。

**结果反馈**：复用现有 `notice` 条 →「已移动 N 个素材到「XXX」」（含 `missing` 时追加「，M 个已失效被跳过」）；退出多选态；失效 `['media', ...]` 与 `['categories']`。

### 4.3 分类增删改 + 排序（「管理分类」面板）

弹层/面板内列出分类，每行：

```
┌ 管理分类 ────────────────────────────┐
│ [输入新分类名........] [新建]          │
│ ↑ ↓  BBC        12 个素材   [✎] [🗑]   │
│ ↑ ↓  VOA        20 个素材   [✎] [🗑]   │
└──────────────────────────────────────┘
```

- **新建**：顶部输入框 + 「新建」按钮 / 回车提交；空名或超 32 字禁用提交并内联提示。
- **重命名**：点铅笔→行内输入（复用 `MediaRow` 的重命名交互范式：Enter 提交、Esc 取消）。撞名（后端 409）→ 行内红字「已存在同名分类」，**保留已输入内容**不清空。
- **删除**：单次 `confirm`，文案**明示不删素材**：
  > 删除分类「XXX」后，其中的 12 个素材会移入「未分类」，**不会被删除**。确定删除？
  - **不设二级确认**：该操作破坏性低（不删素材/笔记），与「删除媒体」的重确认区分开，避免无谓摩擦。
- **排序**：每行 `↑ / ↓` 按钮（32px，P0 方案）。点击后本地重排并提交整份顺序到 `PATCH /api/categories/order`。
  - **移动端可用性替代**：不引入拖拽库（新增依赖 + 触摸拖拽易误触）；↑↓ 按钮在桌面与移动端表现一致。
  - 拖拽排序列为 **P2** 增强（可选，用现有栈自行实现，不引付费/第三方依赖）。

### 4.4 按类导入

- **上传**：在拖拽上传区旁放一个「导入到分类」`<select>`（默认「未分类」）。因为上传是逐文件循环，**本轮所选文件统一使用同一分类**。移动端用原生 `<select>`（触摸友好、零额外依赖）。
- **收件箱导入面板**：在「导入选中 / 全部导入」按钮左侧放同样的分类 `<select>`（默认「未分类」），导入时把 `category_id` 带入 `POST /api/media/import`。
- 导入完成 `notice` 文案追加目标分类名，如「已导入 3 个素材到「BBC」，正在后台转码」。

### 4.5 与移动端既有约束的一致性

- 复用三段式布局，**禁止** `calc(100vh - Npx)` 魔法数字。
- 所有新增可点元素触摸目标 **≥ 32px**，不按屏宽分档。
- chips 条、操作条在窄屏下横向滚动或换行，不溢出。

---

## 5. 兼容与回归风险（本次改动「不能破坏」清单）

| # | 不能破坏的既有行为 | 为什么会受影响 | 缓解措施 |
|---|---|---|---|
| 1 | `GET /api/media` 契约（`items`/`total`、`MediaOut` 字段名与类型） | 新增筛选参数 / 新字段 | 参数为**可选**、`MediaOut` 仅**追加** `category_id`；不改既有字段；契约冻结 |
| 2 | 处理中列表的 1.5s 轮询 | query key 变为 `['media', categoryId]` | 轮询判定仍基于「当前 key 的 `items` 是否含处理中状态」，逻辑不变 |
| 3 | SSE `/api/media/{id}/progress` 与轮询兜底 | 理论上若动到 media 序列化 | 不改该端点；SSE 载荷字段不动 |
| 4 | 学习页 `/study/:id`、句子编辑、生词本、笔记导出 | 与分类无耦合 | 不改相关表与端点；`serialize()` 只加字段 |
| 5 | 删除媒体的级联（sentences/notes/attempts） | 新增 FK 可能被误设成 CASCADE | `media.category_id` 用 SET NULL；删除媒体逻辑不动 |
| 6 | 老库「就地更新」启动不崩 | 漏登记补列 → 缺列报错 | `category_id` 已登记 `_ADDED_COLUMNS`；索引 `IF NOT EXISTS`。**老库冒烟测试（三条全过才算合格）**：① `SELECT category_id FROM media LIMIT 1` 不报缺列；② `PRAGMA foreign_key_list(media)` 能看到指向 `categories(id)` 且 `on_delete=SET NULL` 的外键；③ 实跑一遍「建分类 → 归类 → 删分类 → 素材回到未分类」，确认回落语义生效 |
| 7 | SQLite 外键语义 | 删分类若仅依赖 DB 级联，在未开 FK 的连接上失效 | 端点内**显式** `UPDATE media SET category_id=NULL` 再删分类；DB `SET NULL` 作二道防线 |
| 8 | 云端已部署版本可用 | 前端引用未部署的后端端点会 404 | **后端先上**（新增端点向后兼容），前端后上；同批发布，避免中间态 |
| 9 | 移动端布局与触摸约定 | 新增 UI 元素 | 遵守三段式 + 32px 触摸目标 + 横向滚动，见 §4.5 |
| 10 | `/api/stats` 15s 轮询 | 若扩展响应体 | 决定不改 `StatsOut`（§3.4） |

---

## 6. 需要用户拍板的决策 / 未决问题

1. **分类名长度上限与判重规则**：采用「1–32 字符、忽略大小写判重（`BBC` = `bbc`）」。若你更希望区分大小写或放宽到 64 字符，请说明。
2. **排序交互方案**：P0 采用「↑/↓ 按钮」而非拖拽（避免新依赖 + 移动端误触）；拖拽列 P2。若你坚持首发就要拖动排序，请确认可接受引入拖拽依赖或自实现成本。
3. **导入时分类选择的记忆**：本轮默认不记忆（每次默认「未分类」）。若希望「记住上次选择」，属 P2，可上线后加。

以上三条都已有默认结论，**不阻塞开发**；用户不回即按默认执行。

---

## 7. 落地位置与改动清单（文件级，给实现者）

**后端**

- `backend/app/models/entities.py`：新增 `Category`；`Media` 增 `category_id`。
- `backend/app/models/__init__.py`：导出 `Category`。
- `backend/app/db.py`：`_ADDED_COLUMNS` 增 `media.category_id`；新增 `_INDEXES` 并在 `init_db()` 幂等执行。
- `backend/app/schemas/category.py`（新建）：`CategoryOut` / `CategoryListResponse` / `CategoryCreate` / `CategoryUpdate` / `CategoryReorder`。
- `backend/app/schemas/media.py`：`MediaOut` 增 `category_id`；`MediaUpdate` 增 `category_id`；`ImportRequest` 增 `category_id`；新增 `BatchCategoryRequest`。
- `backend/app/api/categories.py`（新建）：§3.1 全部端点。**注意：`{category_id}` 路径参数必须标注 `int`；`/order` 端点声明在 `/{category_id}` 之前**（见 §3.1）。
- `backend/app/api/media.py`：`list_media` 增 `category_id` 查询参数与过滤；`update_media` 增 `category_id` 分支；新增 `POST /batch-category`；`upload_media` 增 `category_id: Form(None)`；`import_from_inbox` 透传 `category_id`；`serialize` 输出 `category_id`。
- `backend/app/main.py`：`include_router(categories.router)`。

**前端**

- `frontend/src/api/client.ts`：`MediaItem` 增 `category_id`；新增 `CategoryItem` / `CategoryListResponse` 类型与 `listCategories` / `createCategory` / `updateCategory` / `deleteCategory` / `reorderCategories` / `batchMoveCategory`；`updateMedia` 支持传 `category_id`；`importFromInbox` / `uploadMedia` 支持传 `category_id`；`listMedia(categoryId?)`。
- `frontend/src/pages/MediaLibraryPage.tsx`：分类 chips 条、批量管理态、管理分类面板、上传/导入分类选择器；素材行加**分类名 badge**（用 `['categories']` 结果做 `id → name` 本地映射，未分类显示灰字「未分类」）；`refresh()` 追加 `invalidateQueries(['categories'])`。
- 新增小组件文件（如 `frontend/src/components/CategoryChips.tsx` / `CategoryManager.tsx`），复用现有样式与图标。

**不动的部分**：`data/media/library/<id>/` 物理布局、状态机、SSE、学习页、生词本、笔记、句子编辑、`/api/stats`。

---

## 范围建议（砍到哪层能上线）

- **首发必做（P0，缺一不可上线）**：`categories` 表 + `media.category_id` 迁移与补列；分类 CRUD（列表含计数 + 新建 + 重命名 + 删除回落）；单项改分类；批量移动；`GET /api/media?category_id=` 过滤 + 「全部 / 未分类」chips；按类上传 + 按类收件箱导入；↑↓ 手动排序。
- **首发可做（P1）**：分类计数随操作即时刷新动画、移动完成的更友好提示。
- **上线后迭代（P2）**：分类颜色、分类描述、拖拽排序、导入时记忆上次分类。
- **砍到哪层仍能上线**：若时间极紧，砍掉 P1，再砍「按类上传（保留按类 inbox 导入）」与「↑↓ 排序（用默认创建序显示）」仍可上线 —— 核心的「建分类 / 归类 / 筛选」三件事必须在。

## 最大风险（一句话）

**老库「就地更新」时若漏登记 `media.category_id` 补列，会导致缺列崩溃 —— 这是唯一「一改就炸线上」的点，必须做旧库启动冒烟测试。**

## 需要用户拍板的决策

1. 分类名上限 32 字符 + 忽略大小写判重，是否接受？
2. P0 排序用 ↑/↓ 按钮（不做拖拽）是否接受？
3. 导入不记忆上次分类（默认「未分类」）是否接受？
