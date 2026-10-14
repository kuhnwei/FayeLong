# FayeLong 上线报告

## 访问地址
**http://114.132.173.241/** （已实测打开：是 —— 公网 HTTP 200，并用 headless Chrome 实际渲染出应用界面）

## 部署信息
| 项 | 值 |
|---|---|
| 平台 | 腾讯云轻量应用服务器 `ap-guangzhou / lhins-a0s35jwt` |
| 系统 | Ubuntu 24.04.4 LTS x86_64，2 vCPU / 2 GB / 50 GB SSD |
| 形态 | 源码原生部署（非 Windows 交付包）；Python 3.12 venv，单端口应用 |
| 构建命令 | 无（前端产物 `frontend/dist` 直接拷贝；后端源码直跑） |
| 产物目录 | `/opt/fayelong/{backend, frontend/dist}`；数据 `/opt/fayelong/data` |
| 进程 | `uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1`（systemd 托管） |
| 反向代理 | Caddy 2.11.4，`:80` → `127.0.0.1:8000`，gzip/zstd |
| 环境变量（仅名） | `FAYELONG_HOST` `FAYELONG_PORT` `FAYELONG_WORKER_THREADS` `FAYELONG_WHISPER_MODEL` `FAYELONG_WHISPER_COMPUTE_TYPE` `FAYELONG_HF_ENDPOINT` |
| 回滚 | `bash /opt/fayelong/deploy/linux/update.sh <新代码目录>` 结尾会打印可直接粘贴的回滚命令；旧代码在 `/opt/fayelong/.backup/`；数据目录从不被覆盖 |

## 域名与 HTTPS
| 项 | 状态 | 说明 |
|---|---|---|
| 域名绑定 | N-A | 当前用公网 IP 直连，无域名 |
| HTTPS | N-A | 无域名无证书；Caddy 已就绪，接域名后自动签发并 301 |
| URL 一致性 | PASS | SPA 单页 + 深链回退（`/anything` 均 200 且落到前端路由） |
| 混合内容 | PASS | 页面无外部 HTTP 资源 |

## 上线前检查
逐项结果见 [`deploy/PRELAUNCH-CHECKLIST.md`](./PRELAUNCH-CHECKLIST.md)。摘要：
- 主理人指定的 **8 项专属检查全部 PASS**；
- 通用 A（可访问性）/ D（功能）**无 FAIL**；
- B（多端）有 4 项 **CONCERNS**（未做像素级/交互级验证）；
- E（SEO）因 IP 直连、无域名、无收录意图判为 **N-A / 建议改进**；
- F（性能）F1/F3/F5/F6 PASS，F2 未跑 Lighthouse（CONCERNS）。

## 性能
| 指标 | 优化前 | 优化后 |
|---|---|---|
| JS 传输体积 | 315,364 B | 98,107 B（gzip，−69%） |
| CSS 传输体积 | 24,105 B | 5,283 B（gzip，−78%） |
| `/assets/*` 缓存 | 无 Cache-Control | `public, max-age=31536000, immutable` |
| 首页总资源（gzip） | 339.9 KB | **103.8 KB** |
| 公网 TTFB | — | 0.045–0.077 s |
| `Server` 头 | 暴露 `Caddy` | 已移除 |

ASR 性能（2 vCPU，同一 34.4s 音频）：**small 39.0s（RTF 1.13×）/ base 12.6s（RTF 0.37×）** → **默认选 `small`**（用户决策：听写场景转写即标准答案，准确率优先；`base` 可一键切换，见 `deploy/README.md` §5.1）。
内存：转写峰值 RSS 328 MB，无 OOM。

## 未解决项
1. B3/B4/B5/B6 未做像素级与交互级验证（横向溢出、移动端导航、点击区尺寸、跨浏览器）。
2. 无独立 404 视图（未知路径渲染应用主界面）。
3. SEO 技术项缺失（无 description / robots / sitemap / canonical / og）——IP 形态下不阻塞。
4. 软 404：`/robots.txt`、`/sitemap.xml`、`/favicon.ico` 被 SPA 回退成 200+HTML。
5. 单 worker 串行，转写期间其他请求排队（2 核 2GB 的取舍）。
6. 实例 **2026-11-14 到期、未开自动续费**，到期不续站点将下线。
7. 无 HTTPS/域名，浏览器可能提示“不安全”。

详见 `deploy/PRELAUNCH-CHECKLIST.md` 第三节。

## 我的判定
**可上线（附已知问题）** —— 阻塞项：无。

## 需要用户自己完成的步骤
1. **续费/自动续费**：2026-11-14 前在腾讯云控制台为 `lhins-a0s35jwt` 续费或开启自动续费，否则站点下线。
2. **（可选）接入域名**：购买域名 → DNS 解析 A 记录指向 `114.132.173.241` → 大陆主机需完成 **ICP 备案** → 把 Caddy 站点的 `:80` 改为域名，Caddy 自动签发 HTTPS。
3. **（可选）移动端真机验收**：用手机浏览器打开 `http://114.132.173.241/`，确认无横向滚动、导航可展开、按钮不误触。
4. **（可选）若要 SEO 收录**：需前端补 meta description / og / canonical，后端补 robots.txt、sitemap.xml 与独立 404。
5. **（可选）换识别规格**：默认 `small`（准确率优先）。如需吞吐优先，把 `FAYELONG_WHISPER_MODEL` 改为 `base` 并重启（模型已在机上）。

## 上线后建议观察的指标
1. **服务存活与重启**：`systemctl is-active fayelong`、`systemctl show fayelong -p NRestarts`（异常自愈次数）。
2. **内存与 OOM**：`systemctl show fayelong -p MemoryCurrent`、`journalctl -k | grep -i oom`（转写高峰是否触顶 1.3 G）。
3. **公网可用性与延迟**：对 `http://114.132.173.241/api/health` 做外部拨测，观察 5xx 与 TTFB 变化。

---
> 交付物：`deploy/linux/{install.sh, fayelong.service, Caddyfile.site, update.sh}`、`deploy/README.md`、`deploy/PRELAUNCH-CHECKLIST.md`、本报告。
> 服务器：`/opt/fayelong/` 全量 + `/etc/systemd/system/fayelong.service` + `/etc/caddy/Caddyfile`。
