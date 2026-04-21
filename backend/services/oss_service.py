"""
阿里云 OSS 上传服务
图片先上传到 OSS，前端通过返回的 URL 直接访问。
"""
import hashlib
import random
import string
import logging
import os
from datetime import datetime

logger = logging.getLogger("contest_robot.oss")

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    try:
        import alibabacloud_oss_v2 as oss
    except ImportError:
        logger.warning("alibabacloud-oss-v2 未安装，OSS 上传不可用")
        return None

    ak_id = os.getenv("OSS_ACCESS_KEY_ID")
    ak_secret = os.getenv("OSS_ACCESS_KEY_SECRET")
    region = os.getenv("OSS_REGION", "cn-guangzhou")
    endpoint = os.getenv("OSS_ENDPOINT", "http://object.intuly.com")
    use_cname = os.getenv("OSS_USE_CNAME", "true").lower() in ("true", "1", "yes")

    if not ak_id or not ak_secret:
        logger.warning("OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET 未配置")
        return None

    cfg = oss.config.load_default()
    cfg.credentials_provider = oss.credentials.StaticCredentialsProvider(ak_id, ak_secret)
    cfg.region = region
    cfg.endpoint = endpoint
    cfg.use_cname = use_cname
    _client = oss.Client(cfg)
    logger.info("OSS Client 初始化完成, endpoint=%s", endpoint)
    return _client


def _object_key(original_filename: str) -> str:
    ext = original_filename.rsplit(".", 1)[-1] if "." in original_filename else "png"
    now = datetime.now().strftime("%Y%m%d%H%M%S")
    rand = "".join(random.choices(string.hexdigits[:16], k=16))
    raw = f"{now}_{rand}_{original_filename}"
    md5 = hashlib.md5(raw.encode()).hexdigest()
    prefix = os.getenv("OSS_PATH", "ai/img/build")
    return f"{prefix}/{md5[:2]}/{md5[2:4]}/{md5}.{ext}"


def upload_local_file(local_path: str) -> str | None:
    """
    把本地文件上传到 OSS，返回公开可访问的 URL。
    如果 OSS 不可用则返回 None。
    """
    client = _get_client()
    if client is None:
        return None

    import alibabacloud_oss_v2 as oss

    bucket = os.getenv("OSS_BUCKET_NAME", "aichord-test")
    endpoint = os.getenv("OSS_ENDPOINT", "http://object.intuly.com")
    filename = os.path.basename(local_path)
    key = _object_key(filename)

    try:
        with open(local_path, "rb") as f:
            result = client.put_object(oss.PutObjectRequest(
                bucket=bucket,
                key=key,
                body=f,
                acl="public-read",
            ))
        if result and hasattr(result, "status_code") and result.status_code == 200:
            url = f"{endpoint}/{key}"
            logger.debug("OSS 上传成功: %s -> %s", filename, url)
            return url
        else:
            logger.error("OSS 上传返回异常: status=%s", getattr(result, "status_code", "?"))
            return None
    except Exception as e:
        logger.error("OSS 上传失败 %s: %s", filename, e)
        return None


_url_cache: dict[str, str] = {}


def upload_images_to_oss(image_paths: list[str]) -> dict[str, str]:
    """
    批量上传图片到 OSS。
    返回 {本地路径: OSS URL} 映射。已上传过的走内存缓存。
    """
    result = {}
    for path in image_paths:
        if path in _url_cache:
            result[path] = _url_cache[path]
            continue
        url = upload_local_file(path)
        if url:
            _url_cache[path] = url
            result[path] = url
    return result
