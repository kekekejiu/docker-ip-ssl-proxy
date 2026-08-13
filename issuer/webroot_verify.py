"""webroot 验证模式：把校验文件写进已有 Web 服务的站点目录。

适用于宿主机 80 端口已被占用（例如已装宝塔/nginx）的情况，
此时签发容器不监听 80，只借用现成 Web 服务来提供校验文件。
"""

import contextlib
import os


@contextlib.contextmanager
def serve(webroot, routes):
    """把每个 URL 路径对应的内容写入 webroot，退出时清理。"""
    if not os.path.isdir(webroot):
        raise RuntimeError(
            "VERIFY_WEBROOT=%s 在容器内不存在。请确认已通过 volumes 挂载该目录" % webroot)

    written = []
    try:
        for url_path, content in routes.items():
            dest = os.path.join(webroot, url_path.lstrip("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w", encoding="utf-8") as fh:
                fh.write(content)
            os.chmod(dest, 0o644)
            written.append(dest)
            print("    [verify-webroot] 已写入 %s" % dest, flush=True)
        yield written
    finally:
        for path in written:
            try:
                os.remove(path)
                print("    [verify-webroot] 已清理 %s" % path, flush=True)
            except OSError:
                pass
