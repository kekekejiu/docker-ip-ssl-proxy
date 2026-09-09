#!/usr/bin/env python3
"""为非 Docker 部署补齐 ZeroSSL IP 证书的旧客户端兼容链。

服务端应发送三张证书：站点证书、ZeroSSL 中间证书、
Sectigo R46 x USERTrust RSA 交叉签名证书。
USERTrust 自签名根由客户端信任库提供，不由服务端发送。

用法：
  python3 fix_chain.py <fullchain.pem> [chain.pem]
"""

import os
import re
import subprocess
import sys

CROSS_SIGN_CERT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "SectigoPublicServerAuthenticationRootR46_USERTrust.pem",
)

_PEM_CERT_RE = re.compile(
    r"-----BEGIN CERTIFICATE-----\s+.*?\s+-----END CERTIFICATE-----",
    re.DOTALL,
)


def certificate_blocks(pem):
    return [block.strip() + "\n" for block in _PEM_CERT_RE.findall(pem or "")]


def load_cross_sign(path=CROSS_SIGN_CERT):
    with open(path, "r", encoding="utf-8") as fh:
        blocks = certificate_blocks(fh.read())
    if len(blocks) != 1:
        raise SystemExit("交叉签名证书文件无效: %s" % path)
    return blocks[0]


def build_chain(leaf_pem, chain_pem, cross_sign=None):
    """返回 (fullchain, chain)，顺序为叶证书、CA 链、交叉签名证书，并去重。"""
    leaves = certificate_blocks(leaf_pem)
    if not leaves:
        raise SystemExit("未找到站点证书")
    cross_sign = cross_sign or load_cross_sign()
    chain_ordered = []
    seen = set()
    for block in certificate_blocks(chain_pem) + [cross_sign]:
        key = block.strip()
        if key not in seen:
            chain_ordered.append(block)
            seen.add(key)
    return "".join(leaves[:1] + chain_ordered), "".join(chain_ordered)


def write_atomic(path, content, mode=0o644):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(content)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def verify_pem(path):
    proc = subprocess.run(["openssl", "x509", "-in", path, "-noout", "-subject"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit("生成的证书无法解析: %s" % proc.stderr.strip()[:300])


def repair(fullchain_path, chain_path=None):
    """就地补齐已有 fullchain；已包含交叉证书时不做修改。"""
    with open(fullchain_path, "r", encoding="utf-8") as fh:
        blocks = certificate_blocks(fh.read())
    if len(blocks) < 2:
        raise SystemExit("%s 至少应包含站点证书和中间证书" % fullchain_path)
    cross_sign = load_cross_sign()
    if cross_sign.strip() in {b.strip() for b in blocks}:
        print("已包含交叉签名证书，无需修改")
        return False
    fullchain, chain = build_chain(blocks[0], "".join(blocks[1:]), cross_sign)
    backup = fullchain_path + ".bak-r46"
    if not os.path.exists(backup):
        write_atomic(backup, "".join(blocks))
    write_atomic(fullchain_path, fullchain)
    verify_pem(fullchain_path)
    if chain_path:
        write_atomic(chain_path, chain)
    print("已补入 R46 -> USERTrust 交叉签名证书，共 %d 张"
          % len(certificate_blocks(fullchain)))
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    repair(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
