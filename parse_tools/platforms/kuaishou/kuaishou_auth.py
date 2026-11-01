"""
快手登录凭证

重要：网页扫码会刷新 passToken，官方机制下经常挤下线手机 App。
产品侧应优先「粘贴已有 www Cookie」，扫码仅作小号备选。

扫码实现（备选）：
- 主 sid：kuaishou.server.webday7
- 回退：kuaishou.server.web
- 登录完成后必须通过 www GraphQL 校验才算成功
"""
from __future__ import annotations

import logging
import re
import threading
import time

import requests
from flask import Blueprint, jsonify

from parse_tools.core.config import DATA_DIR, get_proxies_dict, get_settings, save_settings

logger = logging.getLogger(__name__)

kuaishou_auth_bp = Blueprint("kuaishou_auth", __name__, url_prefix="/api/kuaishou/auth")

# 与官方网页版一致：webday7 优先，避免创作者平台互踢手机
SID_WEBDAY7 = "kuaishou.server.webday7"
SID_WWW = "kuaishou.server.web"
# 仅作极端回退（可能踢 App），默认路径不走
SID_CP = "kuaishou.web.cp.api"

QR_START = "https://id.kuaishou.com/rest/c/infra/ks/qr/start"
QR_SCAN = "https://id.kuaishou.com/rest/c/infra/ks/qr/scanResult"
QR_ACCEPT = "https://id.kuaishou.com/rest/c/infra/ks/qr/acceptResult"
QR_CALLBACK = "https://id.kuaishou.com/pass/kuaishou/login/qr/callback"
QR_VERIFY = "https://www.kuaishou.com/account/login/api/verifyToken"
QR_STS = "https://www.kuaishou.com/rest/infra/sts"

LOGIN_MARKER_KEYS = {
    "passToken",
    "kuaishou.server.webday7_st",
    "kuaishou.server.web_st",
    "kuaishou.web.cp.api_st",
    "userId",
}

_login_state = {
    "status": "idle",
    "message": "",
    "cookie": "",
    "qrcode": "",
}
_login_lock = threading.Lock()
_cancel_event = threading.Event()
_worker_thread = None
_login_expired = False


def set_login_expired(expired: bool = True):
    global _login_expired
    _login_expired = expired


def _extract_user_id(cookie_str: str) -> str:
    m = re.search(r"(?:^|;\s*)userId=([^;]+)", cookie_str)
    return m.group(1).strip() if m else ""


def _set_state(status: str, message: str = "", cookie: str | None = None, qrcode: str | None = None):
    with _login_lock:
        _login_state["status"] = status
        _login_state["message"] = message
        if cookie is not None:
            _login_state["cookie"] = cookie
        if qrcode is not None:
            _login_state["qrcode"] = qrcode


def _api_err(payload: dict, fallback: str) -> str:
    return (
        (payload or {}).get("error_msg")
        or (payload or {}).get("errorMsg")
        or (payload or {}).get("message")
        or fallback
    )


def _serialize_jar(session: requests.Session) -> str:
    cookie_dict = {}
    for c in session.cookies:
        name = (c.name or "").strip()
        value = (c.value or "").strip()
        if not name or not value:
            continue
        domain = (c.domain or "").strip().lstrip(".").lower()
        if not domain or domain.endswith("kuaishou.com"):
            cookie_dict[name] = value
    return "; ".join(f"{k}={v}" for k, v in cookie_dict.items())


def _has_login_markers(cookie_str: str) -> bool:
    return bool(cookie_str) and any(k in cookie_str for k in LOGIN_MARKER_KEYS)


def _merge_auth_payload_into_cookies(session: requests.Session, payload: dict) -> None:
    """把 callback/verify/sts JSON 里的 st/ph/passToken/userId 写入 CookieJar（常不在 Set-Cookie）。"""
    if not isinstance(payload, dict):
        return
    for k, v in payload.items():
        if v is None or v == "":
            continue
        key = str(k)
        if not (key.endswith("_st") or key.endswith("_ph") or key in ("passToken", "userId", "bUserId")):
            continue
        try:
            session.cookies.set(key, str(v), domain=".kuaishou.com", path="/")
        except Exception:
            session.cookies.set(key, str(v))


def _session_from_cookie_str(cookie_str: str) -> requests.Session:
    session = _new_session()
    session.headers.update({
        "Origin": "https://www.kuaishou.com",
        "Referer": "https://www.kuaishou.com/",
    })
    for part in (cookie_str or "").split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        k, _, v = part.partition("=")
        k, v = k.strip(), v.strip()
        if k and v:
            try:
                session.cookies.set(k, v, domain=".kuaishou.com", path="/")
            except Exception:
                session.cookies.set(k, v)
    return session


def validate_kuaishou_www_login(cookie_str: str = "", session: requests.Session | None = None) -> tuple[bool, str, str]:
    """探测 www 是否真正登录。返回 (ok, user_id, message)。

    重要：不要在状态检查里调用 passToken 换票接口。
    那是登录换票 API，频繁打会触发「账号异常」并把会话踢掉。
    这里只读 GraphQL userInfo 做轻量探测。
    """
    try:
        s = session or _session_from_cookie_str(cookie_str)
        # 仅 GraphQL：真正的 www 登录态（schema 已不含 viewerIsOwner）
        gr = s.post(
            "https://www.kuaishou.com/graphql",
            json={
                "operationName": "userBasicInfo",
                "variables": {},
                "query": "query userBasicInfo { userInfo { id name } }",
            },
            headers={
                **s.headers,
                "Content-Type": "application/json",
                "Origin": "https://www.kuaishou.com",
                "Referer": "https://www.kuaishou.com/new-reco",
            },
            timeout=12,
        )
        data = gr.json() if gr.content else {}
        info = ((data.get("data") or {}).get("userInfo")) or {}
        uid = str(info.get("id") or "").strip()
        uname = str(info.get("name") or "").strip()
        if uid and uid.lower() != "null":
            tip = f"登录有效 (UID: {uid}"
            if uname:
                tip += f" / {uname}"
            tip += ")"
            return True, uid, tip
        # 明确未登录
        errs = data.get("errors") or []
        if any(
            isinstance(e, dict)
            and (
                "No Login" in str(e)
                or (e.get("extensions") or {}).get("code") == "UNAUTHENTICATED"
            )
            for e in errs
        ):
            return False, "", "www 未登录（Cookie 无效），请重新获取登录"
        if info.get("id") is None and "userInfo" in str(data.get("data")):
            return False, "", "www 未识别登录态，请重新获取登录"
        # 兜底：有 userId cookie 也算弱登录，但点赞页仍可能失败
        weak = _extract_user_id(cookie_str or _serialize_jar(s))
        if weak and _has_login_markers(cookie_str or _serialize_jar(s)):
            return False, weak, "登录凭证不完整，www 未生效，请重新获取登录"
        return False, "", "未检测到有效快手登录"
    except Exception as e:
        logger.info("validate ks login failed: %s", e)
        return False, "", f"登录校验失败: {e}"


def _new_session() -> requests.Session:
    session = requests.Session()
    # 对齐 KSQRcode：QR 相关接口用 id.kuaishou.com 的 Origin/Referer
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Origin": "https://id.kuaishou.com",
        "Referer": "https://id.kuaishou.com/",
    })
    proxies = get_proxies_dict()
    if proxies:
        session.proxies.update(proxies)
    return session


def _complete_login(session: requests.Session, sid: str, token: str, signature: str) -> None:
    """扫码成功后的换票：accept → callback → verify/sts（对齐 GitHub 方案）"""
    _set_state("scanned", "已扫码，请在手机上点击确认登录...")

    accept = session.post(
        QR_ACCEPT,
        data={"qrLoginToken": token, "qrLoginSignature": signature, "sid": sid},
        timeout=120,
    ).json()
    logger.info("ks acceptResult sid=%s resp=%s", sid, accept)
    if accept.get("result") != 1:
        raise RuntimeError(_api_err(accept, "确认登录失败，请在手机点确认后重试"))

    qr_token = accept.get("qrToken")
    if not qr_token:
        raise RuntimeError(f"未返回 qrToken: {accept}")

    _set_state("scanned", "确认成功，正在换取登录凭证...")
    callback = session.post(
        QR_CALLBACK,
        data={"qrToken": qr_token, "sid": sid},
        timeout=30,
    ).json()
    logger.info("ks callback sid=%s keys=%s cookie=%s", sid, list(callback.keys()), list(session.cookies.keys()))
    _merge_auth_payload_into_cookies(session, callback)

    at_key = f"{sid}.at"
    auth_token = (
        callback.get(at_key)
        or callback.get(f"{SID_WEBDAY7}.at")
        or callback.get(f"{SID_WWW}.at")
        or callback.get(f"{SID_CP}.at")
    )
    if not auth_token and not _has_login_markers(_serialize_jar(session)):
        raise RuntimeError(_api_err(callback, "换取登录凭证失败"))

    if auth_token:
        _set_state("scanned", "正在写入登录 Cookie...")
        www_headers = {
            **session.headers,
            "Origin": "https://www.kuaishou.com",
            "Referer": "https://www.kuaishou.com/",
        }
        # 1) verifyToken
        try:
            verify = session.post(
                QR_VERIFY,
                json={"authToken": auth_token, "sid": sid},
                headers=www_headers,
                timeout=20,
            ).json()
            logger.info("ks verifyToken sid=%s: %s", sid, verify)
            _merge_auth_payload_into_cookies(session, verify)
        except Exception as e:
            logger.warning("verifyToken failed: %s", e)

        # 2) POST /rest/infra/sts（尽量种下 www 域 Cookie）
        try:
            sts = session.post(
                QR_STS,
                data={"authToken": auth_token, "sid": sid},
                headers=www_headers,
                timeout=20,
            )
            try:
                sts_json = sts.json()
            except Exception:
                sts_json = {"http": sts.status_code}
            logger.info("ks sts POST sid=%s: %s cookie=%s", sid, sts_json, list(session.cookies.keys()))
            if isinstance(sts_json, dict):
                _merge_auth_payload_into_cookies(session, sts_json)
        except Exception as e:
            logger.warning("sts failed: %s", e)

    cookie_str = _serialize_jar(session)
    if not _has_login_markers(cookie_str):
        raise RuntimeError(
            "登录流程完成但未拿到有效 Cookie，请重试。"
            f"（sid={sid}, cookies={list(session.cookies.keys())}）"
        )

    # 只在缺 webday7 时轻量补一次，避免连环换票触发 App 下线
    cookie_str = _ensure_webday7_if_missing(session, cookie_str)

    # 必须通过 www 真实登录校验，避免「有 Cookie 但点赞页仍要扫码」
    ok, uid, msg = validate_kuaishou_www_login(cookie_str=cookie_str, session=session)
    if not ok:
        set_login_expired(True)
        raise RuntimeError(
            f"{msg}。扫码换票未激活 www 登录态，请重试；"
            "或在电脑浏览器登录 www.kuaishou.com 后，把 Cookie 粘贴到「手动填入」。"
        )

    settings = get_settings()
    settings["kuaishou_cookie"] = cookie_str
    save_settings(settings)
    set_login_expired(False)
    uid = uid or _extract_user_id(cookie_str)
    _set_state(
        "success",
        f"登录完成！(UID: {uid})" if uid else "登录完成！Cookie 已保存",
        cookie=cookie_str,
        qrcode="",
    )


def _ensure_webday7_if_missing(session: requests.Session, cookie_str: str) -> str:
    """若已有 webday7 登录态则直接返回；否则用现有 passToken 只换一次 webday7。"""
    if "kuaishou.server.webday7_st" in cookie_str:
        return cookie_str
    if "passToken" not in cookie_str:
        return cookie_str

    sid = SID_WEBDAY7
    try:
        callback = (
            "https://www.kuaishou.com/rest/infra/sts?"
            f"followUrl={requests.utils.quote('https://www.kuaishou.com/', safe='')}"
            f"&sid={sid}"
        )
        r = session.get(
            "https://id.kuaishou.com/pass/kuaishou/login/passToken",
            params={"sid": sid, "callback": callback},
            headers={
                **session.headers,
                "Origin": "https://www.kuaishou.com",
                "Referer": "https://www.kuaishou.com/",
            },
            allow_redirects=True,
            timeout=30,
        )
        logger.info(
            "ks webday7 fill-in status=%s cookies=%s body=%s",
            r.status_code,
            list(session.cookies.keys()),
            (r.text or "")[:160],
        )
    except Exception as e:
        logger.warning("webday7 fill-in failed: %s", e)

    return _serialize_jar(session) or cookie_str


def _login_with_sid(session: requests.Session, sid: str) -> bool:
    """用指定 sid 跑完二维码登录；成功返回 True。"""
    start = session.post(QR_START, data={"sid": sid}, timeout=20).json()
    logger.info("ks start sid=%s result=%s", sid, start.get("result"))
    if start.get("result") != 1 or not start.get("imageData"):
        raise RuntimeError(_api_err(start, f"获取二维码失败（{sid}）"))

    token = start["qrLoginToken"]
    signature = start["qrLoginSignature"]
    qr_img = f"data:image/png;base64,{start['imageData']}"
    _set_state("scanning", "请使用快手 App 扫描二维码", qrcode=qr_img)

    deadline = time.time() + 180
    while time.time() < deadline:
        if _cancel_event.is_set():
            _set_state("cancelled", "登录已取消", qrcode="")
            return False

        try:
            # KSQRcode：scanResult 不传 sid
            scan = session.post(
                QR_SCAN,
                data={"qrLoginToken": token, "qrLoginSignature": signature},
                timeout=40,
            ).json()
        except requests.exceptions.ReadTimeout:
            continue
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"轮询失败: {e}") from e

        result = scan.get("result")
        logger.info("ks scan sid=%s result=%s err=%s", sid, result, scan.get("error_msg") or scan.get("errorMsg"))

        if result == 707:
            _set_state("expired", "二维码已过期，请重新扫码", qrcode="")
            return False

        if result == 1:
            user = scan.get("user") or {}
            name = user.get("user_name") or user.get("userName") or ""
            tip = f"已扫码{('：' + name) if name else ''}，请在手机上确认登录"
            _set_state("scanned", tip, qrcode=qr_img)
            _complete_login(session, sid, token, signature)
            return True

        err = (scan.get("error_msg") or scan.get("errorMsg") or "").strip()
        if err and ("出错" not in err) and ("一会儿" not in err):
            _set_state("scanning", err, qrcode=qr_img)
        else:
            _set_state("scanning", "请使用快手 App 扫描二维码", qrcode=qr_img)
        time.sleep(0.2)

    _set_state("expired", "登录超时，请重试", qrcode="")
    return False


def _do_login():
    _set_state("scanning", "正在获取二维码...", cookie="", qrcode="")
    session = _new_session()
    try:
        try:
            session.get(
                "https://www.kuaishou.com/",
                headers={
                    **session.headers,
                    "Origin": "https://www.kuaishou.com",
                    "Referer": "https://www.kuaishou.com/",
                },
                timeout=15,
            )
        except Exception:
            pass

        # 官方网页登录态：webday7 → server.web；不用创作者平台 sid，降低踢 App 概率
        last_err = None
        for sid in (SID_WEBDAY7, SID_WWW):
            try:
                if _login_with_sid(session, sid):
                    return
                # 取消 / 过期：不再换 sid
                if _login_state.get("status") in ("cancelled", "expired"):
                    return
                last_err = RuntimeError(_login_state.get("message") or f"{sid} 未完成登录")
            except Exception as e:
                last_err = e
                # 已出码则不要换 sid（否则用户要扫两次）；仅拿码失败才回退
                if _login_state.get("qrcode"):
                    raise
                logger.warning("ks login bootstrap failed sid=%s: %s", sid, e)
                session = _new_session()
                continue
        if last_err:
            raise last_err
    except Exception as e:
        logger.exception("kuaishou login failed")
        if not _cancel_event.is_set():
            _set_state("error", f"登录异常: {e}", qrcode="")


@kuaishou_auth_bp.route("/start", methods=["POST"])
def start_login():
    global _worker_thread, _cancel_event

    with _login_lock:
        if _login_state["status"] in ("scanning", "scanned") and _worker_thread and _worker_thread.is_alive():
            return jsonify({"error": "正在登录中，请勿重复操作", "qrcode": _login_state.get("qrcode", "")}), 400

    _cancel_event = threading.Event()
    _set_state("scanning", "正在获取二维码...", cookie="", qrcode="")
    _worker_thread = threading.Thread(target=_do_login, daemon=True)
    _worker_thread.start()
    for _ in range(50):
        with _login_lock:
            if _login_state.get("qrcode") or _login_state["status"] in ("error", "expired", "cancelled"):
                break
        time.sleep(0.1)

    with _login_lock:
        return jsonify({
            "message": _login_state.get("message") or "请扫码登录",
            "status": _login_state.get("status"),
            "qrcode": _login_state.get("qrcode") or "",
        })


@kuaishou_auth_bp.route("/cancel", methods=["POST"])
def cancel_login():
    if _login_state["status"] not in ("scanning", "scanned"):
        return jsonify({"error": "没有正在进行的登录"}), 400
    _cancel_event.set()
    _set_state("cancelled", "登录已取消", qrcode="")
    return jsonify({"message": "已取消登录"})


@kuaishou_auth_bp.route("/status", methods=["GET"])
def check_status():
    with _login_lock:
        if _login_state["status"] in ("scanning", "scanned"):
            return jsonify({
                "status": _login_state["status"],
                "message": _login_state["message"],
                "cookie": _login_state.get("cookie") or "",
                "qrcode": _login_state.get("qrcode") or "",
            })

    settings = get_settings()
    cookie = settings.get("kuaishou_cookie", "")
    if cookie and any(k in cookie for k in LOGIN_MARKER_KEYS):
        # 实时探测 www，避免本地有 Cookie 标记但实际已失效
        ok, uid, msg = validate_kuaishou_www_login(cookie_str=cookie)
        if ok:
            set_login_expired(False)
            return jsonify({
                "status": "success",
                "message": msg or (f"登录有效 (UID: {uid})" if uid else "登录有效"),
                "cookie": cookie,
                "qrcode": "",
                "account_info": {"user_id": uid} if uid else {},
            })
        set_login_expired(True)
        return jsonify({
            "status": "expired",
            "message": msg or "登录已失效，请重新扫码登录",
            "cookie": cookie,
            "qrcode": "",
        })

    with _login_lock:
        payload = dict(_login_state)
        payload.setdefault("qrcode", "")
        return jsonify(payload)


# ── 本地浏览器自动截获 Cookie（对齐视频号「元宝」方案）──────────────
_capture_task = {
    "status": "idle",  # idle | running | success | failed | cancelled
    "message": "",
    "cookie": "",
    "error": "",
}
_capture_lock = threading.Lock()
_capture_cancel = threading.Event()
_capture_thread = None
KS_BROWSER_PROFILE = DATA_DIR / "ks_browser_profile"


def _cookie_str_from_list(cookies: list) -> str:
    """合并 Cookie；同名优先保留更长的值（passToken 等常很长）。"""
    best: dict[str, str] = {}
    for c in cookies or []:
        name = (c.get("name") or "").strip()
        value = (c.get("value") or "").strip()
        domain = (c.get("domain") or "").lstrip(".").lower()
        if not name or not value:
            continue
        if domain and "kuaishou.com" not in domain and "gifshow.com" not in domain:
            continue
        prev = best.get(name)
        if prev is None or len(value) > len(prev):
            best[name] = value
    return "; ".join(f"{k}={v}" for k, v in best.items())


def _collect_ks_cookies(context) -> str:
    """
    必须拉全站 Cookie：passToken 在 id.kuaishou.com，
    webday7_st 在 www.kuaishou.com。只读 www URL 会漏掉 passToken。
    """
    merged = []
    seen_keys = set()
    sources = [
        None,  # 全部
        "https://www.kuaishou.com/",
        "https://www.kuaishou.com/new-reco",
        "https://id.kuaishou.com/",
        "https://live.kuaishou.com/",
    ]
    for url in sources:
        try:
            batch = context.cookies() if url is None else context.cookies(url)
        except Exception:
            continue
        for c in batch or []:
            key = (
                (c.get("name") or ""),
                (c.get("domain") or ""),
                (c.get("path") or "/"),
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            merged.append(c)
    return _cookie_str_from_list(merged)


def _cookies_look_logged_in(cookie_str: str) -> bool:
    """www 登录：userId + (passToken 或 web*_st) 即可进入校验。"""
    if not cookie_str:
        return False
    has_user = "userId=" in cookie_str
    has_token = "passToken=" in cookie_str
    has_st = (
        "kuaishou.server.webday7_st=" in cookie_str
        or "kuaishou.server.web_st=" in cookie_str
    )
    return has_user and (has_token or has_st)


def _cookie_marker_hint(cookie_str: str) -> str:
    flags = []
    for key, label in (
        ("userId=", "userId"),
        ("passToken=", "passToken"),
        ("kuaishou.server.webday7_st=", "webday7_st"),
        ("kuaishou.server.web_st=", "web_st"),
    ):
        if key in (cookie_str or ""):
            flags.append(label)
    return "、".join(flags) if flags else "无关键字段"


def _try_accept_captured_cookie(cookie_str: str) -> tuple[bool, str, str]:
    """补全 webday7 后校验；成功返回 (True, cookie, message)。"""
    if not cookie_str:
        return False, "", ""
    session = _session_from_cookie_str(cookie_str)
    filled = _ensure_webday7_if_missing(session, cookie_str)
    ok, uid, msg = validate_kuaishou_www_login(cookie_str=filled, session=session)
    if ok:
        return True, filled or cookie_str, msg or f"登录有效 (UID: {uid})"
    return False, filled or cookie_str, msg or "校验未通过"


def _do_capture_cookie():
    """拉起可视浏览器打开 www.kuaishou.com，登录成功后自动截获 Cookie。"""
    global _capture_task
    from parse_tools.core.runtime import launch_persistent_context

    with _capture_lock:
        _capture_task = {
            "status": "running",
            "message": "正在打开本地浏览器…",
            "cookie": "",
            "error": "",
        }

    try:
        from playwright.sync_api import sync_playwright

        KS_BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            context = launch_persistent_context(
                p.chromium,
                KS_BROWSER_PROFILE,
                headless=False,
                viewport={"width": 1280, "height": 860},
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                with _capture_lock:
                    _capture_task["message"] = (
                        "请在弹出的浏览器中登录快手网页（推荐停留在推荐页）；"
                        "若已登录将自动识别并保存 Cookie"
                    )
                # 推荐页登录态更完整；首页有时只是半登录
                for url in (
                    "https://www.kuaishou.com/new-reco",
                    "https://www.kuaishou.com/",
                ):
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=45000)
                        break
                    except Exception:
                        continue

                captured = ""
                last_hint = ""
                deadline = time.time() + 300
                while time.time() < deadline:
                    if _capture_cancel.is_set():
                        with _capture_lock:
                            _capture_task = {
                                "status": "cancelled",
                                "message": "已取消",
                                "cookie": "",
                                "error": "",
                            }
                        return

                    try:
                        if page.is_closed():
                            break
                    except Exception:
                        break

                    cookie_str = _collect_ks_cookies(context)
                    hint = _cookie_marker_hint(cookie_str)
                    if hint != last_hint:
                        last_hint = hint
                        logger.info("ks capture cookie markers: %s", hint)

                    if _cookies_look_logged_in(cookie_str):
                        with _capture_lock:
                            _capture_task["message"] = f"已检测到 {hint}，正在校验…"
                        ok, final_cookie, msg = _try_accept_captured_cookie(cookie_str)
                        if ok:
                            captured = final_cookie
                            with _capture_lock:
                                _capture_task["message"] = msg
                            break
                        with _capture_lock:
                            _capture_task["message"] = (
                                f"已检测到 {hint}，但校验未通过：{msg}。"
                                "请确认页面右上角已显示头像后再等几秒…"
                            )
                    else:
                        with _capture_lock:
                            _capture_task["message"] = (
                                f"等待网页登录完成（当前：{hint}；请勿关闭浏览器）…"
                            )
                    time.sleep(1.5)

                # 窗口被关时再读一次
                if not captured:
                    try:
                        cookie_str = _collect_ks_cookies(context)
                        if _cookies_look_logged_in(cookie_str):
                            ok, final_cookie, _msg = _try_accept_captured_cookie(cookie_str)
                            if ok:
                                captured = final_cookie
                    except Exception:
                        pass
            finally:
                try:
                    context.close()
                except Exception:
                    pass

        if captured:
            settings = get_settings()
            settings["kuaishou_cookie"] = captured
            save_settings(settings)
            set_login_expired(False)
            with _capture_lock:
                _capture_task = {
                    "status": "success",
                    "message": "Cookie 已自动获取并保存",
                    "cookie": captured,
                    "error": "",
                }
        else:
            with _capture_lock:
                if _capture_task.get("status") != "cancelled":
                    _capture_task = {
                        "status": "failed",
                        "message": "",
                        "cookie": "",
                        "error": (
                            "未检测到有效登录。请在弹出窗口登录 www.kuaishou.com/new-reco 后重试；"
                            "需出现 userId + passToken/webday7_st。"
                            "若用手机扫码，仍可能挤下线 App。"
                        ),
                    }
    except Exception as e:
        err = str(e)
        if "closed" in err.lower() or "target page" in err.lower():
            err = "浏览器窗口已关闭，自动获取已取消"
        logger.exception("ks capture cookie failed")
        with _capture_lock:
            _capture_task = {
                "status": "failed",
                "message": "",
                "cookie": "",
                "error": err,
            }


@kuaishou_auth_bp.route("/capture-cookie", methods=["POST"])
def start_capture_cookie():
    """本地拉起浏览器，登录后自动截获 Cookie（对齐元宝方案）"""
    global _capture_thread, _capture_cancel

    with _capture_lock:
        if _capture_task.get("status") == "running" and _capture_thread and _capture_thread.is_alive():
            return jsonify({"message": "抓取任务已在运行中", "status": "running"})

    _capture_cancel = threading.Event()
    _capture_thread = threading.Thread(target=_do_capture_cookie, daemon=True)
    _capture_thread.start()
    return jsonify({
        "message": "已唤起本地浏览器，请在窗口中登录快手网页（已登录会自动识别）",
        "status": "running",
    })


@kuaishou_auth_bp.route("/capture-cookie-status", methods=["GET"])
def capture_cookie_status():
    with _capture_lock:
        return jsonify(dict(_capture_task))


@kuaishou_auth_bp.route("/capture-cookie-cancel", methods=["POST"])
def capture_cookie_cancel():
    _capture_cancel.set()
    with _capture_lock:
        if _capture_task.get("status") == "running":
            _capture_task["status"] = "cancelled"
            _capture_task["message"] = "正在取消…"
    return jsonify({"message": "已请求取消"})
