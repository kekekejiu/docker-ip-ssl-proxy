#!/usr/bin/env python3
"""容器启动时探测本机公网 IPv4，申请 ZeroSSL IP 证书，之后常驻自动续期。

证书按 <IP>.crt / <IP>.key / <IP>.chain.crt 命名写入 /certs。
验证阶段由本进程临时监听 80 端口，无需 nginx 配合。
"""

import datetime
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import http_verify
import webroot_verify
import zerossl

CERT_DIR = os.environ.get("CERT_DIR", "/certs")
STATE_DIR = os.environ.get("STATE_DIR", "/state")

def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("[%s] %s" % (ts, msg), flush=True)


def env_int(name, default):
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def detect_public_ipv4(timeout=8):
    """探测公网 IPv4。

    必须强制 IPv4：双栈机器上多数探测服务会优先返回 IPv6，而 ZeroSSL 不签 IPv6。
    Docker 用户自定义网络的内嵌 DNS(127.0.0.11) 在部分宿主上转发不可靠，
    因此先用免 DNS 的直连 IP 方式，失败再退回域名方式。
    """
    for ip in _detect_via_literal_ip(timeout):
        log("探测到公网 IPv4: %s" % ip)
        return ip
    for ip in _detect_via_hostname(timeout):
        log("探测到公网 IPv4: %s" % ip)
        return ip
    return None


def _detect_via_literal_ip(timeout):
    """直接连服务商 IP，完全绕开 DNS。"""
    import http.client
    # (IP, Host 头, 路径) —— 均为返回纯文本 IPv4 的服务
    endpoints = [
        ("1.1.1.1", "one.one.one.one", "/cdn-cgi/trace"),
        ("104.16.132.229", "www.cloudflare.com", "/cdn-cgi/trace"),
    ]
    for addr, host, path in endpoints:
        try:
            conn = http.client.HTTPSConnection(addr, 443, timeout=timeout)
            conn.request("GET", path, headers={"Host": host, "User-Agent": "curl/8"})
            body = conn.getresponse().read().decode("utf-8", "replace")
            conn.close()
            for line in body.splitlines():
                if line.startswith("ip="):
                    candidate = line[3:].strip()
                    if is_ipv4(candidate):
                        yield candidate
                        return
        except Exception as exc:
            log("  直连 %s 探测失败: %s" % (host, exc))


def _detect_via_hostname(timeout):
    """退路：走域名解析，但把 socket 限制为 IPv4。"""
    import socket
    import urllib.request

    orig = socket.getaddrinfo

    def ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
        return orig(host, port, socket.AF_INET, type, proto, flags)

    socket.getaddrinfo = ipv4_only
    try:
        for url in ("https://api.ipify.org", "https://ipv4.icanhazip.com",
                    "https://ifconfig.me/ip"):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    candidate = resp.read().decode().strip()
                if is_ipv4(candidate):
                    yield candidate
                    return
            except Exception as exc:
                log("  %s 探测失败: %s" % (url, exc))
    finally:
        socket.getaddrinfo = orig


def is_ipv4(value):
    import socket
    try:
        socket.inet_pton(socket.AF_INET, value)
        return True
    except (OSError, ValueError):
        return False


def load_settings():
    key = (os.environ.get("ZEROSSL_API_KEY") or "").strip()
    if not key:
        die("未设置 ZEROSSL_API_KEY，请在 .env 中填写你的 ZeroSSL API access key")

    ip = (os.environ.get("CERT_IP") or "").strip()
    if ip and not is_ipv4(ip):
        die("CERT_IP=%s 不是合法 IPv4。ZeroSSL 不签发 IPv6 证书" % ip)
    if not ip:
        ip = detect_public_ipv4()
        if not ip:
            die("无法自动探测公网 IPv4，请在 .env 里显式设置 CERT_IP")

    return {
        "api_key": key,
        "ip": ip,
        "validity_days": env_int("CERT_VALIDITY_DAYS", 90),
        "renew_before_days": env_int("RENEW_BEFORE_DAYS", 30),
        "check_interval": env_int("CHECK_INTERVAL_HOURS", 12) * 3600,
        "verify_port": env_int("VERIFY_PORT", 80),
        "verify_mode": (os.environ.get("VERIFY_MODE") or "standalone").strip().lower(),
        "verify_webroot": (os.environ.get("VERIFY_WEBROOT") or "").strip(),
    }


def die(msg):
    log("致命错误: %s" % msg)
    raise SystemExit(1)

def cert_paths(ip):
    """CERT_NAME 为空时按 IP 命名；设为 ip 则输出 ip.crt / ip.key。"""
    stem = (os.environ.get("CERT_NAME") or "").strip() or ip
    return {
        "crt": os.path.join(CERT_DIR, "%s.crt" % stem),
        "key": os.path.join(CERT_DIR, "%s.key" % stem),
        "chain": os.path.join(CERT_DIR, "%s.chain.crt" % stem),
    }


def days_left(crt_path, ip):
    """返回本地证书剩余天数；证书不存在或 SAN 不含该 IP 时返回 None。"""
    import subprocess
    if not os.path.exists(crt_path):
        return None
    proc = subprocess.run(["openssl", "x509", "-in", crt_path, "-noout", "-text", "-enddate"],
                          capture_output=True, text=True)
    if proc.returncode != 0 or ("IP Address:%s" % ip) not in proc.stdout:
        return None
    for line in proc.stdout.splitlines():
        if line.startswith("notAfter="):
            raw = line.split("=", 1)[1].strip()
            try:
                exp = datetime.datetime.strptime(raw, "%b %d %H:%M:%S %Y %Z")
            except ValueError:
                return None
            exp = exp.replace(tzinfo=datetime.timezone.utc)
            return (exp - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 86400.0
    return None


def write_atomic(path, content, mode=0o644):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(content)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def reload_nginx():
    """证书换新后让 nginx 重载。

    优先通过挂载的 docker socket 直接对目标容器执行 nginx -s reload；
    未挂载 socket 时退回写信号文件，由 nginx 容器内的 reloader 轮询。
    """
    target = (os.environ.get("NGINX_CONTAINER") or "").strip()
    if target and os.path.exists("/var/run/docker.sock"):
        if docker_exec_reload(target):
            return
        log("  socket 重载失败，退回信号文件方式")

    write_atomic(os.path.join(CERT_DIR, ".reload"),
                 datetime.datetime.now().isoformat() + "\n")
    log("  已写入 reload 信号")


def docker_exec_reload(container):
    """经 Docker Engine API 在目标容器内执行 nginx -s reload。"""
    import http.client
    import json as _json

    def api(method, path, body=None):
        conn = http.client.HTTPConnection("localhost", timeout=30)
        conn.sock = _unix_socket("/var/run/docker.sock")
        payload = _json.dumps(body).encode() if body is not None else None
        conn.request(method, path, body=payload,
                     headers={"Content-Type": "application/json", "Host": "docker"})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    try:
        status, data = api("POST", "/containers/%s/exec" % container,
                           {"AttachStdout": True, "AttachStderr": True,
                            "Cmd": ["nginx", "-s", "reload"]})
        if status not in (200, 201):
            log("  创建 exec 失败 (HTTP %s): %s" % (status, data[:200]))
            return False
        exec_id = _json.loads(data)["Id"]
        status, data = api("POST", "/exec/%s/start" % exec_id, {"Detach": False, "Tty": False})
        if status != 200:
            log("  启动 exec 失败 (HTTP %s)" % status)
            return False
        log("  已通知容器 %s 重载 nginx" % container)
        return True
    except Exception as exc:
        log("  docker socket 重载异常: %s" % exc)
        return False


def _unix_socket(path):
    import socket
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(30)
    sock.connect(path)
    return sock

def wait_until_issued(api_key, cert_id, timeout=900, interval=15):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        obj = zerossl.get_certificate(api_key, cert_id)
        status = obj.get("status")
        if status != last:
            log("  状态: %s" % status)
            last = status
        if status == "issued":
            return obj
        if status in ("cancelled", "revoked", "expired"):
            raise zerossl.ZeroSSLError("证书进入终态 %s" % status)
        time.sleep(interval)
    raise zerossl.ZeroSSLError("等待签发超时")


def issue_once(cfg):
    ip, api_key = cfg["ip"], cfg["api_key"]
    paths = cert_paths(ip)
    key_tmp = paths["key"] + ".new"

    log("1/6 生成私钥与 CSR (CN=%s)" % ip)
    csr = zerossl.generate_key_and_csr(ip, key_tmp)
    os.chmod(key_tmp, 0o600)

    log("2/6 创建 %d 天证书" % cfg["validity_days"])
    cert = zerossl.create_certificate(api_key, ip, csr, cfg["validity_days"])
    cert_id = cert["id"]
    log("  证书 ID: %s" % cert_id)

    url, content = zerossl.extract_http_challenge(cert, ip)
    url_path = "/" + url.split("/", 3)[-1]

    if cfg["verify_mode"] == "webroot":
        log("3/6 webroot 模式：写入校验文件到 %s" % cfg["verify_webroot"])
        verifier = webroot_verify.serve(cfg["verify_webroot"], {url_path: content})
    else:
        log("3/6 standalone 模式：临时监听 %d 端口" % cfg["verify_port"])
        verifier = http_verify.serve(cfg["verify_port"], {url_path: content})

    with verifier:
        ok, detail = http_verify.self_check(url, content)
        log("  自检: %s (%s)" % ("通过" if ok else "未通过", detail))
        if not ok:
            if os.path.exists(key_tmp):
                os.remove(key_tmp)
            hint = ("webroot 模式下请确认该目录确实是 80 端口站点的根目录，"
                    "且站点没有强制跳转 HTTPS（ZeroSSL 不接受 3xx）"
                    if cfg["verify_mode"] == "webroot"
                    else "请确认防火墙/安全组已放通 80 端口入站")
            raise zerossl.ZeroSSLError(
                "外部无法访问 http://%s%s —— %s" % (ip, url_path, hint))

        log("4/6 触发验证 (HTTP_CSR_HASH)")
        zerossl.start_validation(api_key, cert_id)

        log("5/6 等待签发")
        final = wait_until_issued(api_key, cert_id)
    log("  验证资源已释放")

    log("6/6 写入 %s" % CERT_DIR)
    crt, chain = zerossl.download_certificate(api_key, cert_id)
    write_atomic(paths["crt"], crt.rstrip() + "\n" + chain.rstrip() + "\n")
    write_atomic(paths["chain"], chain.rstrip() + "\n")
    os.replace(key_tmp, paths["key"])
    os.chmod(paths["key"], 0o600)
    for label, p in (("证书", paths["crt"]), ("私钥", paths["key"])):
        log("  %s -> %s" % (label, p))

    reload_nginx()
    log("完成，到期时间 %s" % final.get("expires"))
    return final

def main():
    os.makedirs(CERT_DIR, exist_ok=True)
    os.makedirs(STATE_DIR, exist_ok=True)

    cfg = load_settings()
    log("目标 IP: %s | 有效期 %d 天 | 剩余 %d 天内续期 | 每 %d 小时检查"
        % (cfg["ip"], cfg["validity_days"], cfg["renew_before_days"], cfg["check_interval"] // 3600))

    # 把最终确定的 IP 写出来，供 nginx 容器在自动探测模式下读取
    write_atomic(os.path.join(CERT_DIR, ".ip"), cfg["ip"] + "\n")

    paths = cert_paths(cfg["ip"])
    force = os.environ.get("FORCE_ISSUE", "").lower() in ("1", "true", "yes")

    while True:
        left = days_left(paths["crt"], cfg["ip"])
        if force:
            reason = "FORCE_ISSUE 已启用"
        elif left is None:
            reason = "尚无该 IP 的有效证书"
        elif left <= cfg["renew_before_days"]:
            reason = "剩余 %.1f 天，已达续期阈值" % left
        else:
            log("证书剩余 %.1f 天，无需续期。%d 小时后再次检查"
                % (left, cfg["check_interval"] // 3600))
            time.sleep(cfg["check_interval"])
            continue

        log("开始签发（原因: %s）" % reason)
        try:
            issue_once(cfg)
            force = False
        except zerossl.ZeroSSLError as exc:
            log("签发失败: %s" % exc)
            log("将在 30 分钟后重试")
            time.sleep(1800)
            continue
        except Exception as exc:
            log("未预期错误: %r" % exc)
            time.sleep(1800)
            continue

        time.sleep(cfg["check_interval"])

if __name__ == "__main__":
    sys.exit(main())
