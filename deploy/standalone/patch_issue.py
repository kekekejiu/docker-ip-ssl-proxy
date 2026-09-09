import io
import os
import py_compile

TARGET = "/www/server/zerossl-ip/issue.py"

OLD = (
    '    crt, chain = zerossl.download_certificate(api_key, cert_id)\n'
    '    write_atomic(paths["crt"], crt.rstrip() + "\\n" + chain.rstrip() + "\\n")\n'
    '    write_atomic(paths["chain"], chain.rstrip() + "\\n")\n'
)

NEW = (
    '    crt, chain = zerossl.download_certificate(api_key, cert_id)\n'
    '    import fix_chain\n'
    '    fullchain, chain_only = fix_chain.build_chain(crt, chain)\n'
    '    write_atomic(paths["crt"], fullchain)\n'
    '    write_atomic(paths["chain"], chain_only)\n'
)

with io.open(TARGET, encoding="utf-8") as fh:
    src = fh.read()

if "fix_chain" in src:
    print("already-patched")
elif OLD not in src:
    raise SystemExit("anchor-not-found")
else:
    backup = TARGET + ".bak-r46"
    if not os.path.exists(backup):
        with io.open(backup, "w", encoding="utf-8") as fh:
            fh.write(src)
    with io.open(TARGET, "w", encoding="utf-8") as fh:
        fh.write(src.replace(OLD, NEW, 1))
    py_compile.compile(TARGET, doraise=True)
    print("patched")
