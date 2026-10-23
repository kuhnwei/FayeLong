# FayeLong 部署手册（Linux / 腾讯云轻量应用服务器）

> 本文档面向运维与后续维护者。目标形态：**浏览器打开 `https://fayelong.com.cn` 即为 FayeLong 首页**（HTTPS + Let's Encrypt 自动续期，见 §十二）。
> 已验证环境：Ubuntu 24.04.4 LTS x86_64 / 2 vCPU / 2 GB 内存 / Python 3.12.3 / ffmpeg 6.1.1。

---

## 一、架构总览

```
              公网 :443 (HTTPS)          :80 → 301 跳转到 :443
                     │  (证书由 Caddy 内置 ACME 自动申领 / 自动续期)
                 ┌───▼────────┐
                 │   Caddy    │  反向代理 + gzip/zstd 压缩 + 访问日志 + TLS 终止
                 └───┬────────┘
                     │  reverse_proxy → 127.0.0.1:8000
                 ┌───▼──────────────────────┐
                 │ uvicorn (systemd 托管)    │  FastAPI 单端口应用
                 │ /opt/fayelong/venv/bin/…  │  · 提供 /api/*
                 │ WorkingDirectory=backend  │  · 托管 frontend/dist（SPA 回退）
                 └───┬──────────────────────┘
                     │
        /opt/fayelong/data/  ← 唯一运行时数据根（app.db / media / models / dict / logs）
```

- **单端口应用**：后端同时提供 API 与前端静态资源，机器上**不需要 Node**。
- **构建产物**：`frontend/dist`（v1.11，约 344 KB），直接拷贝，无需在服务器重新构建。
- **数据即迁移**：整个学习数据都在 `/opt/fayelong/data/`，拷贝该目录即完成迁移。

---

## 二、服务器目录布局

```
/opt/fayelong/
├─ backend/                 # 后端源码（含 requirements.txt → config.py 判定为「开发形态」）
│  ├─ app/                  #   36 个 .py
│  ├─ scripts/              #   fetch_dict.py / selftest.py
│  ├─ requirements.txt
│  └─ requirements-ml.txt
├─ frontend/dist/           # 前端构建产物（旧 React，冻结版；见下方脚注）
├─ deploy/                  # 本部署资产（linux/ 下为脚本）
├─ venv/                    # Python 虚拟环境（约 526 MB）
└─ data/                    # 运行时数据根（★ 更新时绝不触碰）
   ├─ app.db                #   SQLite（104 KB）
   ├─ media/{audio,library} #   收件箱 + 媒体库（约 30 MB）
   ├─ models/               #   faster-whisper-small（464 MB）/ -base（142 MB）
   ├─ dict/ecdict.db        #   ECDICT 词库（约 207 MB 压缩包解出）
   └─ logs/                 #   应用日志
```

`config.py` 依据 `backend/requirements.txt` 的存在自动判定「开发形态」：
`BASE_DIR=/opt/fayelong/backend` → `ROOT_DIR=/opt/fayelong` → `DATA_DIR=/opt/fayelong/data`、
静态目录 `/opt/fayelong/frontend/dist`。**无需改动任何业务代码。**

> **⚠️ 静态目录（2026-10-22 起已切换并清理旧版）**
> `STATIC_CANDIDATES = (frontend-vue/dist, static)` —— 开发环境用 Vue 产物，打包环境用 `static`。
> 云端 `/opt/fayelong/frontend/dist` 目录里现在放的是 **Vue 产物**（部署时由 `update.sh` 从 `frontend-vue/dist` 拷入），**不是**旧 React。
> 旧 React 源码已于 2026-10-22 从仓库移除，源码保留在 git tag `frontend-react-final`。
> **回滚到旧 React**：先恢复构建产物（云端用 `/opt/fayelong/.backup/dist-20261022-145723`；本地从 tag 取源码重新 build），再把该目录放回候选首位 + 重启。详见 `docs/REFACTOR-PLAN-001-执行计划.md` §9。

| 系统级文件 | 作用 |
|---|---|
| `/etc/systemd/system/fayelong.service` | 托管 uvicorn（自启、崩溃重启、内存上限） |
| `/etc/caddy/Caddyfile` | `fayelong.com.cn` 站点：443 HTTPS 终止 + 反代 127.0.0.1:8000（证书自动签发/续期） |
| `/var/log/fayelong/*.log` | 服务 stdout/stderr |
| `/var/log/caddy/fayelong-access.log` | 访问日志 |

---

## 三、前置条件

- 服务器已装：`python3`(3.12)、`python3.12-venv`、`ffmpeg`、`caddy`。
  - 若缺 venv 模块：`apt-get update && apt-get install -y python3.12-venv`
- 本机（打包/运维机）能通过 SSH 连到服务器。
- 代码目录已就位：`/opt/fayelong/backend` 与 `/opt/fayelong/frontend/dist`。

---

## 四、首次部署（从零到可访问）

### 步骤 0：本机准备密钥并打通 SSH（一次性）

```bash
ssh-keygen -t ed25519 -f ~/.ssh/fayelong_deploy -N ""
# 把公钥追加到服务器 root 的 authorized_keys（可用云控制台 VNC / 连接器通道执行）：
#   mkdir -p /root/.ssh && chmod 700 /root/.ssh
#   echo '<公钥内容>' >> /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys
ssh -i ~/.ssh/fayelong_deploy -o StrictHostKeyChecking=no root@<公网IP> 'id'
```

### 步骤 1：上传代码与数据（从本机执行）

```bash
cd <本地仓库根>
# 后端（排除 Windows 专用虚拟环境与缓存）
tar --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' -czf /tmp/fel-backend.tar.gz backend
tar -czf /tmp/fel-frontend.tar.gz frontend/dist
tar -czf /tmp/fel-data.tar.gz data/app.db data/media
tar -czf /tmp/fel-deploy.tar.gz deploy

ssh ... root@<IP> 'mkdir -p /opt/fayelong/{backend,frontend,data}'
scp /tmp/fel-*.tar.gz root@<IP>:/tmp/
ssh ... root@<IP> 'cd /opt/fayelong && for f in backend frontend data deploy; do tar xzf /tmp/fel-$f.tar.gz; done && chown -R root:root /opt/fayelong'
```

> 不上传 `data/dict/`（812 MB）与 `data/models/`（464 MB）——在服务器上现下更快。

### 步骤 2：服务器上一键装配

```bash
cd /opt/fayelong/deploy/linux
bash install.sh            # 全流程：目录 + venv + 依赖 + 模型 + 词库 + systemd + Caddy
```

也可分步执行（便于排错、便于长任务后台跑）：

```bash
bash install.sh env        # 建目录 / venv / 装依赖（PyPI 走阿里云源）
bash install.sh models     # 下 small + base 两个 whisper 模型（hf-mirror 镜像）
bash install.sh dict       # 下 ECDICT 词库（约 207 MB）
bash install.sh service    # 装并启动 systemd 服务
bash install.sh caddy      # 配置 Caddy 反代
```

长任务建议后台跑并看日志：

```bash
nohup setsid bash install.sh models </dev/null >/var/log/fayelong/install-models.log 2>&1 &
tail -f /var/log/fayelong/install-models.log
```

### 步骤 3：放通防火墙 80 与 443 端口

在腾讯云轻量控制台（或 `lighthouse-ops` 连接器）为该实例新增规则：

| 协议 | 端口 | 来源 | 动作 | 描述 |
|---|---|---|---|---|
| TCP | 80 | 0.0.0.0/0 | ACCEPT | FayeLong Web（ACME HTTP-01 校验 + HTTP→HTTPS 跳转） |
| TCP | 443 | 0.0.0.0/0 | ACCEPT | FayeLong HTTPS |

**不要改动 22(SSH) 与 ICMP 规则。**

> ⚠️ **443 没放通是最典型的「证书签出来了但网站打不开」原因**：证书签发靠 80 端口的 HTTP-01
> 校验，所以即使 443 被云防火墙挡住，`journalctl -u caddy` 里依然会显示签发成功，
> 但浏览器连不上 443。验收时务必从**公网**测 443，不要只测 `127.0.0.1`。

### 步骤 4：验收

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/health   # 期望 200
curl -s -o /dev/null -w "%{http_code}\n" https://fayelong.com.cn/            # 期望 200
curl -s -o /dev/null -w "%{http_code}\n" http://fayelong.com.cn/             # 期望 301/308
systemctl is-enabled fayelong                                               # 期望 enabled
systemctl is-enabled caddy                                                  # 期望 enabled
```

---

## 五、配置与环境变量

配置前缀 `FAYELONG_`，可用 systemd `Environment=` 或 `backend/.env` 覆盖。**不含任何机密**。

| 变量 | 默认 | 说明 |
|---|---|---|
| `FAYELONG_HOST` | `127.0.0.1` | 监听地址（反代场景留回环） |
| `FAYELONG_PORT` | `8000` | 监听端口 |
| `FAYELONG_WORKER_THREADS` | `1`（本机覆盖） | 后台转码并发，2 核机器压到 1 |
| `FAYELONG_WHISPER_MODEL` | `small` | 默认识别规格（量化结论见上线检查表） |
| `FAYELONG_WHISPER_COMPUTE_TYPE` | `int8` | CPU 推理精度 |
| `FAYELONG_HF_ENDPOINT` | `https://hf-mirror.com` | 模型镜像（官方域名国内不可达） |

> 依赖安装**必须用阿里云源**：清华镜像对 `faster-whisper` 的 wheel 返回 403。

### 5.1 语音识别规格一键切换（small ⇄ base）

`small` 与 `base` 两个模型都已预置在服务器上（`data/models/faster-whisper-<规格>/`），
切换**无需重新下载**。

| 规格 | 磁盘 | 2 vCPU 实测（同一 34.4s 音频） | 定位 |
|---|---|---|---|
| `small` | 464 MB | 推理 36.3s，RTF 1.13× | **默认**：准确率优先——听写场景下转写文本即标准答案，错词会造成误判 |
| `base` | 142 MB | 推理 11.4s，RTF 0.37× | 吞吐优先——适合长音频多、可容忍少量识别误差时 |

切换步骤（以改用 `base` 为例）：

```bash
sed -i 's/FAYELONG_WHISPER_MODEL=small/FAYELONG_WHISPER_MODEL=base/' \
    /etc/systemd/system/fayelong.service
systemctl daemon-reload
systemctl restart fayelong
sleep 3
curl -s http://127.0.0.1:8000/api/health
```

验收：`/api/health` 中 `config.whisper_model` 与 `asr.model` 都等于目标规格，且 `asr.ready == true`。
若 `asr.ready` 为 `false`，说明该规格模型文件缺失，请检查 `data/models/faster-whisper-<规格>/model.bin` 是否存在
（参考第九节排错）。改回 `small` 只需把上面的 `sed` 两端对调。

---

## 六、日志位置

| 日志 | 位置 | 查看 |
|---|---|---|
| 服务 stdout/stderr | `/var/log/fayelong/service.log`、`service.err.log` | `tail -f /var/log/fayelong/service.err.log` |
| **worker 日志** | `/var/log/fayelong/worker.log`（unit 的 append 目标） | `journalctl -u fayelong-worker -f` |
| **worker 应用日志** | `/opt/fayelong/data/logs/worker.log` | `tail -f /opt/fayelong/data/logs/worker.log` |
| web 应用日志 | `/opt/fayelong/data/logs/app.log` | `tail -f /opt/fayelong/data/logs/app.log` |
| systemd 单元日志 | journald | `journalctl -u fayelong -f` / `journalctl -u fayelong-worker -f` |
| Caddy 访问日志 | `/var/log/caddy/fayelong-access.log` | `tail -f /var/log/caddy/fayelong-access.log` |
| SS 进度 | 前端页面内展示 | `curl -N http://127.0.0.1:8000/api/media/<id>/progress` |

> **两个进程的日志刻意分开**：web 写 `app.log`，worker 写 `worker.log`。两个进程同时
> 对一个文件做 `RotatingFileHandler` 轮转，在 Windows 上会 `PermissionError`，
> 在 Linux 上会互相覆盖（丢的正好是最有用的那一段）。

---

## 七、更新流程（就地更新，保留全部学习数据）

把新代码放到某个目录（含 `backend/` 与 `frontend/dist/`），然后：

```bash
cd /opt/fayelong/deploy/linux
bash update.sh <含新代码的目录>      # 默认用当前目录
```

`update.sh` 行为：备份旧代码 → 原子替换 `backend/` 与 `frontend/dist/` →
同步依赖 → 重启服务 → 健康检查。**绝不触碰 `/opt/fayelong/data/`。**
结尾会打印一条可直接粘贴的**回滚命令**。

---

## 八、回滚

- **代码回滚**：用 `update.sh` 结尾打印的命令，从 `/opt/fayelong/.backup/backend-<时间戳>` 恢复。
- **指定版本重建**：重新上传上一版 `backend/` 与 `frontend/dist/`，跑一次 `update.sh`。
- **退回「单进程全干」（P3-2 引入的双进程形态回滚）**：见 §十一.4。
- **系统级回滚**：`systemctl stop fayelong` 停机排查；Caddy 配置回滚用 `/etc/caddy/Caddyfile.bak.<时间戳>`。
- 回滚**不涉及数据**（data/ 从未被覆盖），因此学习记录始终可逆。

---

## 九、排错

| 症状 | 排查 / 处置 |
|---|---|
| `python3 -m venv` 报 `No module named ensurepip` | `apt-get install -y python3.12-venv` |
| pip 装 `faster-whisper` 报 403 | 换清华为**阿里云源**：`-i https://mirrors.aliyun.com/pypi/simple/` |
| 词库下载全部源 404 | `fetch_dict.py` 的 `{zip_name}` 占位符未格式化（已在仓库修复）；临时可用 `curl -L -o data/dict/tmp/ecdict-sqlite-28.zip <真实URL>` 预置压缩包，脚本会自动复用并解压 |
| 词库下载慢 | GitHub 直连 ~45 KB/s；改用镜像 `https://ghfast.top/https://github.com/.../ecdict-sqlite-28.zip`（实测 ~500 KB/s） |
| 模型下载失败 | 确认 `FAYELONG_HF_ENDPOINT=https://hf-mirror.com`（官方域名国内不可达） |
| 服务起不来 | `journalctl -u fayelong -n 100 --no-pager`；确认 `WorkingDirectory` 与 `venv` 路径 |
| 502 / Bad Gateway | 后端没起来：`systemctl status fayelong`；`curl 127.0.0.1:8000/api/health` |
| 被 OOM Kill | `dmesg \| grep -i oom`；web 上限 400M / worker 上限 1400M（见 §十一.3）；转写任务**串行**执行（`FAYELONG_JOB_CPU_THREADS=1`） |
| 素材一直显示「排队中」 | worker 没在跑：`systemctl status fayelong-worker`；`tail -50 /opt/fayelong/data/logs/worker.log`；`curl -s 127.0.0.1:8000/api/health \| python3 -m json.tool` 看 `worker.online` 与 `jobs.pending` |
| 端口占用 | `ss -ltnp \| grep -E ':80\|:8000'` |

**红线**：不要停用/卸载 Caddy；不要动 22 与 ICMP 防火墙规则；不要重启/改配实例；不要触碰 `/home/ubuntu/.hermes`。

---

## 十、日常养护

| 需求 | 操作 |
|---|---|
| 改文案 / 换图 | 属前端，需在本地 `frontend/` 重新构建出新的 `dist/`，再走 `update.sh` |
| 加媒体素材 | 把音频/视频丢进 `/opt/fayelong/data/media/audio/`，页面「导入」即可 |
| 换识别模型 | 改 `fayelong.service` 的 `FAYELONG_WHISPER_MODEL`，`systemctl daemon-reload && systemctl restart fayelong` |
| 备份学习数据 | `tar -czf fel-data-$(date +%F).tar.gz /opt/fayelong/data` |

---

## 十一、双进程部署（P3-2 起：web + worker）

### 11.1 两个 unit 各干什么

| unit | 进程 | 干什么 | 不干什么 |
|---|---|---|---|
| `fayelong.service` | `uvicorn app.main:app` | 全部 `/api/*`、静态托管、SSE 进度推送 | **不执行**转码/识别/翻译/切片（`FAYELONG_WEB_INPROC_WORKER=off`） |
| `fayelong-worker.service` | `python -m app.worker` | 消费 `jobs` 表：CPU 池（转码/识别/切片）+ IO 池（翻译） | 不监听端口 |

为什么拆：

1. **G3-③「ASR 不阻塞翻译」**：一条 `transcode→asr→translate→clip` 链被拆成 4 个
   stage job，每个 stage 自带池归属。翻译走 IO 池，长 ASR 期间它照跑。
2. **内存**：`services/asr.py` 是延迟导入 + 任务只在 worker 里执行 →
   **whisper 模型只在 worker 进程加载**。2GB 实例上 web 常驻从「≈1.1 GB」降到
   「≈150 MB」，总占用反而比拆分前更低。
3. **崩了不互相拖累**：worker 被 kill 后，它手上的任务租约过期后由新 worker（或
   web 的 `auto` 兜底）接管，`jobs.attempts` 记录尝试次数，最多 3 次。

### 11.2 安装 / 启停

```bash
cd /opt/fayelong/deploy/linux
bash install.sh service          # 同时安装并启动两个 unit
systemctl status fayelong fayelong-worker
journalctl -u fayelong-worker -f
```

两个 unit 的启动顺序**随便**：`off` 模式下 web 不干活；`auto` 模式下 web 会兜底。
`fayelong-worker.service` 刻意**没有** `After=fayelong.service` —— worker 不该等 web。

### 11.3 内存上限（是**上限**，不是预留）

| unit | 软限 `MemoryHigh` | 硬限 `MemoryMax` |
|---|---|---|
| `fayelong.service`（web） | 300M | **400M** |
| `fayelong-worker.service` | 1000M | **1400M** |

合计上限 1800M < 2GB，留 200M 给系统/Caddy。

> ⚠️ **上线后必须实测回填**：这两组数是按「web 不加载模型 + whisper small int8
> 常驻 ≈ 1.0 GB」估的，没有在 2 vCPU 实机上验证过。跑 2～3 个真实素材后执行
> `systemd-cgtop -1`（或 `systemd-cgtop` 观察 10 分钟），看
> `/system.slice/fayelong.service` 与 `/system.slice/fayelong-worker.service` 的
> `Memory` 列，把 `MemoryMax` 调到「实测峰值 × 1.2」再 `daemon-reload + restart`。
> 若 worker 峰值 > 1400M：先把 `FAYELONG_WHISPER_MODEL` 换成 `base`
> （见 §五.1），而不是盲目抬高上限（抬到 1500M 以上就会和 web 抢同一块 2GB）。

### 11.4 回滚到「单进程全干」（旧行为）

```bash
systemctl disable --now fayelong-worker
# 把 fayelong.service 里的 FAYELONG_WEB_INPROC_WORKER=off 改成 auto（或 on）
systemctl daemon-reload
systemctl restart fayelong
```

- `auto`：web 5s 后检查 `workers` 表，没有在线 worker 就自己接管（任务仍会完成，只是慢）；
- `on`：web 无条件执行任务（等价于 P3-2 之前的行为）。

两个执行者同时存在也**不会双跑**：执行权靠 `jobs` 表的原子 claim（`UPDATE ...
WHERE status='pending'` + `rowcount==1`）+ `attempts` 作 fencing token。

### 11.5 自检要点

```bash
curl -s 127.0.0.1:8000/api/health | python3 -m json.tool
```

- `worker.online` 必须为 `true`，`worker.count` 应为 **1**（`>1` 说明有孤儿 worker）；
- `worker.last_heartbeat_at` 应在 30s 内（否则 worker 心跳停了）；
- `jobs.pending` 长期 > 0 且 `jobs.running == 0` → worker 没在消费，看
  `journalctl -u fayelong-worker`。

---

## 十二、HTTPS 与证书（Let's Encrypt 自动续期）

**上线时间**：2026-10-23 ｜ **域名**：`fayelong.com.cn`（`www` 无解析，不签）

### 12.1 结论先行：本机没有、也不需要 Certbot

服务器跑的是 **Caddy v2.11.4**，它内置 ACME 客户端，把站点地址从 `:80` 改成 `fayelong.com.cn`
的那一刻起就同时拿到了四件事：

1. 向 Let's Encrypt 申领免费证书（90 天有效）；
2. 自动把 `:80` 的明文请求 301 到 `:443`；
3. 后台每 12h 巡检一次，到期前自动续签并**热加载**（不重启进程、不中断连接）；
4. 证书链、OCSP、密钥轮换全部自理。

因此**不装 nginx、不装 certbot、不写 cron、不加 systemd timer**。多引一个 ACME 客户端只会
引入「两个客户端抢同一份证书 / 续期后忘记 reload」这类故障，收益为零。

> 参考：若日后确实要换方案，`certbot --nginx` 需要先引入 nginx 并重写现有的
> gzip/zstd 压缩、`/assets/*` 强缓存、SSE `flush_interval -1` 三处配置，改动面远大于收益。

### 12.2 当前证书

| 项 | 值 |
|---|---|
| 签发者 | Let's Encrypt（中间 CA `YE2`） |
| 主体 | `CN=fayelong.com.cn` |
| 签发 / 到期 | 2026-10-23 → **2027-01-21** |
| 续期触发 | ARI 建议窗口 ≈ 2026-12-21（早于到期 30 天） |
| 私钥与证书落盘 | `/var/lib/caddy/.local/share/caddy/certificates/acme-v02.api.letsencrypt.org-directory/fayelong.com.cn/` |

### 12.3 验证命令（运维日常）

```bash
# 1) 看证书到期时间（最直观）
echo | openssl s_client -connect fayelong.com.cn:443 -servername fayelong.com.cn 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates

# 2) 看跳转链路（期望 308 / 301）
curl -sI http://fayelong.com.cn/ | head -3

# 3) 看续期有没有正常调度（关键：出现 renewal / obtained 字样）
journalctl -u caddy --since "-7d" | grep -iE "acme|renew|obtained" | tail -20
```

> Caddy 没有「强制续期」子命令。真要强制重签，只能删证书目录后 reload
> （`systemctl reload caddy` 会让 Caddy 重新走一遍 order）——**注意 Let's Encrypt 对同一
> 域名有「每周 5 次重复签发」的速率限制**，非排障不要随便重签。

### 12.4 站点配置要点（`deploy/linux/Caddyfile.site`）

```caddyfile
fayelong.com.cn {            # ← 写裸域名即开 HTTPS；写 :80 就是纯 HTTP
    encode zstd gzip
    @assets path /assets/*
    header @assets Cache-Control "public, max-age=31536000, immutable"
    reverse_proxy 127.0.0.1:8000 { flush_interval -1 }   # flush_interval -1 是 SSE 进度条的生命线
    header {
        -Server
        X-Content-Type-Options nosniff
        Strict-Transport-Security "max-age=31536000"      # 一年内强制 HTTPS；未加 includeSubDomains/preload
    }
}

# 老书签 http://114.132.173.241/ 仍可用，跳到域名；精确匹配该 Host，不抢 ACME 校验路径
http://114.132.173.241 { redir https://fayelong.com.cn{uri} permanent }
```

**为什么 HTTPS 之后不会有混合内容问题**（已实测排除）：

- 前端 API 基址是相对路径 `/api`（`frontend-vue/src/api/request.ts` → `export const BASE = '/api'`），
  同源请求，不经过 CORS；
- 产物 bundle 里唯一的 `http://` 是 `www.w3.org/2000/svg` 这类 XML 命名空间常量，不会被请求；
- uvicorn 已带 `--proxy-headers --forwarded-allow-ips=127.0.0.1`，后端能正确识别
  `X-Forwarded-Proto: https`，应用侧若拼绝对地址也会是 https。

### 12.5 回滚（回到纯 HTTP）

```bash
ls -t /etc/caddy/Caddyfile.bak.* | head -1                  # 找到切换前的备份
cp -a "$(ls -t /etc/caddy/Caddyfile.bak.* | head -1)" /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl reload caddy
```

> ⚠️ 回滚前先想清楚：一旦站点在用户浏览器里缓存过 `Strict-Transport-Security`，
> 该浏览器在 max-age（一年）内**仍会强制 https**，纯 HTTP 回滚对它无效。

### 12.6 常见故障对照

| 现象 | 原因 | 处置 |
|---|---|---|
| 证书签发成功但浏览器连不上 | 云防火墙未放通 443/TCP | 控制台加 `TCP/443/0.0.0.0/0/ACCEPT` |
| `caddy validate` 报 address already in use | 另一个进程占了 80/443 | `ss -tlnp \| grep -E ':80\|:443'` |
| 签发失败 `unauthorized` / 超时 | 80 被云防火墙或云厂商拦截（**大陆机器未备案会直接拦 80**） | 先确认 `curl -I http://fayelong.com.cn/` 返回的是真实应用响应而不是拦截页 |
| 续期后仍旧证书 | reload 未生效 | `systemctl reload caddy`；`journalctl -u caddy -n 50` |
| 页面能开但听写进度条不动 | 反代丢了 SSE flush | 确认 `reverse_proxy` 块里 `flush_interval -1` 还在 |
