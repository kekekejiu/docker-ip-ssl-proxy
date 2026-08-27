# human-gate 人机验证闸门（反代站点公共片段）
# 用法：在反代站点的 server{} 里 include 本文件，再在 location / 内加一行：
#         auth_request /__gate/check;
# 说明：human-gate 容器为 host 网络，故这里用 127.0.0.1:9200 即可直达。
# 注意：API / WebDAV / 直链下载等 location 不要加 auth_request（自动放行）。

# 闸门校验端点：由 auth_request 内部调用
location = /__gate/check {
    internal;
    proxy_pass http://127.0.0.1:9200/__gate/check;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    proxy_set_header X-Original-URI $request_uri;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
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

# 未通过验证时跳转到闸门页；保持相对跳转，避免暴露源站/反代真实地址
error_page 401 = @gate_redirect;
location @gate_redirect {
    absolute_redirect off;
    return 302 /__gate/?next=$request_uri;
}
