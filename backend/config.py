"""读取并暴露 config.yaml 配置。所有可调参数集中在仓库根目录 config.yaml。"""
import os
import yaml

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve(p: str) -> str:
    if os.path.isabs(p):
        return p
    return os.path.normpath(os.path.join(_ROOT, p))


class Config:
    def __init__(self, path: str = None):
        path = path or os.path.join(_ROOT, "config.yaml")
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"未找到配置文件 {path}，请复制 config.example.yaml 为 config.yaml 并填写凭证"
            )
        with open(path, "r", encoding="utf-8") as f:
            self.raw = yaml.safe_load(f) or {}

        self.root = _ROOT
        srv = self.raw.get("server", {})
        self.backend_port = int(srv.get("backend_port", 8000))

        c = self.raw.get("cloud", {})
        self.api_key = c.get("api_key", "")
        self.secret_key = c.get("secret_key", "")
        self.token_url = c.get("token_url", "")
        self.submit_url = c.get("submit_url", "")
        self.result_url = c.get("result_url", "")
        self.manifest_version_id = c.get("manifest_version_id", "")
        self.use_local_manifest_as_fallback = bool(
            c.get("use_local_manifest_as_fallback", True)
        )
        self.submit_qps = float(c.get("submit_qps", 2))
        self.poll_interval_sec = int(c.get("poll_interval_sec", 30))
        self.poll_timeout_sec = int(c.get("poll_timeout_sec", 300))
        self.max_retries = int(c.get("max_retries", 2))
        self.recognize_use_ocr = bool(c.get("recognize_use_ocr", True))
        self.ocr_url = c.get("ocr_url", "https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic")

        p = self.raw.get("paths", {})
        self.annotations_dir = _resolve(p.get("annotations_dir", "./annotations"))
        self.parser_dir = _resolve(p.get("parser_dir", "./parser"))
        self.doc_dir = _resolve(p.get("doc_dir", "./doc"))
        self.storage_dir = _resolve(p.get("storage_dir", "./.data"))

        e = self.raw.get("eval", {})
        self.default_match_mode = e.get("default_match_mode", "exact")
        self.aggregate = e.get("aggregate", "micro")

        a = self.raw.get("auth", {})
        self.auth_username = a.get("username", "admin")
        self.auth_password = a.get("password", "changeme")  # 脱敏默认值，请在 config.yaml 的 auth 段覆盖

        # OneAPI（仅后端使用；绝不返回前端）。环境变量优先于 config.yaml。
        o = self.raw.get("oneapi", {})
        self.oneapi_key = os.environ.get("ONEAPI_KEY") or o.get("api_key", "")
        self.oneapi_base = os.environ.get("ONEAPI_BASE") or o.get("api_base", "")
        self.oneapi_model = os.environ.get("ONEAPI_MODEL") or o.get("model", "")

        os.makedirs(self.storage_dir, exist_ok=True)
        os.makedirs(os.path.join(self.storage_dir, "render"), exist_ok=True)
        os.makedirs(os.path.join(self.storage_dir, "extract"), exist_ok=True)


_cfg = None


def get_config() -> "Config":
    global _cfg
    if _cfg is None:
        _cfg = Config()
    return _cfg


def reload_config() -> "Config":
    """重新从 config.yaml 加载并替换缓存。"""
    global _cfg
    _cfg = Config()
    return _cfg


def _config_path() -> str:
    return os.path.join(_ROOT, "config.yaml")


def update_cloud_config(updates: dict) -> "Config":
    """合并更新 config.yaml 的 cloud 段并立即生效（重载缓存 + 清 token 缓存）。"""
    path = _config_path()
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    cloud = raw.get("cloud", {}) or {}
    for k, v in (updates or {}).items():
        if v is not None:
            cloud[k] = v
    raw["cloud"] = cloud
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False)
    try:
        from services import cloud_service
        cloud_service._token_cache["token"] = None
        cloud_service._token_cache["exp"] = 0
    except Exception:  # noqa
        pass
    return reload_config()
