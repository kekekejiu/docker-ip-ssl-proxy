#!/usr/bin/env bash
# docker-ip-ssl-proxy 受控自动更新器
# UPDATE_SCOPE=full: 更新完整程序并重建 issuer/nginx/human-gate
# UPDATE_SCOPE=cert-only: 仅更新 issuer 与更新器，不安装/启动 human-gate，不修改 nginx 配置
set -Eeuo pipefail

ROOT="${PROJECT_DIR:-/opt/lnmpr}"
BRANCH="${UPDATE_BRANCH:-main}"
SCOPE="${UPDATE_SCOPE:-full}"
LOCK=/run/lock/docker-ip-ssl-proxy-update.lock
BACKUP_ROOT="$ROOT/.updates"
STATE_FILE="$BACKUP_ROOT/applied-$SCOPE"
LOG_PREFIX="[updater:$SCOPE]"

log(){ echo "$(date '+%F %T') $LOG_PREFIX $*"; }
exec 9>"$LOCK"
flock -n 9 || { log "已有更新任务在运行，跳过"; exit 0; }

case "$SCOPE" in full|cert-only) ;; *) log "非法 UPDATE_SCOPE=$SCOPE"; exit 2;; esac
cd "$ROOT" || { log "项目目录不存在: $ROOT"; exit 1; }
[ -d .git ] || { log "不是 git 仓库: $ROOT"; exit 1; }
mkdir -p "$BACKUP_ROOT"

fetch_ok=0
for attempt in 1 2 3; do
  if git fetch -q origin "$BRANCH"; then fetch_ok=1; break; fi
  log "git fetch 第${attempt}次失败，稍后重试"
  sleep $((attempt * 5))
done
if [ "$fetch_ok" -ne 1 ]; then
  log "GitHub暂时不可达，跳过本轮并保留当前版本"
  exit 0
fi
TARGET=$(git rev-parse "origin/$BRANCH")
CURRENT=$(cat "$STATE_FILE" 2>/dev/null || git rev-parse HEAD)
[ "$CURRENT" = "$TARGET" ] && { log "已是最新版 ${TARGET:0:7}"; exit 0; }

STAMP=$(date +%Y%m%d%H%M%S)
STAGE=$(mktemp -d /tmp/lnmpr-update.XXXXXX)
BACKUP="$BACKUP_ROOT/$STAMP-$SCOPE"
cleanup(){ git worktree remove -f "$STAGE" >/dev/null 2>&1 || rm -rf "$STAGE"; }
trap cleanup EXIT

log "发现新版本 ${CURRENT:0:7} -> ${TARGET:0:7}"
git worktree add -q --detach "$STAGE" "$TARGET" || { log "创建临时worktree失败"; exit 1; }
mkdir -p "$BACKUP"

if [ "$SCOPE" = full ]; then
  cp -a .env "$STAGE/.env" 2>/dev/null || true
  (cd "$STAGE" && docker compose config >/dev/null) || { log "新版 compose 校验失败"; exit 1; }
  # 备份程序快照和本机环境；持久化目录始终原地保留。
  git archive HEAD | tar -x -C "$BACKUP"
  cp -a .env "$BACKUP/.env" 2>/dev/null || true
  rsync -a --delete \
    --exclude '.git' --exclude '.updates/' --exclude '.env' \
    --exclude 'nginx/http.d/' --exclude 'nginx/stream.d/' \
    --exclude 'nginx/cert/' --exclude 'nginx/log/' \
    --exclude 'issuer/state/' --exclude 'human-gate/data/' \
    "$STAGE/" "$ROOT/"
else
  # API 后端节点：只更新证书签发器和自动更新器，绝不碰 compose/nginx/human-gate。
  cp -a issuer "$BACKUP/issuer"
  [ -d deploy ] && cp -a deploy "$BACKUP/deploy" || true
  mkdir -p "$ROOT/issuer" "$ROOT/deploy"
  rsync -a --delete --exclude 'state/' "$STAGE/issuer/" "$ROOT/issuer/"
  rsync -a "$STAGE/deploy/" "$ROOT/deploy/"
fi

rollback(){
  log "健康检查失败，回滚到 ${CURRENT:0:7}"
  if [ "$SCOPE" = full ]; then
    rsync -a --delete --exclude '.env' --exclude 'nginx/http.d/' --exclude 'nginx/stream.d/' \
      --exclude 'nginx/cert/' --exclude 'nginx/log/' --exclude 'issuer/state/' --exclude 'human-gate/data/' \
      "$BACKUP/" "$ROOT/"
    [ -f "$BACKUP/.env" ] && cp -a "$BACKUP/.env" "$ROOT/.env"
    docker compose up -d --build >/dev/null 2>&1 || true
    docker compose up -d --force-recreate human-gate >/dev/null 2>&1 || true
  else
    rm -rf "$ROOT/issuer"; cp -a "$BACKUP/issuer" "$ROOT/issuer"
    docker compose up -d --build issuer >/dev/null 2>&1 || true
  fi
}

if [ "$SCOPE" = full ]; then
  docker compose up -d --build || { rollback; exit 1; }
  docker compose up -d --force-recreate human-gate || { rollback; exit 1; }
  sleep 8
  RUNNING=$(docker compose ps --status running --services)
  if ! grep -qx nginx <<<"$RUNNING" || ! grep -qx issuer <<<"$RUNNING" || ! grep -qx human-gate <<<"$RUNNING" || \
     ! docker exec nginx nginx -t >/dev/null 2>&1 || \
     ! docker exec nginx wget -qO- --timeout=5 http://127.0.0.1:9200/__gate/healthz | grep -q '^ok$'; then
    rollback; exit 1
  fi
else
  docker compose up -d --build issuer || { rollback; exit 1; }
  sleep 5
  docker compose ps --status running --services | grep -qx issuer || { rollback; exit 1; }
  # cert-only 节点明确禁止出现 human-gate 容器。
  if docker ps --format '{{.Names}}' | grep -qx human-gate; then
    log "检测到禁止的 human-gate 容器"; rollback; exit 1
  fi
fi

printf '%s\n' "$TARGET" > "$STATE_FILE"
# 更新全局执行副本，使下一轮定时任务使用新版更新器。
if [ -f "$ROOT/deploy/auto-update.sh" ]; then
  install -m 0755 "$ROOT/deploy/auto-update.sh" /usr/local/sbin/docker-ip-ssl-proxy-update
fi
log "更新成功 ${TARGET:0:7}；本机配置/证书/密钥均保留"
