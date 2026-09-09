# 非 Docker 节点接入 human-gate 闸门

宝塔环境有两种情况，取决于 nginx 是否编译了 `http_auth_request_module`：

```bash
/www/server/nginx/sbin/nginx -V 2>&1 | grep -c with-http_auth_request_module
```

## 有 auth_request（返回 1）

用标准片段，在 `server{}` 里 include `human-gate.inc`，再在要保护的
`location` 内加：

```nginx
auth_request /__gate/check;
```

## 没有 auth_request（返回 0）

改用本目录的 Lua 版，无需重新编译 nginx（要求已带 `lua_nginx_module`）：

```bash
cp human-gate-lua.inc human-gate-check.inc /www/server/panel/vhost/nginx/
```

在 `server{}` 里 include：

```nginx
include /www/server/panel/vhost/nginx/human-gate-lua.inc;
```

在要保护的 `location` 内 include：

```nginx
include /www/server/panel/vhost/nginx/human-gate-check.inc;
```

### 为什么用 cosocket 而不是 ngx.location.capture

`ngx.location.capture` 不支持 HTTP/2 请求，站点开了 `http2 on` 会直接 500：

```text
lua entry thread aborted: runtime error: http2 requests not supported yet
```

因此 `human-gate-check.inc` 采用 `ngx.socket.tcp()` 直连 `127.0.0.1:9200`，
HTTP/1.1、HTTP/2、HTTP/3 场景均可用。闸门不可用时选择放行（fail-open），
避免闸门故障导致整站不可访问。

## 反代目标要指向真实应用

闸门是旁路校验，不能取代应用。`proxy_pass` 必须指向真实上游（例如 MrDoc 的
`127.0.0.1:8808`），而不是 human-gate 的 `9200`，否则验证通过后仍停在闸门页。

## 验证

```bash
curl -sk -o /dev/null -w '%{http_code} -> %{redirect_url}\n' https://你的IP/
```

未验证时应 `302` 跳到 `/__gate/?next=...`；闸门页应返回 `200`。
再确认 nginx 错误日志中没有 `lua entry thread aborted`。
