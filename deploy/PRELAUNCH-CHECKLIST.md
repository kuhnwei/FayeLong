# FayeLong 上线前检查表（实测逐项）

- **访问地址**：http://114.132.173.241/ （实测打开：是）
- **检查时间**：2026-10-14 23:00–23:20 (CST)
- **环境**：腾讯云轻量 `ap-guangzhou / lhins-a0s35jwt`，Ubuntu 24.04.4 LTS，2 vCPU / 2 GB，Python 3.12.3，ffmpeg 6.1.1，Caddy 2.11.4
- **判定口径**：PASS / FAIL / CONCERNS / N-A（N-A 必附理由）

---

## 一、项目专属检查表（主理人指定，8 项）

| # | 检查项 | 结果 | 实测证据 |
|---|---|---|---|
| 1 | `/api/health` 正常 | **PASS** | `{"status":"ok"}`，checks 全 true（database/ffmpeg/ffprobe/asr/asr_model/dict） |
| 1 | `/api/stats` 正常 | **PASS** | 200，`media{total:6,done:6,failed:0}, sentences:121, attempts{total:4}` |
| 2 | 首页与 `/assets/*` 200 | **PASS** | `/` 200(409B)；`/assets/index-5O-uxDGV.js` 200(315,364B)；`/assets/index-wU9FM-Hf.css` 200(24,105B) |
| 2 | SPA 深链回退 | **PASS** | `/learn/deep/link/xyz` → 200 且返回 SPA 外壳 |
| 3 | 词典词形还原 `children/went/better` | **PASS** | children→**child**(exchange)、went→**go**、better→**good**，三例均正确 |
| 4 | 端到端冒烟 | **PASS** | 导入 `_示例-多句听力.wav` → 轮询到 `done`（6 句）→ 每句有 `text_en` 与 `text_zh` → 提交听写：完全正确 100%/判对，截断 92.9%/判错，乱写 0%/判错，历史 total=3 |
| 5 | 2 核转写耗时（small vs base，同一 34.4s 音频） | **PASS** | 见下表；结论：**默认 small**（用户决策，准确率优先） |
| 6 | 内存峰值 / OOM | **PASS** | 转写中进程峰值 RSS **328 MB**（VmHWM 335,680 kB）；系统 available 始终 ≥1.0 GB；`dmesg`/`journalctl -k` 无 OOM、无 Killed process；`fayelong` NRestarts=0 |
| 7 | 公网可达 | **PASS** | `curl http://114.132.173.241/` → 200；资源 TTFB 0.045–0.077s |
| 8 | 服务自启 | **PASS** | `systemctl is-enabled fayelong` → enabled；`caddy` 亦 enabled |

### 转写耗时 / 实时率（2 vCPU · int8 · 同一段 34.4s 音频）

| 模型 | 加载 | 推理 | 合计 | 实时率 RTF | 产出句数 | 内存占用 | 磁盘 |
|---|---|---|---|---|---|---|---|
| **small** | 2.6s | 36.3s | **39.0s** | **1.13×**（慢于实时） | 6 | — | 464 MB |
| **base** | 1.2s | 11.4s | **12.6s** | **0.37×**（快 2.7 倍） | 4 | — | 142 MB |

**结论（默认该用哪个）：small —— 用户决策，准确率优先。** 依据：本工具是「听写」用途，**转写文本即标准答案**，base 的错词会把用户拼写正确的输入误判为错误，故准确率优先于吞吐。代价是慢：small 推理 36.3s（RTF 1.13×），比 base 慢约 3.2 倍、模型大 3.3 倍。
如需吞吐优先（长音频多、可容忍少量识别误差），把 `fayelong.service` 的 `FAYELONG_WHISPER_MODEL` 改为 `base` 后 `systemctl daemon-reload && systemctl restart fayelong` 即切换（模型已在机上，详见 `deploy/README.md` §5.1）。

> 端到端流水线（导入→转码→识别→翻译→切片→done）参考：34.4s 音频用 small 冷跑约 86s；10.4s 音频用 base 热跑约 14s。

---

## 二、通用检查表 A–H

### A. 可访问性
| 项 | 结果 | 说明 |
|---|---|---|
| A1 真实 URL 能打开 | **PASS** | 公网 200，且用 headless Chrome 实际渲染出应用界面 |
| A2 HTTPS 生效，HTTP 301 | **N-A** | 纯 IP 直连、无域名无证书，不涉及 HTTPS |
| A3 www / 非 www 301 | **N-A** | 无域名 |
| A4 控制台无报错 | **PASS** | 1280 / 834 / 390 三档渲染，页面 JS 报错 **0**（Chrome 仅有与本机无关的 dbus 噪音） |
| A5 页面 200、无 404/500 | **PASS** | `/`、`/assets/*` 均 200；`/api/*` 未知路径正确返回 404 |

### B. 多端渲染
| 项 | 结果 | 说明 |
|---|---|---|
| B1 桌面 ≥1280 | **PASS** | headless Chrome 1280×1000 渲染成功，DOM 22,581B，H1=1 |
| B2 平板 640–1023 | **PASS** | 834×1200 渲染成功，H1=1 |
| B3 手机 <640，无横向滚动 | **CONCERNS** | 390×844 渲染成功、内容完整、H1=1；**但未做像素级横向溢出测量**（受本机受限，无法驱动像素级校验） |
| B4 移动端导航交互 | **CONCERNS** | 未做交互验证（需人工在真机点开/关闭） |
| B5 点击区域 ≥44px | **CONCERNS** | 未测量 |
| B6 两个桌面浏览器一致 | **CONCERNS** | 仅 Chromium 内核验证 |

### C. 内容与一致性
| 项 | 结果 | 说明 |
|---|---|---|
| C1 文案与 content-plan.md 一致 | **N-A** | 本项目为应用型站点，未交付 content-plan.md |
| C2 无占位文案 | **PASS** | 渲染 DOM 无 lorem / 待替换 / 示例文字 |
| C3 图片素材无裂图 | **N-A** | 页面无 `<img>` 元素 |
| C4 联系方式 / 备案号 | **N-A** | 无域名、无备案主体信息 |
| C5 错别字 / 术语统一 | **PASS** | 抽查首页与学习页文案正常 |

### D. 功能
| 项 | 结果 | 说明 |
|---|---|---|
| D1 表单实测提交并收到 | **PASS** | 听写提交落库，`GET /api/sentences/{id}/attempts` total=3；导入/翻译/切片全链路跑通 |
| D2 失败态可读 | **PASS** | 全局异常处理返回中文 `detail`；404/409 均为中文提示 |
| D3 服务端也有校验 | **PASS** | 听写判定在服务端 `services/dictation.py`（服务端为唯一判定源） |
| D4 站内链接无死链 | **PASS** | 单页应用；`/assets/*` 全 200 |
| D5 登录 / 支付流程 | **N-A** | 无登录（用户已明确选择公开免登录）、无支付 |
| D6 404 页 | **CONCERNS** | 未知路径落入 SPA 回退显示应用主界面，**无独立 404 视图** |

### E. SEO
| 项 | 结果 | 说明 |
|---|---|---|
| E1 逐页 TDK | **CONCERNS** | `<title>FayeLong 英语学习</title>` 唯一，但**无 meta description** |
| E2 唯一 H1、层级 | **PASS** | 渲染后 H1=1 |
| E3 图片 alt | **N-A** | 无图片 |
| E4 sitemap.xml | **CONCERNS** | 不存在；`/sitemap.xml` 被 SPA 回退成 200 + HTML |
| E5 robots.txt | **CONCERNS** | 不存在；`/robots.txt` 同为 200 + HTML |
| E6 canonical | **CONCERNS** | 无 |
| E7 结构化数据 | **N-A** | 应用型站点，无内容/商品/文章页 |
| E8 分享卡 og/twitter | **CONCERNS** | 无 og/twitter 标签 |

> **E 项定性说明**：本站 IP 直连、无域名、无收录意图（大陆主机绑域名还需 ICP 备案），E4–E8 对当前形态**不构成阻塞**；E1 缺 description 属可低成本修复项。若后续要正式对外经营/收录，需接域名 + 备案 + 补齐 TDK/og/sitemap/robots/canonical。

### F. 性能
| 项 | 结果 | 说明 |
|---|---|---|
| F1 首屏可交互 <2.5s | **PASS** | 公网实测 TTFB 0.045–0.077s，首屏三资源合计传输 ~0.13s |
| F2 LCP<2.5s / CLS<0.1 | **CONCERNS** | 未跑 Lighthouse；以 TTFB 与资源量佐证，未做渲染级指标测量 |
| F3 首页资源 <1.5MB | **PASS** | gzip 后 409 + 98,107 + 5,283 = **103.8 KB**（未压缩 339.9 KB） |
| F4 图片现代格式 / 懒加载 | **N-A** | 无图片 |
| F5 静态资源缓存头 | **PASS** | 已由 Caddy 设 `Cache-Control: public, max-age=31536000, immutable` |
| F6 优化前后对比数字 | **PASS** | 见下 |

**优化前后对比（实测）**
| 资源 | 优化前 | 优化后 | 变化 |
|---|---|---|---|
| JS (`index-5O-uxDGV.js`) | 315,364 B | 98,107 B（gzip） | **−69%** |
| CSS (`index-wU9FM-Hf.css`) | 24,105 B | 5,283 B（gzip） | **−78%** |
| `/assets/*` 缓存 | 无 Cache-Control | `immutable, max-age=1y` | 复访零请求 |
| `Server` 响应头 | `Caddy` | 已移除 | 减少指纹 |

### G. 安全与合规
| 项 | 结果 | 说明 |
|---|---|---|
| G1 无硬编码密钥 | **PASS** | 源码 grep 无 api_key/secret/password；无 `.env` 入库 |
| G2 环境变量齐全 | **PASS** | 仅非机密变量，经 systemd `Environment=` 注入 |
| G3 隐私政策 | **N-A** | 不收集用户数据（无登录、无埋点、无 Cookie） |
| G4 备案号 | **N-A** | 无域名、IP 直连 |
| G5 第三方资源可信/降级 | **PASS** | 无外部 CDN/字体；仅服务端调用有道/MyMemory 免密钥翻译，且带引擎链回退 |

### H. 交付物
| 项 | 结果 | 说明 |
|---|---|---|
| H1 代码仓 + README | **PASS** | 本地仓库；`deploy/README.md`（按要求未 push/commit） |
| H2 部署配置与构建命令 | **PASS** | `deploy/README.md` 第四节 |
| H3 环境变量清单 | **PASS** | `deploy/README.md` 第五节（仅变量名与用途） |
| H4 回滚方式 | **PASS** | `update.sh` 结尾打印回滚命令；`.backup/` 保留历史 |
| H5 养护说明 | **PASS** | `deploy/README.md` 第十节 |
| H6 未解决项 | **PASS** | 见下 |

---

## 三、未解决项与已知风险

1. **B3/B4/B5/B6 未做像素级与交互级验证**（横向溢出、移动端导航交互、点击区尺寸、跨浏览器一致性）。
   影响：移动端体验存在未证实风险。建议：上线后用真机各点一遍；或接 Playwright 做一次视觉回归。
2. **无独立 404 视图（D6）**：未知路径直接渲染应用主界面。影响轻微（用户不会看到空白），但语义上不是标准 404。
3. **SEO 技术项缺失（E1/E4/E5/E6/E8）**：无 meta description、无 robots/sitemap/canonical/og。当前 IP 直连形态下不阻塞；若要做对外经营/收录，需接域名 + 备案 + 前端补标签。
4. **软 404**：`/robots.txt`、`/sitemap.xml`、`/favicon.ico` 等被 SPA 回退成 `200 + HTML`。建议后端为这些固定路径返回真实文件或 404。
5. **单 worker 串行**：转写期间其他请求排队（2 核 2GB 的取舍）。默认已用 base 缩短阻塞时间；如需并发，需升配或引入任务队列。
6. **未开自动续费**：实例 2026-11-14 到期，需用户手动续费，否则站点下线。
7. **无 HTTPS、无域名**：浏览器可能对“不安全”提示；如需正式对外，建议接域名 + Caddy 自动 HTTPS。

---

## 四、判定

**可上线（附已知问题）** —— 阻塞项：无。

- 项目专属 8 项检查：**全部 PASS**。
- 通用 A/D 两类：无 FAIL（仅 B 类若干 CONCERNS、D6 一处 CONCERNS）。
- E 类：因“IP 直连、无域名、无收录意图”判为不适用/建议改进，不阻塞；其中 E1 缺 description 属可低成本修复。
- F 类：F1/F3/F5/F6 PASS，F2 未跑 Lighthouse（CONCERNS）。

> 若主理人/用户要求「SEO 面向」或「移动端像素级验收」，则需退回 `frontend-engineer` 补齐后再上线。
