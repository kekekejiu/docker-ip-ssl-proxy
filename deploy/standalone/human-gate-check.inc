# 闸门校验（Lua cosocket 版）——在需要保护的 location 内 include 本文件。
# 等价于 auth_request 版的：auth_request /__gate/check;
#
# 为什么不用 ngx.location.capture：
#   该 API 不支持 HTTP/2 请求（"http2 requests not supported yet"），
#   而站点通常启用 http2/http3，会直接 500。cosocket 无此限制。
#
# 行为：向 human-gate 发起校验请求；非 2xx 即视为未通过，
# 302 跳转闸门页并带上原始地址。保持相对跳转，避免暴露源站地址。
access_by_lua_block {
    local function fail_open(err)
        -- 闸门不可用时放行，避免闸门故障导致整站不可访问。
        ngx.log(ngx.ERR, "human-gate check unavailable: ", err or "unknown")
    end

    local sock = ngx.socket.tcp()
    sock:settimeouts(500, 1000, 1000)
    local ok, err = sock:connect("127.0.0.1", 9200)
    if not ok then
        return fail_open(err)
    end

    local uri = ngx.var.request_uri or "/"
    local parts = {
        "GET /__gate/check HTTP/1.1\r\n",
        "Host: ", ngx.var.host or "localhost", "\r\n",
        "X-Original-URI: ", uri, "\r\n",
        "X-Forwarded-Host: ", ngx.var.host or "", "\r\n",
        -- $remote_addr 已由 realip/proxy-realip.conf 还原为访客真实 IP
        "X-Real-IP: ", ngx.var.remote_addr or "", "\r\n",
        "X-Forwarded-For: ", ngx.var.proxy_add_x_forwarded_for or "", "\r\n",
        "X-Forwarded-Proto: ", ngx.var.scheme or "https", "\r\n",
        "User-Agent: ", ngx.var.http_user_agent or "", "\r\n",
        "Cookie: ", ngx.var.http_cookie or "", "\r\n",
        "Connection: close\r\n\r\n",
    }
    local bytes, serr = sock:send(table.concat(parts))
    if not bytes then
        sock:close()
        return fail_open(serr)
    end

    local status_line, rerr = sock:receive("*l")
    sock:close()
    if not status_line then
        return fail_open(rerr)
    end

    local code = tonumber(string.match(status_line, "^HTTP/%d%.%d%s+(%d%d%d)"))
    if not code then
        return fail_open("bad status line: " .. status_line)
    end
    if code >= 200 and code < 300 then
        return
    end

    return ngx.redirect("/__gate/?next=" .. ngx.escape_uri(uri), 302)
}
