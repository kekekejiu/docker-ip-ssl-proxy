#!/bin/sh
# 等 issuer 签出 ip.crt 再启动 nginx，否则 nginx 会因缺证书直接退出并进入重启循环。
set -e
CRT=/etc/nginx/cert/ip.crt
KEY=/etc/nginx/cert/ip.key
W=0
while [ ! -s "$CRT" ] || [ ! -s "$KEY" ]; do
  [ $((W % 30)) -eq 0 ] && echo "[nginx] 等待证书 $CRT ...（已 ${W}s，进度: docker logs issuer）"
  sleep 5; W=$((W+5))
done
echo "[nginx] 证书就绪，启动 nginx"
exec /docker-entrypoint.sh nginx -g 'daemon off;'
