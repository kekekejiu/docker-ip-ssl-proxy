#!/usr/bin/env bash
# 安装受控自动更新任务
# 用法：bash deploy/install-auto-update.sh full|cert-only
set -euo pipefail
SCOPE="${1:-full}"
case "$SCOPE" in full|cert-only) ;; *) echo "用法: $0 full|cert-only"; exit 2;; esac
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ "$ROOT" = /opt/lnmpr ] || echo "提示：项目位于 $ROOT，将写入 PROJECT_DIR"

ensure_command(){
  local cmd="$1" pkg="$2"
  command -v "$cmd" >/dev/null 2>&1 && return 0
  echo "缺少 $cmd，正在安装 $pkg..."
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$pkg"
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y "$pkg"
  elif command -v yum >/dev/null 2>&1; then
    yum install -y "$pkg"
  elif command -v apk >/dev/null 2>&1; then
    apk add --no-cache "$pkg"
  else
    echo "无法自动安装 $pkg，请先手动安装" >&2; exit 1
  fi
  command -v "$cmd" >/dev/null 2>&1 || { echo "$cmd 安装失败" >&2; exit 1; }
}
ensure_command rsync rsync
ensure_command flock util-linux

install -m 0755 "$ROOT/deploy/auto-update.sh" /usr/local/sbin/docker-ip-ssl-proxy-update
install -m 0644 "$ROOT/deploy/docker-ip-ssl-proxy-update.service" /etc/systemd/system/
install -m 0644 "$ROOT/deploy/docker-ip-ssl-proxy-update.timer" /etc/systemd/system/
cat > /etc/default/docker-ip-ssl-proxy-updater <<EOF
PROJECT_DIR=$ROOT
UPDATE_BRANCH=main
UPDATE_SCOPE=$SCOPE
EOF
# service固定调用全局脚本，避免项目更新过程中覆盖正在运行的脚本
sed -i 's#ExecStart=/opt/lnmpr/deploy/auto-update.sh#ExecStart=/usr/local/sbin/docker-ip-ssl-proxy-update#' /etc/systemd/system/docker-ip-ssl-proxy-update.service
systemctl daemon-reload
systemctl enable --now docker-ip-ssl-proxy-update.timer
systemctl start docker-ip-ssl-proxy-update.service
echo "自动更新已启用：scope=$SCOPE，每10分钟检查一次"
systemctl list-timers docker-ip-ssl-proxy-update.timer --no-pager
