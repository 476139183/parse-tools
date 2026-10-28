"""Douyin HTTP API client."""
from __future__ import annotations

import json
import random
import re
import string
import time
import urllib.parse
from pathlib import Path
from typing import Any

import requests as http_requests

from parse_tools.core.config import (
    DATA_DIR, get_settings, get_proxy_config, get_proxy_url,
    get_proxies_dict, report_proxy_status, load_json, save_json
)
from parse_tools.platforms.douyin.douyin_sign import sign_detail, sign_params, sign_secsdk_url
from parse_tools.platforms.douyin.douyin_mstoken import get_real_ms_token
from parse_tools.platforms.douyin.tasks import _add_log

DOUYIN_DIR = DATA_DIR / "douyin_downloads"
HISTORY_FILE = DATA_DIR / "douyin_history.json"
PROGRESS_FILE = DATA_DIR / "douyin_progress.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36"
)
REFERER = "https://www.douyin.com/"
API_VIDEO_DETAIL = "https://www.douyin.com/aweme/v1/web/aweme/detail/"
API_MULTI_DETAIL = "https://www.douyin.com/aweme/v1/web/multi/aweme/detail/"
API_USER_POST = "https://www.douyin.com/aweme/v1/web/aweme/post/"
API_MIX_AWEME = "https://www.douyin.com/aweme/v1/web/mix/aweme/"
API_MUSIC_DETAIL = "https://www.douyin.com/aweme/v1/web/music/detail/"
API_WEBCAST_ROOM = "https://live.douyin.com/webcast/room/web/enter/"
API_REFLOW_EPISODE = "https://webcast.amemv.com/webcast/reflow/episode/info/"

_ILLEGAL_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_EDGE_STRIP_CHARS = ". "


def clean_filename(filename: str, max_length: int = 80) -> str:
    if not filename:
        return "untitled"
    filename = filename.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    filename = _ILLEGAL_FILENAME_CHARS_RE.sub("_", filename)
    filename = filename.strip(_EDGE_STRIP_CHARS)
    if len(filename) > max_length:
        filename = filename[:max_length].rstrip(_EDGE_STRIP_CHARS)
    return filename if filename else "untitled"


def generate_ms_token(size: int = 107) -> str:
    return get_real_ms_token(USER_AGENT)


def generate_verify_fp() -> str:
    chars = string.ascii_lowercase + string.digits
    random_str = "".join(random.choice(chars) for _ in range(16))
    return f"verify_0{random_str}"

class DouyinClient:
    """抖音 API 客户端 — 直接 HTTP 调用 + a_bogus 签名"""

    def __init__(self):
        self.session = http_requests.Session()
        
        # 加载用户设置中的 Cookie
        settings = get_settings()
        cookie = settings.get("douyin_cookie", "").strip()
        
        headers = self._get_common_headers()
        if cookie:
            headers["Cookie"] = cookie
            
        self.session.headers.update(headers)
        
        proxies = get_proxies_dict()
        if proxies:
            self.session.proxies.update(proxies)
        else:
            self.session.trust_env = False

        if "ttwid=" not in self.session.headers.get("Cookie", "") and not self.session.cookies.get("ttwid"):
            self.ensure_ttwid_cookie()

    def ensure_ttwid_cookie(self, force_refresh: bool = False) -> bool:
        """确保会话中含有有效的 ttwid 和 UIFID_TEMP，支持自动获取和受控自愈刷新"""
        try:
            if not force_refresh and ("ttwid=" in self.session.headers.get("Cookie", "") or self.session.cookies.get("ttwid")):
                return True
            resp = self.session.get("https://live.douyin.com/", timeout=8)
            ttwid = self.session.cookies.get("ttwid") or resp.cookies.get("ttwid")
            uifid = self.session.cookies.get("UIFID_TEMP") or resp.cookies.get("UIFID_TEMP")
            appended = []
            if ttwid and "ttwid=" not in self.session.headers.get("Cookie", ""):
                appended.append(f"ttwid={ttwid}")
            if uifid and "UIFID_TEMP=" not in self.session.headers.get("Cookie", ""):
                appended.append(f"UIFID_TEMP={uifid}")
            if appended:
                current_ck = self.session.headers.get("Cookie", "").strip()
                if current_ck:
                    self.session.headers["Cookie"] = f"{current_ck}; " + "; ".join(appended)
                else:
                    self.session.headers["Cookie"] = "; ".join(appended)
            return bool(ttwid)
        except Exception as e:
            _add_log(f"⚠️ 自动获取抖音匿名身份凭证失败: {e}")
            return False

    def get_uifid(self) -> str:
        """从 Cookie 或会话中提取有效 UIFID"""
        ck_str = self.session.headers.get("Cookie", "")
        for p in ck_str.split(";"):
            p = p.strip()
            if p.startswith("UIFID=") and not p.startswith("UIFID_TEMP="):
                return p.split("UIFID=", 1)[1].strip()
        return self.session.cookies.get("UIFID") or ""

    def _get_common_headers(self) -> dict:
        """通用请求头"""
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": REFERER,
            "User-Agent": USER_AGENT,
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
            "sec-ch-ua-platform": '"Windows"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua": '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
            "priority": "u=1, i",
        }

    def _get_common_params(self) -> dict:
        """通用请求参数"""
        return {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "update_version_code": "170400",
            "pc_client_type": "1",
            "version_code": "190500",
            "version_name": "29.3.0",
            "cookie_enabled": "true",
            "screen_width": "1920",
            "screen_height": "1080",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Chrome",
            "browser_version": "133.0.0.0",
            "browser_online": "true",
            "engine_name": "Blink",
            "engine_version": "133.0.0.0",
            "os_name": "Windows",
            "os_version": "10",
            "cpu_core_num": "16",
            "device_memory": "8",
            "platform": "PC",
            "downlink": "10",
            "effective_type": "4g",
            "round_trip_time": "50",
            "pc_libra_divert": "Windows",
            "support_h265": "1",
            "support_dash": "1",
            "disable_rs": "0",
            "need_filter_settings": "1",
            "list_type": "single",
            "msToken": generate_ms_token(),
            "verifyFp": generate_verify_fp(),
        }

    def _enrich_and_sign(self, params: dict, skip_sign: bool = False) -> dict:
        """补充通用参数并添加签名，返回字典"""
        all_params = self._get_common_params()
        all_params.update(params)

        if not skip_sign:
            try:
                # 构造用于签名的 query string
                query_parts = []
                for k, v in all_params.items():
                    query_parts.append(f"{k}={urllib.parse.quote(str(v))}")
                query = "&".join(query_parts)

                a_bogus = sign_detail(query, USER_AGENT)
                all_params["a_bogus"] = a_bogus
            except Exception as e:
                _add_log(f"⚠️ 签名生成失败: {e}")
                
        return all_params

    def api_get(self, url: str, params: dict, skip_sign: bool = False, timeout: int = 15) -> dict:
        """发起签名后的 GET 请求，返回 JSON（带 x-secsdk 签名与风控自愈重试）"""
        uifid = self.get_uifid()
        if uifid and "uifid" not in self.session.headers:
            self.session.headers["uifid"] = uifid

        for attempt in range(2):
            all_params = self._enrich_and_sign(params, skip_sign)
            try:
                if uifid:
                    qs = urllib.parse.urlencode(all_params)
                    full_req_url = f"{url}?{qs}" if qs else url
                    full_req_url = sign_secsdk_url(full_req_url, uifid=uifid)
                    resp = self.session.get(full_req_url, timeout=timeout)
                else:
                    resp = self.session.get(url, params=all_params, timeout=timeout)

                if resp.status_code == 403 or "Argus" in resp.text or "Uifid" in resp.text:
                    if attempt == 0:
                        _add_log("⚠️ 抖音请求受 Argus/风控拦截，自动刷新匿名凭证重试...")
                        self.ensure_ttwid_cookie(force_refresh=True)
                        continue
                resp.raise_for_status()
                
                # 抖音在未登录或Cookie失效且无有效签名时，可能会直接返回 0 字节的响应
                if len(resp.content) == 0:
                    if attempt == 0:
                        _add_log("⚠️ 抖音响应为空，自动刷新匿名凭证重试...")
                        self.ensure_ttwid_cookie(force_refresh=True)
                        continue
                    raise ValueError("未获取到有效数据。请检查是否已在左侧菜单「扫码登录」并获取有效 Cookie。")
                    
                try:
                    return resp.json()
                except Exception:
                    if b"\xe6\x9a\x82\xe6\x97\xb6\xe6\xb2\xa1\xe6\x9c\x89\xe6\x9b\xb4\xe5\xa4\x9a\xe4\xba\x86" in resp.content or "application/x-protobuf" in resp.headers.get("content-type", ""):
                        return {"status_code": 0, "aweme_list": [], "has_more": False}
                    if attempt == 0:
                        _add_log("⚠️ 抖音接口返回非 JSON 数据，重试刷新凭证...")
                        self.ensure_ttwid_cookie(force_refresh=True)
                        continue
                    raise ValueError("抖音接口返回非 JSON 数据，请确认是否已在左侧菜单「扫码登录」并获取有效 Cookie。")
            except ValueError as ve:
                raise Exception(str(ve))
            except Exception as e:
                err_str = str(e)
                if attempt == 0 and ("403" in err_str or "Argus" in err_str or "Forbidden" in err_str):
                    _add_log("⚠️ 抖音请求异常，自动刷新匿名凭证重试...")
                    self.ensure_ttwid_cookie(force_refresh=True)
                    continue
                raise Exception(f"API 请求失败: {url} — {str(e)}")

    def api_post(self, url: str, params: dict, data: dict = None, skip_sign: bool = False, timeout: int = 15) -> dict:
        """发起签名后的 POST 请求，返回 JSON（带 x-secsdk 签名与风控自愈重试）"""
        uifid = self.get_uifid()
        if uifid and "uifid" not in self.session.headers:
            self.session.headers["uifid"] = uifid

        for attempt in range(2):
            all_params = self._enrich_and_sign(params, skip_sign)
            try:
                if data is not None:
                    if uifid:
                        qs = urllib.parse.urlencode(all_params)
                        full_req_url = f"{url}?{qs}" if qs else url
                        full_req_url = sign_secsdk_url(full_req_url, uifid=uifid)
                        resp = self.session.post(full_req_url, data=data, timeout=timeout)
                    else:
                        resp = self.session.post(url, params=all_params, data=data, timeout=timeout)
                else:
                    if uifid:
                        full_req_url = sign_secsdk_url(url, uifid=uifid)
                        resp = self.session.post(full_req_url, data=all_params, timeout=timeout)
                    else:
                        resp = self.session.post(url, data=all_params, timeout=timeout)

                if resp.status_code == 403 or "Argus" in resp.text or "Uifid" in resp.text:
                    if attempt == 0:
                        _add_log("⚠️ 抖音请求受 Argus/风控拦截，自动刷新匿名凭证重试...")
                        self.ensure_ttwid_cookie(force_refresh=True)
                        continue
                resp.raise_for_status()
                
                if len(resp.content) == 0:
                    if attempt == 0:
                        _add_log("⚠️ 抖音响应为空，自动刷新匿名凭证重试...")
                        self.ensure_ttwid_cookie(force_refresh=True)
                        continue
                    raise ValueError("未获取到有效数据。请检查是否已在左侧菜单「扫码登录」并获取有效 Cookie。")
                    
                try:
                    return resp.json()
                except Exception:
                    if b"\xe6\x9a\x82\xe6\x97\xb6\xe6\xb2\xa1\xe6\x9c\x89\xe6\x9b\xb4\xe5\xa4\x9a\xe4\xba\x86" in resp.content or "application/x-protobuf" in resp.headers.get("content-type", ""):
                        return {"status_code": 0, "aweme_list": [], "has_more": False}
                    if attempt == 0:
                        _add_log("⚠️ 抖音接口返回非 JSON 数据，重试刷新凭证...")
                        self.ensure_ttwid_cookie(force_refresh=True)
                        continue
                    raise ValueError("抖音接口返回非 JSON 数据，请确认是否已在左侧菜单「扫码登录」并获取有效 Cookie。")
            except ValueError as ve:
                raise Exception(str(ve))
            except Exception as e:
                err_str = str(e)
                if attempt == 0 and ("403" in err_str or "Argus" in err_str or "Forbidden" in err_str):
                    _add_log("⚠️ 抖音请求异常，自动刷新匿名凭证重试...")
                    self.ensure_ttwid_cookie(force_refresh=True)
                    continue
                raise Exception(f"API 请求失败: {url} — {str(e)}")

    # ── 数据查询接口 ──────────────────────────────────────────

    def search_user(self, keyword: str, offset: int = 0) -> dict:
        """搜索用户"""
        import urllib.parse
        encoded_keyword = urllib.parse.quote(keyword)
        self.session.headers["Referer"] = f"https://www.douyin.com/jingxuan/search/{encoded_keyword}?type=user"
        params = {
            "keyword": keyword,
            "search_channel": "aweme_user_web",
            "search_source": "normal_search",
            "query_correct_type": "1",
            "is_filter_search": "0",
            "from_group_id": "",
            "offset": str(offset),
            "count": "10",
            "pc_search_top_1_params": '{"enable_ai_search_top_1":1}'
        }
        return self.api_get("https://www.douyin.com/aweme/v1/web/discover/search/", params, skip_sign=True)

    def get_user_detail(self, sec_uid: str) -> dict:
        """获取用户详情"""
        ref_url = f"https://www.douyin.com/user/{sec_uid}"
        self.session.headers["Referer"] = ref_url
        params = {
            "sec_user_id": sec_uid,
            "personal_center_strategy": "1",
            "source": "channel_pc_web"
        }
        try:
            return self.api_get("https://www.douyin.com/aweme/v1/web/user/profile/other/", params, skip_sign=True)
        except Exception as e:
            err_str = str(e)
            if "403" in err_str or "Argus" in err_str or "Uifid" in err_str or "Forbidden" in err_str:
                _add_log("⚠️ 抖音用户详情直连受风控拦截，自动切换至浏览器会话安全通道获取...")
                return self._fetch_via_browser("/aweme/v1/web/user/profile/other/", method="GET", params=params, referer=ref_url)
            raise

    def get_recommended_feed(self, count: int = 10, cursor: int = 0) -> dict:
        """获取推荐视频流"""
        self.session.headers["Referer"] = "https://www.douyin.com/?recommend=1"
        params = {
            "module_id": "3003101",
            "count": str(count),
            "pull_type": "0",
            "refresh_index": "1",
            "refer_type": "10",
            "use_lite_type": "2",
            "awemePcRecRawData": '{"is_xigua_user":0,"danmaku_switch_status":0,"is_client":false}'
        }
        if cursor > 0:
            params["cursor"] = str(cursor)
        return self.api_post("https://www.douyin.com/aweme/v2/web/module/feed/", params)

    def get_self_sec_uid(self) -> str:
        """获取登录用户自己的 sec_uid"""
        try:
            res = self.api_get("https://www.douyin.com/aweme/v1/web/user/profile/self/", {}, skip_sign=True)
            if res.get("status_code") == 0 and "user" in res:
                return res["user"].get("sec_uid", "")
        except Exception as e:
            _add_log(f"⚠️ 获取登录用户个人信息失败: {e}")
        return ""

    def get_liked_videos(self, sec_uid: str = "", max_cursor: int = 0, count: int = 18) -> dict:
        """获取点赞/喜欢视频列表 (支持本人及任意公开博主)"""
        if not sec_uid:
            sec_uid = self.get_self_sec_uid()

        params = {
            "sec_user_id": sec_uid,
            "max_cursor": str(max_cursor),
            "min_cursor": "0",
            "count": str(count),
            "whale_cut_token": "",
            "cut_version": "1",
            "publish_video_strategy_type": "2",
            "locate_query": "false"
        }
        ref_url = f"https://www.douyin.com/user/{sec_uid}" if sec_uid else "https://www.douyin.com/user/self"
        self.session.headers["Referer"] = ref_url

        try:
            res = self.api_get("https://www.douyin.com/aweme/v1/web/aweme/favorite/", params, skip_sign=True)
            if res.get("status_code") == 0 and res.get("aweme_list"):
                return res
        except Exception:
            pass

        # 切换至浏览器会话安全通道
        return self._fetch_liked_via_browser(sec_uid=sec_uid, max_cursor=max_cursor, count=count)

    def _fetch_liked_via_browser(self, sec_uid: str = "", max_cursor: int = 0, count: int = 18) -> dict:
        """通过后台浏览器会话获取点赞/喜欢视频列表 (支持本人及公开博主，自动激活 Tab 与无限滚动翻页)"""
        from playwright.sync_api import sync_playwright
        from parse_tools.core.runtime import launch_chromium

        settings = get_settings()
        cookie_str = settings.get("douyin_cookie", "").strip()
        cookie_objs = []
        for item in cookie_str.split(";"):
            item = item.strip()
            if "=" in item:
                k, _, v = item.partition("=")
                if k.strip() and v.strip():
                    cookie_objs.append({
                        "name": k.strip(),
                        "value": v.strip(),
                        "domain": ".douyin.com",
                        "path": "/"
                    })

        self_uid = self.get_self_sec_uid()
        is_self = not sec_uid or sec_uid == "self" or (self_uid and sec_uid == self_uid)
        target_url = "https://www.douyin.com/user/self" if is_self else f"https://www.douyin.com/user/{sec_uid}"

        with sync_playwright() as p:
            browser = launch_chromium(p.chromium, headless=True, args=["--disable-blink-features=AutomationControlled"])
            try:
                context = browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={"width": 1440, "height": 900}
                )
                if cookie_objs:
                    context.add_cookies(cookie_objs)
                page = context.new_page()

                captured_pages = []
                def on_res(resp):
                    if "favorite" in resp.url and resp.status == 200:
                        try:
                            data = resp.json()
                            if isinstance(data, dict) and data.get("status_code") == 0 and data.get("aweme_list"):
                                if not any(cp.get("max_cursor") == data.get("max_cursor") and len(cp.get("aweme_list", [])) == len(data.get("aweme_list", [])) for cp in captured_pages):
                                    captured_pages.append(data)
                        except Exception:
                            pass

                page.on("response", on_res)
                try:
                    page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
                except Exception:
                    pass

                # 点击喜欢 Tab 触发第一页加载
                for _ in range(8):
                    if captured_pages:
                        break
                    try:
                        tab = page.locator("#semiTablike")
                        if tab.is_visible():
                            tab.click(force=True)
                    except Exception:
                        pass
                    time.sleep(0.8)

                # 如果请求的是非首页游标（翻页），通过滚动页面触发后续游标请求
                if max_cursor != 0 and str(max_cursor) != "0":
                    for _ in range(8):
                        found = False
                        for idx in range(len(captured_pages) - 1):
                            if str(captured_pages[idx].get("max_cursor")) == str(max_cursor):
                                found = True
                                break
                        if found:
                            break
                        page.evaluate("() => window.scrollBy(0, 4000)")
                        time.sleep(1.5)

                # 提取匹配游标的页数据
                result = None
                if max_cursor == 0 or str(max_cursor) == "0":
                    if captured_pages:
                        result = captured_pages[0]
                else:
                    for idx in range(len(captured_pages) - 1):
                        if str(captured_pages[idx].get("max_cursor")) == str(max_cursor):
                            result = captured_pages[idx + 1]
                            break
                    if not result and captured_pages:
                        result = captured_pages[-1]

                if not result:
                    result = {"status_code": 0, "aweme_list": [], "has_more": False, "max_cursor": 0}

                # 自动将最新产生的 Cookie 回写设置
                try:
                    updated_cookies = context.cookies()
                    if updated_cookies:
                        new_ck = "; ".join([f"{c['name']}={c['value']}" for c in updated_cookies])
                        settings["douyin_cookie"] = new_ck
                        save_settings(settings)
                except Exception:
                    pass

                return result
            finally:
                browser.close()

    def _fetch_via_browser(self, endpoint: str, method: str = "GET", params: dict = None, body: dict = None, referer: str = "") -> dict:
        """通过后台无头浏览器在已授权的上下文中执行 fetch 请求，以绕过 Argus/uifid 等高级风控拦截"""
        from playwright.sync_api import sync_playwright
        from parse_tools.core.runtime import launch_chromium

        settings = get_settings()
        cookie_str = settings.get("douyin_cookie", "").strip()
        cookie_objs = []
        for item in cookie_str.split(";"):
            item = item.strip()
            if "=" in item:
                k, _, v = item.partition("=")
                if k.strip() and v.strip():
                    cookie_objs.append({
                        "name": k.strip(),
                        "value": v.strip(),
                        "domain": ".douyin.com",
                        "path": "/"
                    })

        ref_url = referer or "https://www.douyin.com/user/self?showTab=favorite_collection"

        with sync_playwright() as p:
            browser = launch_chromium(p.chromium, headless=True, args=["--disable-blink-features=AutomationControlled"])
            try:
                context = browser.new_context(
                    user_agent=USER_AGENT
                )
                if cookie_objs:
                    context.add_cookies(cookie_objs)
                page = context.new_page()
                try:
                    page.goto(ref_url, wait_until="domcontentloaded", timeout=12000)
                except Exception:
                    pass

                # 构建请求参数
                fetch_url = endpoint
                fetch_params = {}
                if "/aweme/" in endpoint:
                    fetch_params = {
                        "device_platform": "webapp",
                        "aid": "6383",
                        "channel": "channel_pc_web",
                    }
                if params:
                    fetch_params.update(params)

                if fetch_params:
                    import urllib.parse
                    qs = urllib.parse.urlencode(fetch_params)
                    fetch_url = f"{endpoint}?{qs}" if "?" not in endpoint else f"{endpoint}&{qs}"

                body_str = None
                if body:
                    import urllib.parse
                    body_str = urllib.parse.urlencode(body)

                res = {}
                for _ in range(3):
                    try:
                        res = page.evaluate("""async ({url, method, bodyStr}) => {
                            let lastErr = '';
                            for (let i = 0; i < 6; i++) {
                                try {
                                    const opts = {
                                        method: method,
                                        headers: {
                                            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
                                        }
                                    };
                                    if (bodyStr && method.toUpperCase() !== 'GET') {
                                        opts.body = bodyStr;
                                    }
                                    const resp = await window.fetch(url, opts);
                                    const text = await resp.text();
                                    if (text.startsWith('{')) {
                                        return JSON.parse(text);
                                    }
                                    lastErr = text.slice(0, 150);
                                } catch (e) {
                                    lastErr = e.message;
                                }
                                await new Promise(r => setTimeout(r, 600));
                            }
                            return { status_code: -1, error: lastErr || 'SecSDK initialization timeout' };
                        }""", {"url": fetch_url, "method": method, "bodyStr": body_str})
                        break
                    except Exception as eval_err:
                        if "destroyed" in str(eval_err) or "navigation" in str(eval_err):
                            time.sleep(1)
                            continue
                        raise eval_err

                # 自动将浏览器更新产生的最新 Cookie 写回设置及会话
                try:
                    updated_cookies = context.cookies()
                    if updated_cookies:
                        new_ck = "; ".join([f"{c['name']}={c['value']}" for c in updated_cookies])
                        settings["douyin_cookie"] = new_ck
                        save_settings(settings)
                        self.session.headers["Cookie"] = new_ck
                except Exception:
                    pass

                return res or {}
            finally:
                browser.close()

    def get_collected_videos(self, cursor: int = 0, count: int = 18) -> dict:
        """获取收藏视频列表 (需要登录)"""
        params = {
            "cursor": str(cursor),
            "count": str(count)
        }

        # 添加特殊的 headers
        self.session.headers.update({
            "Referer": "https://www.douyin.com/user/self?from_tab_name=main&showTab=favorite_collection",
            "Origin": "https://www.douyin.com",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
        })

        body_data = {
            "cursor": str(cursor),
            "count": str(count)
        }

        try:
            return self.api_post("https://www.douyin.com/aweme/v1/web/aweme/listcollection/", params, data=body_data)
        except Exception as e:
            err_str = str(e)
            if "403" in err_str or "Argus" in err_str or "Uifid" in err_str or "Forbidden" in err_str:
                _add_log(f"⚠️ 抖音收藏直连受风控拦截，自动切换至浏览器会话安全通道获取 (cursor={cursor})...")
                return self._fetch_via_browser("/aweme/v1/web/aweme/listcollection/", method="POST", body=body_data)
            raise


    def get_collect_folders(self, cursor: int = 0, count: int = 10) -> dict:
        """获取收藏夹列表 (需要登录)"""
        params = {
            "cursor": str(cursor),
            "count": str(count)
        }
        self.session.headers.update({
            "Referer": "https://www.douyin.com/user/self?showTab=favorite_collection",
            "Origin": "https://www.douyin.com"
        })
        try:
            return self.api_get("https://www.douyin.com/aweme/v1/web/collects/list/", params)
        except Exception as e:
            err_str = str(e)
            if "403" in err_str or "Argus" in err_str or "Uifid" in err_str or "Forbidden" in err_str:
                _add_log("⚠️ 抖音收藏夹直连受风控拦截，自动切换至浏览器会话安全通道获取...")
                return self._fetch_via_browser("/aweme/v1/web/collects/list/", method="GET", params=params)
            raise


    def get_collect_folder_videos(self, collect_id: str, cursor: int = 0, count: int = 18) -> dict:
        """获取特定收藏夹下的视频列表 (需要登录)"""
        params = {
            "collect_id": str(collect_id),
            "collects_id": str(collect_id),
            "cursor": str(cursor),
            "count": str(count)
        }
        self.session.headers.update({
            "Referer": f"https://www.douyin.com/collection/{collect_id}",
            "Origin": "https://www.douyin.com"
        })
        try:
            return self.api_get("https://www.douyin.com/aweme/v1/web/collects/video/list/", params)
        except Exception as e:
            err_str = str(e)
            if "403" in err_str or "Argus" in err_str or "Uifid" in err_str or "Forbidden" in err_str:
                _add_log(f"⚠️ 抖音收藏夹视频直连受风控拦截，自动切换至浏览器会话安全通道获取 (collect_id={collect_id})...")
                return self._fetch_via_browser("/aweme/v1/web/collects/video/list/", method="GET", params=params, referer=f"https://www.douyin.com/collection/{collect_id}")
            raise

    def get_collected_mixes(self, cursor: int = 0, count: int = 18) -> dict:
        """获取收藏合集列表 (对应 collectmix 模式，需要登录)"""
        params = {
            "cursor": str(cursor),
            "count": str(count)
        }
        ref_url = "https://www.douyin.com/user/self?showTab=favorite_collection"
        self.session.headers.update({
            "Referer": ref_url,
            "Origin": "https://www.douyin.com"
        })
        try:
            return self.api_get("https://www.douyin.com/aweme/v1/web/mix/listcollection/", params)
        except Exception as e:
            err_str = str(e)
            if "403" in err_str or "Argus" in err_str or "Uifid" in err_str or "Forbidden" in err_str:
                _add_log(f"⚠️ 抖音收藏合集直连受风控拦截，自动切换至浏览器会话安全通道获取 (cursor={cursor})...")
                return self._fetch_via_browser("/aweme/v1/web/mix/listcollection/", method="GET", params=params, referer=ref_url)
            raise


    # ── 链接解析 ──────────────────────────────────────────

    def resolve_share_url(self, url: str) -> str:
        """解析抖音分享链接（短链重定向到最终 URL）"""
        url_clean = url.strip()
        # 1. 优先精准匹配 v.douyin.com 短链 (避免后接的口令、标签、冒号等字符影响)
        v_match = re.search(r"https?://v\.douyin\.com/[A-Za-z0-9_\-]+/?", url_clean)
        if v_match:
            target = v_match.group(0)
        else:
            match = re.search(r"https?://[a-zA-Z0-9.\-_]+(?::\d+)?(?:/[^\s<>'\"\u4e00-\u9fa5]*)?", url_clean)
            if not match:
                return url_clean
            target = match.group(0).rstrip("，。！？；、,.!;:")

        try:
            resp = self.session.get(target, allow_redirects=True, timeout=10)
            if "douyin.com" in resp.url:
                return resp.url
            for h in resp.history:
                loc = h.headers.get("Location", "")
                if "douyin.com" in loc:
                    return loc
            return resp.url
        except Exception:
            try:
                resp = self.session.get(target, allow_redirects=False, timeout=8)
                loc = resp.headers.get("Location", "")
                if loc:
                    return loc
            except Exception:
                pass
            return target

    @staticmethod
    def extract_aweme_id(url: str) -> str:
        """从 URL 中提取 aweme_id 或回放 ID"""
        url = url.strip()
        # 纯数字
        if re.match(r"^\d+$", url):
            return url
        # 各种 URL 格式（含短视频、图文、直播回放 vsdetail 与 episode）
        patterns = [
            r"vsdetail/(\d+)",
            r"reflow/episode/(\d+)",
            r"episode/(\d+)",
            r"episode_id=(\d+)",
            r"video/(\d+)",
            r"note/(\d+)",
            r"slides/(\d+)",
            r"itemId=(\d+)",
            r"item_id=(\d+)",
            r"aweme_id=(\d+)",
            r"modal_id=(\d+)",
            r"/(\d{18,21})",
        ]
        for pattern in patterns:
            m = re.search(pattern, url)
            if m:
                return m.group(1)
        return ""

    @staticmethod
    def extract_live_room_id(url: str) -> str:
        """从 URL 中提取直播间 room_id / web_rid"""
        url = url.strip()
        patterns = [
            r"live\.douyin\.com/(\d+)",
            r"/follow/live/(\d+)",
            r"webcast/reflow/(\d+)",
            r"room_id=(\d+)",
            r"web_rid=(\d+)",
        ]
        for pattern in patterns:
            m = re.search(pattern, url)
            if m:
                return m.group(1)
        return ""

    # ── 单条作品详情 API ──────────────────────────────────

    @staticmethod
    def extract_aweme_from_html(html: str, aweme_id: str = "") -> dict:
        """从抖音网页 HTML (SSR/RSC) 中提取单条作品详情字典"""
        if not html:
            return {}

        # 1. 优先尝试从 self.__pace_f.push (Next.js React Server Components) 提取
        for m in re.finditer(r"self\.__pace_f\.push\(\[1,\s*\"(.*?)\"\s*\]\)", html, re.DOTALL):
            chunk = m.group(1)
            if "detail" in chunk and ("awemeId" in chunk or "aweme_id" in chunk or (aweme_id and aweme_id in chunk)):
                try:
                    unescaped = json.loads("\"" + chunk + "\"")
                    colon = unescaped.find(":")
                    candidate_str = unescaped[colon + 1:] if colon != -1 else unescaped
                    first_bracket = -1
                    for idx, ch in enumerate(candidate_str):
                        if ch in ("[", "{"):
                            first_bracket = idx
                            break
                    if first_bracket != -1:
                        raw_json = candidate_str[first_bracket:].rstrip("\n\r ")
                        obj = None
                        try:
                            obj = json.loads(raw_json)
                        except Exception:
                            for end_idx in range(len(raw_json), max(0, len(raw_json) - 60), -1):
                                try:
                                    obj = json.loads(raw_json[:end_idx])
                                    break
                                except Exception:
                                    pass

                        if obj:
                            def find_aweme(node):
                                if isinstance(node, dict):
                                    if "aweme" in node and isinstance(node["aweme"], dict) and "detail" in node["aweme"]:
                                        return node["aweme"]["detail"]
                                    if "detail" in node and isinstance(node["detail"], dict):
                                        if "awemeId" in node["detail"] or "aweme_id" in node["detail"] or "images" in node["detail"] or "video" in node["detail"]:
                                            return node["detail"]
                                    if "aweme_detail" in node and isinstance(node["aweme_detail"], dict):
                                        return node["aweme_detail"]
                                    for v in node.values():
                                        res = find_aweme(v)
                                        if res: return res
                                elif isinstance(node, list):
                                    for item in node:
                                        res = find_aweme(item)
                                        if res: return res
                                return None

                            target_detail = find_aweme(obj)
                            if target_detail and (target_detail.get("awemeId") or target_detail.get("aweme_id")):
                                return target_detail
                except Exception:
                    pass

        # 2. 尝试从 RENDER_DATA 提取
        render_match = re.search(r"<script id=\"RENDER_DATA\"[^>]*>(.*?)</script>", html, re.DOTALL)
        if render_match:
            try:
                raw_data = render_match.group(1).strip()
                decoded = urllib.parse.unquote(raw_data)
                data = json.loads(decoded)

                def find_in_render(node):
                    if isinstance(node, dict):
                        if "aweme_detail" in node and isinstance(node["aweme_detail"], dict):
                            return node["aweme_detail"]
                        if "detail" in node and isinstance(node["detail"], dict):
                            if "awemeId" in node["detail"] or "aweme_id" in node["detail"] or "video" in node["detail"]:
                                return node["detail"]
                        for v in node.values():
                            res = find_in_render(v)
                            if res: return res
                    elif isinstance(node, list):
                        for item in node:
                            res = find_in_render(item)
                            if res: return res
                    return None

                target_detail = find_in_render(data)
                if target_detail:
                    return target_detail
            except Exception:
                pass

        # 3. 尝试从 window._ROUTER_DATA 提取
        router_match = re.search(r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", html, re.DOTALL)
        if router_match:
            try:
                data = json.loads(router_match.group(1).rstrip("; \n\r"))

                def find_in_router(node):
                    if isinstance(node, dict):
                        if "aweme_detail" in node and isinstance(node["aweme_detail"], dict):
                            return node["aweme_detail"]
                        if "item_list" in node and isinstance(node["item_list"], list):
                            if node["item_list"]:
                                return node["item_list"][0]
                        for v in node.values():
                            res = find_in_router(v)
                            if res: return res
                    elif isinstance(node, list):
                        for item in node:
                            res = find_in_router(item)
                            if res: return res
                    return None

                target_detail = find_in_router(data)
                if target_detail:
                    return target_detail
            except Exception:
                pass

        return {}

    def get_video_detail(self, aweme_id: str, share_url: str = "") -> dict:
        """获取单条作品详情（多通道高可靠解析：API + x-secsdk -> 网页SSR/RSC直出 -> 无头浏览器网页渲染）"""
        # 1. 优先调用带 x-secsdk-web-signature / uifid 的 API 接口（极速直接返回）
        try:
            data = self.api_get(API_VIDEO_DETAIL, {
                "aweme_id": aweme_id,
            }, skip_sign=False)

            if data.get("status_code") == 0 and data.get("aweme_detail"):
                return data["aweme_detail"]
        except Exception:
            pass

        # 2. 网页直出 SSR / RSC 解析通道（无需无头浏览器，秒级提取）
        urls_to_try = []
        if share_url and ("note/" in share_url or "video/" in share_url):
            urls_to_try.append(share_url)
        urls_to_try.extend([
            f"https://www.douyin.com/note/{aweme_id}",
            f"https://www.douyin.com/video/{aweme_id}",
        ])

        page_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.douyin.com/",
        }

        for p_url in urls_to_try:
            try:
                resp = self.session.get(p_url, headers=page_headers, allow_redirects=True, timeout=10)
                if resp.status_code == 200 and len(resp.text) > 5000:
                    d = DouyinClient.extract_aweme_from_html(resp.text, aweme_id)
                    if d:
                        return d
            except Exception:
                pass

        # 3. multi detail API 兜底
        try:
            data = self.api_get(API_MULTI_DETAIL, {
                "aweme_ids": f"[{aweme_id}]",
                "request_source": "200",
            }, skip_sign=False)

            if data.get("status_code") == 0:
                details = data.get("aweme_details", [])
                if details:
                    for d in details:
                        if d.get("aweme_id") == aweme_id or d.get("awemeId") == aweme_id:
                            return d
                    return details[0]
        except Exception:
            pass

        # 4. 终极兜底：通过后台无头浏览器渲染页面并提取完整数据
        try:
            _add_log(f"⚠️ 正在通过无头浏览器安全渲染通道获取作品 {aweme_id} 详情...")
            from playwright.sync_api import sync_playwright
            from parse_tools.core.runtime import launch_chromium

            settings = get_settings()
            cookie_str = settings.get("douyin_cookie", "").strip()
            cookie_objs = []
            for item in cookie_str.split(";"):
                item = item.strip()
                if "=" in item:
                    k, _, v = item.partition("=")
                    if k.strip() and v.strip():
                        cookie_objs.append({
                            "name": k.strip(),
                            "value": v.strip(),
                            "domain": ".douyin.com",
                            "path": "/"
                        })

            browser_urls = urls_to_try or [f"https://www.douyin.com/video/{aweme_id}"]
            with sync_playwright() as p:
                browser = launch_chromium(p.chromium, headless=True, args=["--disable-blink-features=AutomationControlled"])
                try:
                    context = browser.new_context(user_agent=USER_AGENT)
                    if cookie_objs:
                        context.add_cookies(cookie_objs)
                    page = context.new_page()

                    for b_url in browser_urls:
                        try:
                            page.goto(b_url, wait_until="domcontentloaded", timeout=12000)
                            page_html = page.content()
                            d = DouyinClient.extract_aweme_from_html(page_html, aweme_id)
                            if d:
                                # 自动回写更新 Cookie
                                try:
                                    new_cookies = context.cookies()
                                    if new_cookies:
                                        new_ck = "; ".join([f"{c['name']}={c['value']}" for c in new_cookies])
                                        settings["douyin_cookie"] = new_ck
                                        save_settings(settings)
                                        self.session.headers["Cookie"] = new_ck
                                except Exception:
                                    pass
                                return d
                        except Exception:
                            pass
                finally:
                    browser.close()
        except Exception as be:
            _add_log(f"⚠️ 无头浏览器渲染解析异常: {be}")

        raise Exception(f"无法获取作品 {aweme_id} 的详情，可能需要有效的 Cookie 或作品已删除")

    # ── 直播与回放 API ──────────────────────────────────

    def get_live_room_info(self, room_id: str, sec_user_id: str = "") -> dict:
        """获取直播间信息与实时流地址（多通道兜底）"""
        # 1. 尝试从 webcast.amemv.com/douyin/webcast/reflow/ 提取 RSC 页面渲染数据
        try:
            room = self._extract_room_from_webcast(room_id, sec_user_id)
            if room:
                return {"room": room, "user": room.get("owner") or room.get("ownerUser") or {}}
        except Exception:
            pass

        # 2. 尝试 live.douyin.com 网页 HTML 提取
        try:
            room = self._extract_room_from_live_web(room_id)
            if room:
                return {"room": room, "user": room.get("owner") or room.get("ownerUser") or {}}
        except Exception:
            pass

        # 3. 尝试 live.douyin.com API 接口
        self.session.headers["Referer"] = f"https://live.douyin.com/{room_id}"
        params = {
            "aid": "6383",
            "app_name": "douyin_web",
            "live_id": "1",
            "device_platform": "web",
            "language": "zh-CN",
            "enter_from": "web_live",
            "cookie_enabled": "true",
            "screen_width": "1920",
            "screen_height": "1080",
            "browser_language": "zh-CN",
            "browser_platform": "MacIntel",
            "browser_name": "Chrome",
            "browser_version": "120.0.0.0",
            "web_rid": room_id,
            "room_id_str": room_id,
        }
        if sec_user_id:
            params["sec_user_id"] = sec_user_id

        try:
            res = self.api_get(API_WEBCAST_ROOM, params, skip_sign=True)
            if res.get("status_code") == 0 and "data" in res:
                data_obj = res.get("data", {})
                if "data" in data_obj and isinstance(data_obj["data"], list) and len(data_obj["data"]) > 0:
                    return data_obj["data"][0]
                return data_obj
        except Exception:
            pass

        return {}

    def _extract_room_from_webcast(self, room_id: str, sec_user_id: str = "") -> dict:
        """从 webcast.amemv.com reflow 页面提取直播间数据"""
        url = f"https://webcast.amemv.com/douyin/webcast/reflow/{room_id}"
        if sec_user_id:
            url += f"?sec_user_id={sec_user_id}"
        resp = self.session.get(url, timeout=10)
        resp.encoding = "utf-8"
        html = resp.text

        # 1. 查找 RSC payload (self.__rsc_f.push)
        rsc_chunks = re.findall(r"self\.__rsc_f\.push\(\[1,\s*\"(.*?)\"\]\)", html, re.DOTALL)
        if rsc_chunks:
            full_text = ""
            for c in rsc_chunks:
                try:
                    full_text += json.loads(f"\"{c}\"")
                except Exception:
                    full_text += c
            idx = full_text.find("\"room\":{")
            if idx != -1:
                start = idx + 7
                depth = 0
                end = start
                for i in range(start, len(full_text)):
                    if full_text[i] == "{":
                        depth += 1
                    elif full_text[i] == "}":
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                room_str = full_text[start:end]
                room = json.loads(room_str)
                return room

        # 2. 查找 RENDER_DATA
        render_match = re.search(r'<script\s+id="RENDER_DATA"\s+type="application/json">([^<]+)</script>', html)
        if render_match:
            raw_data = urllib.parse.unquote(render_match.group(1))
            data = json.loads(raw_data)
            if isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, dict) and "room" in v:
                        return v["room"]
        return {}

    def _extract_room_from_live_web(self, room_id: str) -> dict:
        """从 live.douyin.com 页面提取直播间数据"""
        url = f"https://live.douyin.com/{room_id}"
        resp = self.session.get(url, timeout=10)
        resp.encoding = "utf-8"
        html = resp.text

        render_match = re.search(r'<script\s+id="RENDER_DATA"\s+type="application/json">([^<]+)</script>', html)
        if render_match:
            raw_data = urllib.parse.unquote(render_match.group(1))
            data = json.loads(raw_data)
            if isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, dict) and "room" in v:
                        return v["room"]
        return {}

    def get_replay_detail(self, replay_id: str) -> dict:
        """获取直播回放/剧集详情（多通道兜底）"""
        # 1. 首先尝试普通 video_detail (很多 vsdetail 在 aweme/detail 中可直接查到)
        try:
            detail = self.get_video_detail(replay_id)
            if detail:
                detail["is_live_replay"] = True
                return detail
        except Exception:
            pass

        # 2. 尝试 webcast episode info 接口
        try:
            res = self.api_get(API_REFLOW_EPISODE, {
                "episode_id": replay_id,
            }, skip_sign=True)
            if res.get("status_code") == 0 and "data" in res:
                ep_data = res.get("data", {})
                detail = self._adapt_episode_to_aweme(ep_data, replay_id)
                if detail:
                    return detail
        except Exception:
            pass

        # 3. 尝试网页 HTML 提取渲染数据 (RENDER_DATA / _ROUTER_DATA)
        try:
            detail = self._fetch_vsdetail_from_html(replay_id)
            if detail:
                return detail
        except Exception:
            pass

        raise Exception(f"无法获取回放作品 {replay_id} 的详情，可能需要有效的 Cookie 或回放已过期/被删除")

    def _adapt_episode_to_aweme(self, ep_data: dict, replay_id: str) -> dict:
        """将 webcast episode 数据格式适配为标准 aweme_detail"""
        item = ep_data.get("episode") or ep_data.get("item") or ep_data
        user = ep_data.get("user") or item.get("user") or item.get("author") or {}
        title = item.get("title") or item.get("desc") or f"直播回放_{replay_id}"

        video_info = item.get("video") or {}
        play_addr = video_info.get("play_addr") or {}
        url_list = play_addr.get("url_list") or []
        if not url_list and "stream_url" in item:
            flv_map = item["stream_url"].get("flv_pull_url") or {}
            url_list = list(flv_map.values())

        return {
            "aweme_id": replay_id,
            "desc": title,
            "author": {
                "nickname": user.get("nickname") or "未知主播",
                "sec_uid": user.get("sec_uid") or "",
            },
            "video": {
                "play_addr": {
                    "url_list": url_list
                },
                "bit_rate": video_info.get("bit_rate") or [],
                "duration": item.get("duration", 0),
            },
            "is_live_replay": True,
        }

    def _fetch_vsdetail_from_html(self, vs_id: str) -> dict:
        """从 vsdetail 网页 HTML 提取渲染数据"""
        urls_to_try = [
            f"https://www.douyin.com/vsdetail/{vs_id}",
            f"https://live.douyin.com/vsdetail/{vs_id}",
        ]
        for page_url in urls_to_try:
            try:
                resp = self.session.get(page_url, timeout=10)
                if resp.status_code != 200 or not resp.text:
                    continue
                html = resp.text

                # 1. 尝试 RENDER_DATA
                render_match = re.search(r'<script\s+id="RENDER_DATA"\s+type="application/json">([^<]+)</script>', html)
                if render_match:
                    raw_data = urllib.parse.unquote(render_match.group(1))
                    data = json.loads(raw_data)
                    aweme = self._find_aweme_in_dict(data)
                    if aweme:
                        aweme["is_live_replay"] = True
                        return aweme

                # 2. 尝试 _ROUTER_DATA
                router_match = re.search(r'window\._ROUTER_DATA\s*=\s*(\{.+?\});?</script>', html)
                if router_match:
                    data = json.loads(router_match.group(1))
                    aweme = self._find_aweme_in_dict(data)
                    if aweme:
                        aweme["is_live_replay"] = True
                        return aweme

                # 3. 尝试 __UNIVERSAL_DATA_FOR_REHYDRATION__
                univ_match = re.search(r'window\.__UNIVERSAL_DATA_FOR_REHYDRATION__\s*=\s*(\{.+?\});?</script>', html)
                if univ_match:
                    data = json.loads(univ_match.group(1))
                    aweme = self._find_aweme_in_dict(data)
                    if aweme:
                        aweme["is_live_replay"] = True
                        return aweme
            except Exception as e:
                _add_log(f"⚠️ 网页回放数据解析尝试失败: {e}")
        return {}

    @staticmethod
    def _find_aweme_in_dict(obj: Any) -> dict:
        """递归查找字典中的 aweme 或 video 结构"""
        if isinstance(obj, dict):
            if "aweme_detail" in obj and isinstance(obj["aweme_detail"], dict):
                return obj["aweme_detail"]
            if "aweme" in obj and isinstance(obj["aweme"], dict):
                return obj["aweme"]
            if "video" in obj and "desc" in obj:
                return obj
            for v in obj.values():
                res = DouyinClient._find_aweme_in_dict(v)
                if res:
                    return res
        elif isinstance(obj, list):
            for item in obj:
                res = DouyinClient._find_aweme_in_dict(item)
                if res:
                    return res
        return {}

    def get_mix_videos(self, mix_id: str, cursor: int = 0, count: int = 20) -> tuple:
        """获取合集作品列表，返回 (aweme_list, next_cursor, has_more)"""
        params = {
            "mix_id": mix_id,
            "cursor": str(cursor),
            "count": str(count),
        }
        ref_url = f"https://www.douyin.com/collection/{mix_id}"
        self.session.headers["Referer"] = ref_url
        try:
            data = self.api_get(API_MIX_AWEME, params, skip_sign=False)
        except Exception as e:
            err_str = str(e)
            if "403" in err_str or "Argus" in err_str or "Uifid" in err_str or "Forbidden" in err_str:
                _add_log(f"⚠️ 抖音合集作品列表直连受风控拦截，自动切换至浏览器会话安全通道获取 (mix_id={mix_id}, cursor={cursor})...")
                data = self._fetch_via_browser("/aweme/v1/web/mix/aweme/", method="GET", params=params, referer=ref_url)
            else:
                raise

        if data.get("status_code") != 0:
            msg = data.get("status_msg", data.get("error", "未知错误"))
            raise Exception(f"获取合集作品列表失败: {msg}")

        aweme_list = data.get("aweme_list") or []
        has_more = data.get("has_more", 0)
        if isinstance(has_more, bool):
            has_more = has_more
        else:
            has_more = int(has_more) == 1
        next_cursor = data.get("cursor", 0)

        return aweme_list, next_cursor, has_more

    def get_user_series(self, sec_uid: str, cursor: int = 0, count: int = 20) -> tuple:
        """获取用户的短剧/系列合集列表 (series/list?read_new_mix=true)"""
        params = {
            "sec_user_id": sec_uid,
            "cursor": str(cursor),
            "count": str(count),
            "read_new_mix": "true",
            "req_from": "channel_pc_web",
        }
        ref_url = f"https://www.douyin.com/user/{sec_uid}"
        self.session.headers["Referer"] = ref_url
        try:
            try:
                data = self.api_get("https://www.douyin.com/aweme/v1/web/series/list/", params, skip_sign=False)
            except Exception as e:
                err_str = str(e)
                if "403" in err_str or "Argus" in err_str or "Uifid" in err_str or "Forbidden" in err_str:
                    data = self._fetch_via_browser("/aweme/v1/web/series/list/", method="GET", params=params, referer=ref_url)
                else:
                    raise
            series_infos = data.get("series_infos") or []
            has_more = data.get("has_more", 0)
            if isinstance(has_more, bool):
                has_more = has_more
            else:
                has_more = int(has_more) == 1
            next_cursor = data.get("cursor", 0)
            # 整形成 mix_infos 结构以兼容下游
            mix_like_items = []
            for entry in series_infos:
                if isinstance(entry, dict) and entry.get("series_id"):
                    mix_like_items.append({
                        "mix_id": str(entry.get("series_id") or ""),
                        "mix_name": entry.get("series_name") or "",
                        "statis": entry.get("stats") or {},
                        "author": entry.get("author") or {},
                        "cover_url": entry.get("cover_url"),
                    })
            return mix_like_items, next_cursor, has_more
        except Exception as e:
            _add_log(f"⚠️ 获取 series 合集列表分支异常: {e}")
            return [], 0, False

    def get_user_mixes(self, sec_uid: str, cursor: int = 0, count: int = 20) -> tuple:
        """获取用户的合集列表，合并传统 mix/list 与新版 series/list 双来源，返回 (mix_infos, next_cursor, has_more)"""
        mix_infos = []
        next_cursor = 0
        has_more = False
        mix_error = None

        # 1. 请求传统合集 mix/list
        params = {
            "sec_user_id": sec_uid,
            "cursor": str(cursor),
            "count": str(count),
        }
        ref_url = f"https://www.douyin.com/user/{sec_uid}"
        self.session.headers["Referer"] = ref_url
        try:
            try:
                data = self.api_get("https://www.douyin.com/aweme/v1/web/mix/list/", params, skip_sign=False)
            except Exception as e:
                err_str = str(e)
                if "403" in err_str or "Argus" in err_str or "Uifid" in err_str or "Forbidden" in err_str:
                    _add_log(f"⚠️ 抖音合集列表直连受风控拦截，自动切换至浏览器会话安全通道获取 (cursor={cursor})...")
                    data = self._fetch_via_browser("/aweme/v1/web/mix/list/", method="GET", params=params, referer=ref_url)
                else:
                    raise
            if data.get("status_code") == 0:
                mix_infos = data.get("mix_infos") or []
                hm = data.get("has_more", 0)
                has_more = hm if isinstance(hm, bool) else int(hm) == 1
                next_cursor = data.get("cursor", 0)
        except Exception as e:
            mix_error = e

        # 2. 首页时尝试拉取短剧/系列合集 series/list (2026-09 最新结构，互不相交)
        if cursor == 0:
            series_items, _, _ = self.get_user_series(sec_uid, cursor=0, count=count)
            if series_items:
                existing_ids = {str(item.get("mix_id")) for item in mix_infos if item.get("mix_id")}
                for s_item in series_items:
                    if str(s_item.get("mix_id")) not in existing_ids:
                        mix_infos.append(s_item)
                        existing_ids.add(str(s_item.get("mix_id")))

        # 如果两者都空且传统合集遇到明确错误，再抛出异常
        if not mix_infos and mix_error is not None and cursor == 0:
            raise mix_error

        return mix_infos, next_cursor, has_more


    def get_music_detail(self, music_id: str) -> dict:
        """获取音乐详情，带兜底"""
        try:
            data = self.api_get(API_MUSIC_DETAIL, {
                "music_id": music_id,
            }, skip_sign=True)
            if data.get("status_code") == 0 and data.get("music_info"):
                return data["music_info"]
        except Exception:
            pass

        try:
            data = self.api_get(API_MUSIC_DETAIL, {
                "music_id": music_id,
            }, skip_sign=False)
            if data.get("status_code") == 0 and data.get("music_info"):
                return data["music_info"]
        except Exception:
            pass

        raise Exception(f"无法获取音乐 {music_id} 的详情，可能需要有效的 Cookie 或作品已删除")

    # ── 用户作品列表 API ──────────────────────────────────

    def get_user_videos(self, sec_uid: str, max_cursor: int = 0, count: int = 18) -> tuple:
        """获取用户发布的作品列表，返回 (aweme_list, next_cursor, has_more)"""
        params = {
            "publish_video_strategy_type": "2",
            "sec_user_id": sec_uid,
            "max_cursor": str(max_cursor),
            "locate_query": "false",
            "show_live_replay_strategy": "1",
            "need_time_list": "0",
            "time_list_query": "0",
            "whale_cut_token": "",
            "count": str(count),
        }
        ref_url = f"https://www.douyin.com/user/{sec_uid}"
        self.session.headers["Referer"] = ref_url
        try:
            data = self.api_get(API_USER_POST, params, skip_sign=True)
        except Exception as e:
            err_str = str(e)
            if "403" in err_str or "Argus" in err_str or "Uifid" in err_str or "Forbidden" in err_str:
                _add_log(f"⚠️ 抖音用户作品列表直连受风控拦截，自动切换至浏览器会话安全通道获取 (cursor={max_cursor})...")
                data = self._fetch_via_browser("/aweme/v1/web/aweme/post/", method="GET", params=params, referer=ref_url)
            else:
                raise

        if data.get("status_code") != 0:
            msg = data.get("status_msg", data.get("error", "未知错误"))
            raise Exception(f"获取用户作品列表失败: {msg}")

        aweme_list = data.get("aweme_list") or []
        has_more = data.get("has_more", 0)
        if isinstance(has_more, bool):
            has_more = has_more
        else:
            has_more = int(has_more) == 1
        next_cursor = data.get("max_cursor", 0)

        return aweme_list, next_cursor, has_more

    def get_user_stories(self, sec_uid: str, max_cursor: int = 0, count: int = 18) -> tuple:
        """获取用户日常列表，返回 (aweme_list, next_cursor, has_more)"""
        params = {
            "publish_video_strategy_type": "1",
            "sec_user_id": sec_uid,
            "max_cursor": str(max_cursor),
            "locate_query": "false",
            "show_live_replay_strategy": "1",
            "need_time_list": "0",
            "time_list_query": "0",
            "whale_cut_token": "",
            "count": str(count),
        }
        ref_url = f"https://www.douyin.com/user/{sec_uid}"
        self.session.headers["Referer"] = ref_url
        try:
            data = self.api_get(API_USER_POST, params, skip_sign=True)
        except Exception as e:
            err_str = str(e)
            if "403" in err_str or "Argus" in err_str or "Uifid" in err_str or "Forbidden" in err_str:
                _add_log(f"⚠️ 抖音用户日常列表直连受风控拦截，自动切换至浏览器会话安全通道获取 (cursor={max_cursor})...")
                data = self._fetch_via_browser("/aweme/v1/web/aweme/post/", method="GET", params=params, referer=ref_url)
            else:
                raise

        if data.get("status_code") != 0:
            msg = data.get("status_msg", data.get("error", "未知错误"))
            raise Exception(f"获取用户日常列表失败: {msg}")

        aweme_list = data.get("aweme_list") or []
        has_more = data.get("has_more", 0)
        if isinstance(has_more, bool):
            has_more = has_more
        else:
            has_more = int(has_more) == 1
        next_cursor = data.get("max_cursor", 0)

        return aweme_list, next_cursor, has_more

    def get_user_replays(self, sec_uid: str, max_cursor: int = 0, count: int = 18) -> tuple:
        """获取博主直播回放列表，返回 (aweme_list, next_cursor, has_more)"""
        params = {
            "publish_video_strategy_type": "2",
            "sec_user_id": sec_uid,
            "max_cursor": str(max_cursor),
            "locate_query": "false",
            "show_live_replay_strategy": "1",
            "need_time_list": "0",
            "time_list_query": "0",
            "whale_cut_token": "",
            "count": str(count),
        }
        ref_url = f"https://www.douyin.com/user/{sec_uid}"
        self.session.headers["Referer"] = ref_url
        try:
            data = self.api_get(API_USER_POST, params, skip_sign=True)
        except Exception as e:
            err_str = str(e)
            if "403" in err_str or "Argus" in err_str or "Uifid" in err_str or "Forbidden" in err_str:
                _add_log(f"⚠️ 抖音博主直播回放列表直连受风控拦截，自动切换至浏览器会话安全通道获取 (cursor={max_cursor})...")
                data = self._fetch_via_browser("/aweme/v1/web/aweme/post/", method="GET", params=params, referer=ref_url)
            else:
                raise

        if data.get("status_code") != 0:
            msg = data.get("status_msg", data.get("error", "未知错误"))
            raise Exception(f"获取用户回放列表失败: {msg}")

        all_aweme = data.get("aweme_list") or []
        replays = []
        for item in all_aweme:
            if item.get("aweme_type") in [101, 103] or item.get("is_live_replay") is True or item.get("vs_entry") is not None:
                item["is_live_replay"] = True
                replays.append(item)

        has_more = data.get("has_more", 0)
        if isinstance(has_more, bool):
            has_more = has_more
        else:
            has_more = int(has_more) == 1
        next_cursor = data.get("max_cursor", 0)

        return replays, next_cursor, has_more

    def get_aweme_comments(self, aweme_id: str, cursor: int = 0, count: int = 20, include_replies: bool = False) -> dict:
        """
        获取单个作品的评论列表（单页）
        参考 douyin-downloader: /aweme/v1/web/comment/list/
        """
        self.session.headers["Referer"] = f"https://www.douyin.com/video/{aweme_id}"
        params = {
            "aweme_id": str(aweme_id),
            "cursor": str(cursor),
            "count": str(min(count, 20)),
            "item_type": "0",
            "insert_ids": "",
            "whale_cut_token": "",
            "cut_version": "1",
            "rcFT": "",
        }
        res = self.api_get("https://www.douyin.com/aweme/v1/web/comment/list/", params, skip_sign=False)
        comments = res.get("comments") or []
        if include_replies:
            for c in comments:
                if isinstance(c, dict):
                    cid = c.get("cid") or c.get("comment_id")
                    reply_total = int(c.get("reply_comment_total") or 0)
                    if cid and reply_total > 0:
                        try:
                            replies_res = self.get_aweme_comment_replies(aweme_id=str(aweme_id), comment_id=str(cid), count=count)
                            c["_replies"] = replies_res.get("comments") or []
                        except Exception:
                            c["_replies"] = []
        return res

    def get_aweme_comment_replies(self, aweme_id: str, comment_id: str, cursor: int = 0, count: int = 20) -> dict:
        """
        获取单条评论的二级回复列表
        参考 douyin-downloader: /aweme/v1/web/comment/list/reply/
        """
        self.session.headers["Referer"] = f"https://www.douyin.com/video/{aweme_id}"
        params = {
            "item_id": str(aweme_id),
            "comment_id": str(comment_id),
            "cursor": str(cursor),
            "count": str(count),
        }
        return self.api_get("https://www.douyin.com/aweme/v1/web/comment/list/reply/", params, skip_sign=False)

    def get_all_comments(self, aweme_id: str, max_comments: int = 0, include_replies: bool = False, delay: float = 0.3) -> list:
        """
        自动翻页抓取作品的全部（或上限条数）评论
        """
        all_comments = []
        cursor = 0
        seen_ids = set()

        while True:
            res = self.get_aweme_comments(aweme_id, cursor=cursor, count=20, include_replies=include_replies)
            items = res.get("comments") or []
            if not items:
                break

            for item in items:
                if not isinstance(item, dict):
                    continue
                cid = item.get("cid") or item.get("comment_id")
                key = str(cid) if cid else None
                if key and key in seen_ids:
                    continue
                if key:
                    seen_ids.add(key)
                all_comments.append(item)
                if 0 < max_comments <= len(all_comments):
                    return all_comments[:max_comments]

            has_more = res.get("has_more", 0)
            if isinstance(has_more, bool):
                has_more = has_more
            else:
                has_more = int(has_more) == 1
            if not has_more:
                break

            next_cursor = res.get("cursor") or 0
            if next_cursor == cursor:
                break
            cursor = next_cursor
            time.sleep(delay)

        return all_comments

    # ── 解析资源信息 ──────────────────────────────────────

    @staticmethod
    def _extract_live_photo_url(img: dict) -> str:
        """从单张图结构中提取 Live Photo 视频 URL（多字段兜底）。"""
        if not isinstance(img, dict):
            return ""

        def _from_addr(addr) -> str:
            if isinstance(addr, list) and addr:
                first = addr[0]
                if isinstance(first, dict):
                    return first.get("src") or first.get("url") or ""
                if isinstance(first, str):
                    return first
            if isinstance(addr, dict):
                urls = addr.get("url_list") or addr.get("urlList") or []
                if urls:
                    return urls[0] if isinstance(urls[0], str) else (urls[0].get("src") or urls[0].get("url") or "")
                return addr.get("src") or addr.get("url") or ""
            if isinstance(addr, str) and addr.startswith("http"):
                return addr
            return ""

        video = img.get("video")
        if isinstance(video, dict):
            for key in ("play_addr", "playAddr", "play_addr_h264", "playAddrH264",
                         "download_addr", "downloadAddr"):
                url = _from_addr(video.get(key))
                if url:
                    return url
            bit_rates = video.get("bit_rate") or video.get("bitRate") or video.get("bitRateList") or []
            if isinstance(bit_rates, list):
                for br in bit_rates:
                    if not isinstance(br, dict):
                        continue
                    url = _from_addr(br.get("play_addr") or br.get("playAddr"))
                    if url:
                        return url

        for key in ("live_photo", "livePhoto", "animated_url", "animatedUrl"):
            raw = img.get(key)
            if isinstance(raw, str) and raw.startswith("http"):
                return raw
            if isinstance(raw, dict):
                url = _from_addr(raw.get("play_addr") or raw.get("playAddr") or raw)
                if url:
                    return url
        return ""

    @staticmethod
    def parse_media_info(detail: dict) -> dict:
        """
        从 aweme_detail 中提取下载所需的资源信息
        同时兼容 API 字段 (snake_case) 与网页 SSR/RSC 字段 (camelCase)
        返回: {type, title, urls, live_photo_urls, aweme_id, nickname, cover, music_url}
        """
        aweme_id = detail.get("aweme_id") or detail.get("awemeId") or "unknown"
        desc = detail.get("desc") or detail.get("item_title") or detail.get("itemTitle") or detail.get("preview_title") or ""
        title = clean_filename(desc) if desc else f"抖音作品_{aweme_id}"

        author = detail.get("author") or detail.get("authorInfo") or {}
        author_nickname = ""
        if isinstance(author, dict):
            author_nickname = author.get("nickname", "")
        nickname = clean_filename(author_nickname.strip()) if author_nickname else ""
        if not nickname or nickname == "untitled":
            nickname = "未知用户"

        # 判断类型：images 存在且非空 → 图文；否则 → 视频
        images = detail.get("images") or detail.get("imagesList") or detail.get("imgList")
        if not images:
            image_post_info = detail.get("image_post_info") or detail.get("imagePostInfo")
            if isinstance(image_post_info, dict):
                images = image_post_info.get("images") or image_post_info.get("imagesList")

        is_replay = bool(detail.get("is_live_replay") or detail.get("aweme_type") == 101 or detail.get("awemeType") == 101)

        # 提取封面
        cover = ""
        video = detail.get("video") or {}
        if isinstance(video, dict):
            for ck in ["origin_cover", "originCover", "cover", "dynamic_cover", "dynamicCover"]:
                c_dict = video.get(ck)
                if isinstance(c_dict, dict):
                    c_urls = c_dict.get("url_list") or c_dict.get("urlList") or []
                    if c_urls:
                        cover = c_urls[0]
                        break
                elif isinstance(c_dict, str) and c_dict.startswith("http"):
                    cover = c_dict
                    break
            if not cover:
                cover_list = video.get("coverUrlList") or video.get("cover_url_list") or []
                if cover_list:
                    cover = cover_list[0]
                elif isinstance(video.get("cover"), str) and video["cover"].startswith("http"):
                    cover = video["cover"]

        if not cover and images and isinstance(images, list) and len(images) > 0:
            first_img = images[0]
            if isinstance(first_img, dict):
                c_urls = first_img.get("url_list") or first_img.get("urlList") or first_img.get("download_url_list") or first_img.get("downloadUrlList") or []
                if c_urls:
                    cover = c_urls[0]
        if not cover and "cover" in detail and isinstance(detail["cover"], dict):
            c_urls = detail["cover"].get("url_list") or detail["cover"].get("urlList") or []
            if c_urls:
                cover = c_urls[0]

        if images and isinstance(images, list) and len(images) > 0:
            # 图文类型
            urls = []
            live_photo_urls = []
            for img in images:
                url_list = img.get("url_list") or img.get("urlList") or img.get("download_url_list") or img.get("downloadUrlList") or []
                if not url_list and "display_image" in img:
                    display_image = img.get("display_image")
                    if isinstance(display_image, dict):
                        url_list = display_image.get("url_list") or display_image.get("urlList") or []
                if not url_list and "owner_watermark_image" in img:
                    watermark_image = img.get("owner_watermark_image")
                    if isinstance(watermark_image, dict):
                        url_list = watermark_image.get("url_list") or watermark_image.get("urlList") or []

                if url_list:
                    # 取最后一个（通常是最高清）
                    urls.append(url_list[-1] if len(url_list) > 1 else url_list[0])

                # 实况照片 (Live Photo) 视频流检测（多字段兜底）
                live_photo_urls.append(DouyinClient._extract_live_photo_url(img))

            # 提取背景音乐 URL
            music_url = ""
            music = detail.get("music")
            if music and isinstance(music, dict):
                play_url = music.get("play_url") or music.get("playUrl")
                if play_url and isinstance(play_url, dict):
                    music_urls = play_url.get("url_list") or play_url.get("urlList") or []
                    if music_urls:
                        music_url = music_urls[0]
                elif isinstance(play_url, str) and play_url.startswith("http"):
                    music_url = play_url

            return {
                "type": "image",
                "is_replay": False,
                "title": title,
                "cover": cover,
                "urls": urls,
                "live_photo_urls": live_photo_urls,
                "aweme_id": aweme_id,
                "nickname": nickname,
                "music_url": music_url,
            }
        else:
            # 视频类型 — 从多个地址源中选择最佳无水印版本
            url_candidates = []

            # 1. bit_rate / bitRateList 中的最佳质量
            bit_rates = video.get("bit_rate") or video.get("bitRateList") or []
            if bit_rates:
                sorted_rates = sorted(bit_rates, key=lambda x: (x.get("data_size") or x.get("dataSize") or x.get("bit_rate") or 0), reverse=True)
                for br in sorted_rates:
                    play_addr = br.get("play_addr") or br.get("playAddr")
                    if isinstance(play_addr, list):
                        for item in play_addr:
                            s = item.get("src") or item.get("url")
                            if s and "watermark=1" not in s.lower():
                                url_candidates.append(s)
                                break
                    elif isinstance(play_addr, dict):
                        url_list = play_addr.get("url_list") or play_addr.get("urlList") or []
                        for u in url_list:
                            if u and "watermark=1" not in u.lower() and "playwm" not in u.lower():
                                url_candidates.append(u)
                                break

            # 2. play_addr_h264
            h264 = video.get("play_addr_h264") or video.get("playAddrH264") or {}
            if isinstance(h264, dict):
                for u in (h264.get("url_list") or h264.get("urlList") or []):
                    if u and "watermark=1" not in u.lower() and "playwm" not in u.lower():
                        url_candidates.append(u)
                        break

            # 3. play_addr (主播放地址)
            play_addr = video.get("play_addr") or video.get("playAddr")
            if isinstance(play_addr, list):
                for item in play_addr:
                    s = item.get("src") or item.get("url")
                    if s:
                        url_candidates.append(s)
            elif isinstance(play_addr, dict):
                for u in (play_addr.get("url_list") or play_addr.get("urlList") or []):
                    if u:
                        clean = u.replace("watermark=1", "watermark=0").replace("playwm", "play")
                        url_candidates.append(clean)
                        break

            # 4. download_addr
            download_addr = video.get("download_addr") or video.get("downloadAddr")
            if isinstance(download_addr, dict):
                for u in (download_addr.get("url_list") or download_addr.get("urlList") or []):
                    if u:
                        url_candidates.append(u)
                        break

            # 5. play_addr_lowbr
            lowbr = video.get("play_addr_lowbr")
            if isinstance(lowbr, dict):
                for u in (lowbr.get("url_list") or lowbr.get("urlList") or []):
                    if u:
                        url_candidates.append(u)
                        break

            # 选择第一个无水印的链接
            chosen_url = ""
            for u in url_candidates:
                lower = u.lower()
                if "watermark=1" not in lower and "playwm" not in lower:
                    chosen_url = u
                    break
            if not chosen_url and url_candidates:
                chosen_url = url_candidates[0]

            return {
                "type": "video",
                "is_replay": is_replay,
                "title": title,
                "cover": cover,
                "urls": [chosen_url] if chosen_url else [],
                "aweme_id": aweme_id,
                "nickname": nickname,
            }


