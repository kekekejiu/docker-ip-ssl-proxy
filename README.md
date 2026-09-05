# docker-ip-ssl-proxy

给**纯 IP 地址**自动签发受浏览器信任的 HTTPS 证书，并做反向代理。开箱即用，无需域名、无需面板。

- `issuer` — 启动时自动探测本机公网 IPv4，通过 ZeroSSL REST API 申请 90 天 IP 证书，常驻自动续期
- `nginx` — TLS 终结 + 反向代理，可跑在任意端口（如 `https://1.2.3.4:10086`）
- `human-gate` — 人机验证闸门 + 访客数据上报（默认对反代站点开启，见下方「人机验证闸门」）

证书固定输出为 `nginx/cert/ip.crt` 和 `ip.key`。

## 受控自动更新

首次部署或迁移后可安装 systemd 定时更新任务，每10分钟检查 GitHub 新版本：

```bash
# 普通网页反代节点：更新issuer/nginx/human-gate
bash deploy/install-auto-update.sh full

# 后端API节点：只更新ZeroSSL签发器，绝不安装/启动human-gate
bash deploy/install-auto-update.sh cert-only
```

更新器会保留本机 `.env`、`nginx/http.d/`、`nginx/stream.d/`、证书、日志、issuer状态和human-gate密钥。新版会先在临时目录执行 `docker compose config`，部署后检查容器、nginx配置和human-gate健康状态；失败自动回滚。`cert-only` 模式不修改compose/nginx，也会拒绝human-gate容器存在。

## 人机验证闸门（human-gate）

本项目已内置人机验证闸门：**反代站点默认开启**，访客首次访问网页需通过滑块验证，
爬虫/自动化请求被挡在门外；同时把访客数据（IP、UA、运营商、地区、风险等级）上报到你的分析中心。

一次部署即接入，无需手动配置每个站点：

- `.env` 里的上报配置（`GATE_REPORT_URL` / `GATE_REPORT_TOKEN`）**已填好默认中心**，
  通常无需改动。部署时一般**只需填 `ZEROSSL_API_KEY`**。
- `docker compose up -d` 会一并启动 issuer、human-gate、nginx 三个服务；
  站点模板 `ip.conf` 已默认 `include exconf/human-gate.inc` 并在 `location /` 加了
  `auth_request`，直接生效。

> 分析中心若迁移或独立部署，改 `.env` 里的 `GATE_REPORT_URL` / `GATE_REPORT_TOKEN` 即可。
> 节点会自动从上报地址推导 `/__gate/policy`，默认每60秒拉取签名策略。

**跨站联防当前为观察模式**：中心把高置信 `danger` 公网IP生成24小时候选，节点命中后只回传“拟执行动作”，不会真的拦截、限速或302。基础设施白名单（含EZ主题4个可信反代IP）优先于候选规则。

**整台机器关闭滑块**（如本机专门反代 API，不面向浏览器用户）：
`.env` 里设 `GATE_ENABLE=off`，`docker compose up -d` 即可。全站放行、不弹滑块，
**无需改任何 nginx 配置**；且仍会采集并上报访客数据，中心照样能看到分析。

**只给某个站点关闭闸门**（部分站要、部分不要）：删掉该站 `.conf` 里的
`include .../human-gate.inc;` 与 `location /` 内的 `auth_request /__gate/check;` 两行即可。
（API 示例站 `hh.conf` 本就没加闸门，可直接参考。）

**放行特定路径**（如网页站里的 API / WebDAV / 直链下载）：给这些路径单独写 `location`，
不加 `auth_request` 即自动放行。

> human-gate 与 nginx 同为 host 网络，闸门经 `127.0.0.1:9200` 通信。
> 分析中心（含面板、IP 画像库）单独部署，本项目内的 human-gate 只做本地闸门 + 上报。
> `human-gate/data/` 下会生成 `secret.key`（HMAC 密钥），已在 `.gitignore` 排除。

## 为什么不用 acme.sh

ZeroSSL 的 **ACME 接口不支持 IP 标识符**，用 acme.sh / lego 指向 ZeroSSL 申请 IP 证书会被服务端直接拒绝：

```
urn:ietf:params:acme:error:unsupportedIdentifier :: IPv4 and IPv6 identifier types are not yet supported
```

ZeroSSL 的 IP 证书只能走 REST API（网页控制台同源）。本项目实现的就是这条路径。
Let's Encrypt 虽然从 2025 年 7 月起支持 ACME 签发 IP 证书，但有效期仅 160 小时（约 6.7 天）；
ZeroSSL 付费套餐可不限量签发 **90 天** IP 证书，运维负担小得多。

## 部署步骤

**1. 装 Docker**

```bash
curl -fsSL https://get.docker.com | sh
```

**2. 拉取项目**

```bash
git clone https://github.com/kekekejiu/docker-ip-ssl-proxy.git /opt/lnmpr
cd /opt/lnmpr
```

**3. 填 API key**

```bash
cp .env.example .env
nano .env      # 填 ZEROSSL_API_KEY
```

**4. 改反代目标**

仓库自带两个示例站点，编辑其中的 `listen` 端口和 `set $upstream` 目标：

| 文件 | 端口 | 示例上游 |
| --- | --- | --- |
| `nginx/http.d/ip.conf` | 10086 | `https://example.com` |
| `nginx/http.d/hh.conf` | 11186 | `https://api.example.com` |

每个站点要改三处：

```nginx
listen 10086 ssl default_server;          # 对外端口
set $upstream "https://example.com";      # 反代目标
set $upstream_host "example.com";         # 传给上游的 Host（不带协议）
```

`$upstream_host` 必须与上游域名一致。它同时用于 `proxy_set_header Host` 和
`proxy_ssl_name`（SNI）—— 反代到域名时若传成本机 IP，上游的路由匹配、
cookie domain、重定向地址都会出错，共享 IP 的主机甚至会握手失败。
反代到 IP:端口 时，这两个值填该 IP 即可。

不需要的站点直接删掉对应 `.conf` 文件；要加站点就复制一份改端口和上游。
注意 `nginx/http.d/default.conf` 是刻意留空的 —— 80 端口必须留给 issuer。

站点均为纯 HTTPS 端口，已配置 `error_page 497` 自动跳转：
误用 `http://你的IP:10086` 访问会 302 到 `https://你的IP:10086`，
不会再出现 nginx 的 `400 The plain HTTP request was sent to HTTPS port`。

**5. 确认 80 端口空闲**

```bash
ss -lntp | grep ':80 '
```

必须没有输出。ZeroSSL 的文件验证只走 80 端口，签发时 issuer 需要独占它
（平时不占用）。若被占用见下方「80 端口被占」。

**6. 启动**

```bash
docker compose up -d
docker compose logs -f issuer
```

看到「完成，到期时间 ...」即成功，约 20-30 秒。nginx 会等证书就绪后自动启动。

**7. 验证**

```bash
curl -sS -o /dev/null -w "HTTP %{http_code} / TLS %{ssl_verify_result}\n" https://你的IP:10086/
```

`TLS 0` 表示证书受浏览器信任（非 0 说明链有问题）。

## 工作原理

```
启动 → 探测公网 IPv4 → 生成私钥+CSR(CN=IP, SAN=IP)
     → ZeroSSL 创建证书 → issuer 临时监听 80 提供校验文件
     → 触发 HTTP_CSR_HASH 验证 → 轮询至 issued
     → 写入 ip.crt/ip.key → 释放 80 → 通知 nginx 重载
     → 休眠，每 12h 检查一次
```

关键设计：**issuer 自己在 80 端口应答验证请求**，不依赖 nginx。
否则会形成死锁 —— nginx 缺证书起不来，80 无人应答，验证失败，永远拿不到证书。
nginx 侧则由 `wait-cert.sh` 等证书就绪后再启动，避免崩溃重启循环。

签发前 issuer 会先自检一次校验 URL 能否返回 200 且内容一致，
不通过就直接中止，避免浪费 ZeroSSL 的验证配额。

## 续期

issuer 常驻，每 12 小时检查，剩余不足 30 天时自动续期，
完成后通过 docker socket 通知 nginx 重载。无需人工干预。

手动强制续期：

```bash
FORCE_ISSUE=1 docker compose up -d issuer   # 等日志出现「完成」
docker compose up -d issuer                 # 复位
```

查看剩余天数：

```bash
openssl x509 -in nginx/cert/ip.crt -noout -enddate
```

## 常见问题

**80 端口被占**

签发会失败并提示 `Address in use`。找出占用者并停掉：

```bash
ss -lntp | grep ':80 '
```

装了宝塔的机器要额外解除服务守护，否则 nginx 会被自动拉回来抢端口：

```bash
echo '[]' > /www/server/panel/data/daemon_service.pl
/etc/init.d/nginx stop
```

**反代上游解析失败**

`resolver` 必须填机器上真实可用的 DNS。本项目已设为 `8.8.8.8 1.1.1.1`。
`127.0.0.53` 只在跑 systemd-resolved 的机器上有效。

**IPv6**

ZeroSSL 不签发 IPv6 证书。双栈机器上 `curl ip.sb` 往往返回 IPv6，
本项目已强制走 IPv4 探测。多 IP 机器建议在 `.env` 里显式设置 `CERT_IP`。

## 配置项

`.env` 全部可用变量：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `ZEROSSL_API_KEY` | 必填 | ZeroSSL API access key |
| `CERT_IP` | 自动探测 | 留空则启动时探测公网 IPv4 |
| `CERT_VALIDITY_DAYS` | `90` | ZeroSSL 仅支持 90 或 200 |
| `RENEW_BEFORE_DAYS` | `30` | 剩余天数低于此值时续期 |
| `CHECK_INTERVAL_HOURS` | `12` | 检查间隔 |
| `FORCE_ISSUE` | `0` | 设为 1 强制重新签发 |

issuer 还支持 `VERIFY_MODE=webroot`（见 `docker-compose.yaml` 注释）：
不监听 80，而是把校验文件写进已有 Web 服务的站点目录，
适合宿主 80 端口无法腾出的场景。

## 注意

- 需要 **ZeroSSL 付费套餐**才能不限量签发 IP 证书；免费账号有额度限制。
- `.env` 含 API key，已在 `.gitignore` 中排除，建议权限设为 600。
- 仅支持 IPv4。
- `docker-compose.full.yaml.bak` 是原始 lnmpr 的五服务配置（含 php/mariadb/redis），
  纯反代场景不需要。若要恢复 mariadb，务必先按实际内存调小 `innodb_buffer_pool_size`，
  原值 4G 在小内存机器上会 OOM 无法启动。

## License

MIT
