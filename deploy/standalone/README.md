# 非 Docker 部署的证书链兼容修复

适用于宝塔或 systemd 环境下直接用 `issue.py` 签发 ZeroSSL IP 证书的节点。

服务端需要发送三张证书：

```text
站点 IP 证书
└─ ZeroSSL RSA DV SSL CA 2
   └─ Sectigo Public Server Authentication Root R46（USERTrust 交叉签名）
```

`USERTrust RSA Certification Authority` 由客户端信任库提供，不由服务端发送。

## 一次性修复已有证书

```bash
python3 fix_chain.py /www/server/zerossl-ip/cert/fullchain.pem \
                     /www/server/zerossl-ip/cert/chain.pem
/www/server/nginx/sbin/nginx -t && /www/server/nginx/sbin/nginx -s reload
```

脚本会在首次修改前生成 `fullchain.pem.bak-r46` 备份，重复执行不会重复追加。

## 让续期后自动补链

把 `fix_chain.py` 与交叉证书放到 `issue.py` 同级目录，然后修改 `issue.py`
中写入证书的那一行：

```python
    crt, chain = zerossl.download_certificate(api_key, cert_id)
    import fix_chain
    fullchain, chain_only = fix_chain.build_chain(crt, chain)
    write_atomic(paths["crt"], fullchain)
    write_atomic(paths["chain"], chain_only)
```

## 验证

```bash
openssl s_client -connect <IP>:443 -servername <IP> -verify_return_error </dev/null
```

结果应为 `Verify return code: 0 (ok)`，且链中包含三张证书。
