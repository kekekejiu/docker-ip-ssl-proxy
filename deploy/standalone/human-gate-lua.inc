# ============================================================
# 人机验证闸门 (human-gate) —— Lua 版公共片段
#
# 适用于未编译 http_auth_request_module、但带 lua_nginx_module 的 nginx
# （宝塔部分版本即是这种组合）。用法与 auth_request 版等价：
#   1) 在 server{} 里 include 本文件；
#   2) 在需要保护的 location 里加一行：
#        access_by_lua_block { gate_check() }
#      或直接用下面提供的 include：
#        include /www/server/panel/vhost/nginx/human-gate-check.inc;
#
# 注意：API / 支付回调 / 静态资源等 location 不要加校验，即自动放行。
# ============================================================

# 校验用内部子请求端点：不对外暴露
location = /__gate/check {
    internal;
    proxy_pass http://127.0.0.1:9200/__gate/check;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    proxy_set_header X-Original-URI $request_uri;
    proxy_set_header X-Forwarded-Host $host;
    # $remote_addr 已由 realip/proxy-realip.conf 还原为访客真实 IP
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header User-Agent $http_user_agent;
    proxy_set_header Cookie $http_cookie;
}

# 闸门页面与接口（验证页 / 生成滑块 / 校验）：直接转发，不参与鉴权
location /__gate/ {
    proxy_pass http://127.0.0.1:9200;
    proxy_set_header Host $host;
    proxy_set_header User-Agent $http_user_agent;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    access_log off;
}
