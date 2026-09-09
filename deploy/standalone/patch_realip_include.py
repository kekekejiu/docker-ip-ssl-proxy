import io
import os
import sys

INCLUDE = "    include /www/server/panel/vhost/nginx/realip/proxy-realip.conf;\n"
ANCHOR = "    #SSL-END\n"


def patch(path):
    with io.open(path, encoding="utf-8") as fh:
        src = fh.read()
    if "realip/proxy-realip.conf" in src:
        print("already-included %s" % path)
        return False
    if ANCHOR not in src:
        print("anchor-not-found %s" % path)
        return False
    backup = path + ".bak-realip"
    if not os.path.exists(backup):
        with io.open(backup, "w", encoding="utf-8") as fh:
            fh.write(src)
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(src.replace(ANCHOR, ANCHOR + INCLUDE, 1))
    print("patched %s" % path)
    return True


if __name__ == "__main__":
    for target in sys.argv[1:]:
        patch(target)
