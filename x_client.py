from __future__ import annotations

from config import get_env, get_required_env

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def get_x_cookies(required: bool = False) -> dict[str, str]:
    getter = get_required_env if required else get_env
    auth_token = getter("X_AUTH_TOKEN", "") if not required else getter("X_AUTH_TOKEN")
    ct0 = getter("X_CT0", "") if not required else getter("X_CT0")
    twid = getter("X_TWID", "") if not required else getter("X_TWID")
    return {
        "auth_token": auth_token or "",
        "ct0": ct0 or "",
        "twid": twid or "",
    }


def has_required_x_cookies(cookies: dict[str, str]) -> bool:
    return bool(cookies.get("auth_token") and cookies.get("ct0"))


def build_x_headers(
    cookies: dict[str, str],
    *,
    referer: str = "https://x.com",
    include_language: bool = True,
) -> dict[str, str]:
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items() if v)
    headers = {
        "Authorization": get_required_env("X_BEARER_TOKEN"),
        "Cookie": cookie_str,
        "X-Csrf-Token": cookies.get("ct0", ""),
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Referer": referer,
    }
    if include_language:
        headers["Accept-Language"] = "en-US,en;q=0.9"
        headers["X-Twitter-Active-User"] = "yes"
        headers["X-Twitter-Client-Language"] = "en"
    return headers
