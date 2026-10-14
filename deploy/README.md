# FayeLong 部署手册（Linux / 腾讯云轻量应用服务器）

> 本文档面向运维与后续维护者。目标形态：**浏览器打开 `http://<公网IP>` 即为 FayeLong 首页**。
> 已验证环境：Ubuntu 24.04.4 LTS x86_64 / 2 vCPU / 2 GB 内存 / Python 3.12.3 / ffmpeg 6.1.1。

---

## 一、架构总览

```
                  公网 :80
                     │  (HTTP，纯 IP 访问，暂无域名/证书)
                 ┌───▼────────┐
                 │   Caddy    │  反向代理 + gzip/zstd 压缩 + 访问日志
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
├─ frontend/dist/           # 前端构建产物（config.py 的 STATIC_CANDIDATES[0]）
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

| 系统级文件 | 作用 |
|---|---|
| `/etc/systemd/system/fayelong.service` | 托管 uvicorn（自启、崩溃重启、内存上限） |
| `/etc/caddy/Caddyfile` | `:80` 站点，反代到 127.0.0.1:8000 |
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

### 步骤 3：放通防火墙 80 端口

在腾讯云轻量控制台（或 `lighthouse-ops` 连接器）为该实例新增规则：
`TCP / 端口 80 / 来源 0.0.0.0/0 / ACCEPT / 描述 “FayeLong Web”`。
**不要改动 22(SSH) 与 ICMP 规则。**

### 步骤 4：验收

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/health   # 期望 200
curl -s -o /dev/null -w "%{http_code}\n" http://<公网IP>/                    # 期望 200
systemctl is-enabled fayelong                                               # 期望 enabled
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
| systemd 单元日志 | journald | `journalctl -u fayelong -f` |
| Caddy 访问日志 | `/var/log/caddy/fayelong-access.log` | `tail -f /var/log/caddy/fayelong-access.log` |
| 应用内日志 | `/opt/fayelong/data/logs/` | — |
| SS 进度 | 前端页面内展示 | `curl -N http://127.0.0.1:8000/api/media/<id>/progress` |

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
| 被 OOM Kill | `dmesg \| grep -i oom`；已设 `MemoryMax=1300M` + `Restart=on-failure`；转写任务**串行**执行 |
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
