"""ZeroSSL REST API 客户端，面向 IP 地址证书（HTTP 文件验证）。

仅使用标准库，避免在宝塔环境里引入额外依赖。
API 文档: https://zerossl.com/documentation/api
"""

import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.zerossl.com"
USER_AGENT = "zerossl-ip-cert/1.0 (+baota)"


class ZeroSSLError(RuntimeError):
    pass


def _request(method, path, access_key, data=None, timeout=60):
    url = "%s%s?%s" % (API_BASE, path, urllib.parse.urlencode({"access_key": access_key}))
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("User-Agent", USER_AGENT)
    if body:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        raise ZeroSSLError("HTTP %s: %s" % (exc.code, raw[:800])) from exc
    except urllib.error.URLError as exc:
        raise ZeroSSLError("网络请求失败: %s" % exc.reason) from exc
    return raw


def _request_json(method, path, access_key, data=None, timeout=60):
    raw = _request(method, path, access_key, data=data, timeout=timeout)
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise ZeroSSLError("响应不是合法 JSON: %s" % raw[:500]) from exc
    # ZeroSSL 在业务错误时仍可能返回 HTTP 200，需要检查 success 字段
    if isinstance(payload, dict) and payload.get("success") is False:
        raise ZeroSSLError("API 返回错误: %s" % json.dumps(payload.get("error", payload), ensure_ascii=False))
    return payload


def generate_key_and_csr(ip, key_path, key_bits=2048):
    """生成新私钥并返回 CSR 文本。CN 与 SAN 都必须是该 IP。"""
    cmd = [
        "openssl", "req", "-new", "-nodes",
        "-newkey", "rsa:%d" % key_bits,
        "-keyout", key_path,
        "-subj", "/CN=%s" % ip,
        "-addext", "subjectAltName=IP:%s" % ip,
        "-outform", "PEM",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ZeroSSLError("生成 CSR 失败: %s" % proc.stderr.strip()[:500])
    return proc.stdout


def create_certificate(access_key, ip, csr, validity_days=90):
    data = {
        "certificate_domains": ip,
        "certificate_csr": csr,
        "certificate_validity_days": str(validity_days),
        "strict_domains": "1",
    }
    return _request_json("POST", "/certificates", access_key, data=data)


def extract_http_challenge(cert_obj, ip):
    """从创建响应中取出 HTTP 文件验证的 URL 与内容。"""
    methods = (cert_obj.get("validation") or {}).get("other_methods") or {}
    entry = methods.get(ip)
    if entry is None and len(methods) == 1:
        entry = next(iter(methods.values()))
    if not entry:
        raise ZeroSSLError("响应中没有 %s 的文件验证信息: %s" % (ip, json.dumps(methods)[:500]))
    url = entry.get("file_validation_url_http")
    content = entry.get("file_validation_content")
    if not url or not content:
        raise ZeroSSLError("文件验证字段缺失: %s" % json.dumps(entry)[:500])
    if isinstance(content, str):
        content = [content]
    return url, "\n".join(content) + "\n"


def start_validation(access_key, cert_id):
    return _request_json(
        "POST", "/certificates/%s/challenges" % cert_id, access_key,
        data={"validation_method": "HTTP_CSR_HASH"},
    )


def get_certificate(access_key, cert_id):
    return _request_json("GET", "/certificates/%s" % cert_id, access_key)


def download_certificate(access_key, cert_id):
    """返回 (certificate.crt, ca_bundle.crt)。"""
    payload = _request_json("GET", "/certificates/%s/download/json" % cert_id, access_key)
    crt = payload.get("certificate.crt")
    chain = payload.get("ca_bundle.crt") or ""
    if not crt:
        raise ZeroSSLError("下载响应缺少 certificate.crt: %s" % json.dumps(payload)[:300])
    return crt, chain


def cancel_certificate(access_key, cert_id):
    return _request_json("POST", "/certificates/%s/cancel" % cert_id, access_key)
