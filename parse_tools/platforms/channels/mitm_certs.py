# -*- coding: utf-8 -*-
"""
WeChat Channels MITM Interception Proxy Server
Handles SSL interception, CA root trust, system proxy control, and custom script injection.
"""

import os
import re
import sys
import json
import time
import threading
import subprocess
from pathlib import Path
from parse_tools.core.config import DATA_DIR

# Force unbuffered output for real-time background logging
import builtins
def print(*args, **kwargs):
    kwargs.setdefault('flush', True)
    builtins.print(*args, **kwargs)

CA_KEY_PATH = DATA_DIR / "ca.key"
CA_CERT_PATH = DATA_DIR / "ca.crt"
CERTS_DIR = DATA_DIR / "certs"
# mitmproxy 的配置目录:复用我们已生成并已被系统信任的 CA,
# 避免 mitmproxy 自己另生成一张未受信任的 CA(那会导致握手失败 → 页面疯狂重刷)。
MITM_CONFDIR = DATA_DIR / "mitm"

# 拦截目标主机(仅对这两个域名做 TLS 解密,其余全部透传)
TARGET_HOSTS = ("channels.weixin.qq.com", "mp.weixin.qq.com", "res.wx.qq.com")

# Create certs directory
CERTS_DIR.mkdir(parents=True, exist_ok=True)

PROXY_SESSION_ID = str(int(time.time()))

# 保存 MITM 启动前的 NO_PROXY 环境变量，用于停止时还原
_original_no_proxy = None
_last_captured_cred_hash = None
_last_captured_time = 0

# ── 证书管理 (Certificate Management) ──────────────────────────

def ensure_ca_certificates():
    if CA_KEY_PATH.exists() and CA_CERT_PATH.exists():
        return CA_KEY_PATH, CA_CERT_PATH
        
    # Generate CA
    import datetime
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Guangdong"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Shenzhen"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "WeChat Channels Downloader"),
        x509.NameAttribute(NameOID.COMMON_NAME, "Channels Interceptor CA"),
    ])
    
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    ).not_valid_after(
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3650)
    ).add_extension(
        x509.BasicConstraints(ca=True, path_length=None), critical=True
    ).add_extension(
        x509.KeyUsage(
            digital_signature=True,
            content_commitment=False,
            key_encipherment=False,
            data_encipherment=False,
            key_agreement=False,
            key_cert_sign=True,
            crl_sign=True,
            encipher_only=False,
            decipher_only=False
        ), critical=True
    ).sign(private_key, hashes.SHA256())
    
    with open(CA_KEY_PATH, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))
    with open(CA_CERT_PATH, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    return CA_KEY_PATH, CA_CERT_PATH

def prepare_mitm_confdir():
    """把已生成、已受系统信任的 CA(ca.key + ca.crt)写入 mitmproxy 的
    配置目录,文件名为 mitmproxy-ca.pem(key 与 cert 拼接的 PEM)。
    这样 mitmproxy 用我们这张 CA 去签发各站点的叶子证书,沿用现有的
    安装/信任/卸载逻辑(CN=Channels Interceptor CA),不会另起一张新 CA。
    返回 confdir 路径。
    """
    ensure_ca_certificates()
    MITM_CONFDIR.mkdir(parents=True, exist_ok=True)
    ca_pem = MITM_CONFDIR / "mitmproxy-ca.pem"
    key_bytes = CA_KEY_PATH.read_bytes()
    cert_bytes = CA_CERT_PATH.read_bytes()
    combined = key_bytes
    if not combined.endswith(b"\n"):
        combined += b"\n"
    combined += cert_bytes
    # 仅在内容变化时重写,避免每次启动都触碰文件
    if not ca_pem.exists() or ca_pem.read_bytes() != combined:
        ca_pem.write_bytes(combined)
    # mitmproxy 还会用到 *-ca-cert.pem 等派生文件;删掉旧的让其按新 CA 重建
    for stale in ("mitmproxy-ca-cert.pem", "mitmproxy-ca-cert.cer",
                  "mitmproxy-ca-cert.p12", "mitmproxy-dhparam.pem"):
        p = MITM_CONFDIR / stale
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass
    return MITM_CONFDIR


def _run_certutil(args, check=False):
    """
    Spawn certutil safely, even inside a PyInstaller onefile package.

    PyInstaller prepends sys._MEIPASS to the process PATH, so a spawned certutil.exe
    resolves its dependent DLLs from the bundle dir and fails to initialize with
    STATUS_DLL_INIT_FAILED (0xc0000142). To resolve this robustly, we isolate the
    child process by setting its PATH environment variable to ONLY contain Windows
    system directories (System32 and SystemRoot), preventing any third-party or
    packaged DLLs from polluting the search path.
    """
    if sys.platform == "win32":
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        system32 = os.path.join(system_root, "System32")
        certutil = os.path.join(system32, "certutil.exe")
        env = os.environ.copy()
        # Force the PATH to contain ONLY system paths to completely isolate certutil.exe
        # from any outside or packaged DLLs that might conflict.
        env["PATH"] = f"{system32}{os.pathsep}{system_root}"
        flags = 0x08000000  # CREATE_NO_WINDOW: 彻底阻止 Windows 弹出的黑色命令行闪烁窗口
        return subprocess.run(
            [certutil] + list(args),
            capture_output=True, check=check, env=env, cwd=system32,
            creationflags=flags
        )
    return subprocess.run(["certutil"] + list(args), capture_output=True, check=check)

_cert_trusted_cache = {"ts": 0.0, "val": False}

def check_cert_trusted():
    now = time.time()
    if now - _cert_trusted_cache["ts"] < 4.0:
        return _cert_trusted_cache["val"]

    def _eval():
        if sys.platform == "darwin":
            try:
                # 0. 先检查证书是否在钥匙串中存在，若不存在则必定未信任
                out_find = subprocess.run(
                    ["security", "find-certificate", "-c", "Channels Interceptor CA"],
                    capture_output=True
                )
                if out_find.returncode != 0:
                    return False

                def has_valid_trust_count(output_text):
                    lines = output_text.splitlines()
                    for i, line in enumerate(lines):
                        if "Channels Interceptor CA" in line:
                            for j in range(i + 1, min(i + 5, len(lines))):
                                if "Number of trust settings" in lines[j]:
                                    match = re.search(r"Number of trust settings\s*:\s*(\d+)", lines[j])
                                    if match:
                                        return int(match.group(1)) > 0
                            return False
                    return False

                # 1. Check System-wide domain trust settings
                out_d = subprocess.run(["security", "dump-trust-settings", "-d"], capture_output=True, text=True)
                if out_d.returncode == 0 and "Channels Interceptor CA" in out_d.stdout:
                    if has_valid_trust_count(out_d.stdout):
                        return True
                
                # 2. Check User domain trust settings (installed via fallback to login keychain)
                out_s = subprocess.run(["security", "dump-trust-settings", "-s"], capture_output=True, text=True)
                if out_s.returncode == 0 and "Channels Interceptor CA" in out_s.stdout:
                    if has_valid_trust_count(out_s.stdout):
                        return True
                        
                # 3. Check Default domain trust settings
                out = subprocess.run(["security", "dump-trust-settings"], capture_output=True, text=True)
                if out.returncode == 0 and "Channels Interceptor CA" in out.stdout:
                    if has_valid_trust_count(out.stdout):
                        return True

                return False
            except Exception:
                return False
        elif sys.platform == "win32":
            try:
                out = _run_certutil(["-verifystore", "-user", "root", "Channels Interceptor CA"])
                if out.returncode == 0:
                    return True
                out2 = _run_certutil(["-verifystore", "root", "Channels Interceptor CA"])
                if out2.returncode == 0:
                    return True
                return False
            except Exception:
                return False
        return False

    val = _eval()
    _cert_trusted_cache["ts"] = now
    _cert_trusted_cache["val"] = val
    return val

def _delete_all_matching_mac_certs(common_name: str = "Channels Interceptor CA"):
    """安全清空钥匙串中所有同名（包括历史重复/冲突的）证书，通过 SHA-1 哈希精准删除以杜绝歧义错误。"""
    try:
        res = subprocess.run(["security", "find-certificate", "-a", "-c", common_name, "-Z"], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout:
            hashes = re.findall(r"SHA-1 hash:\s*([0-9A-Fa-f]+)", res.stdout)
            for h in set(hashes):
                subprocess.run(["security", "delete-certificate", "-Z", h], capture_output=True)
                subprocess.run(["security", "delete-certificate", "-Z", h, "/Library/Keychains/System.keychain"], capture_output=True)
    except Exception:
        pass
    try:
        subprocess.run(["security", "delete-certificate", "-c", common_name], capture_output=True)
    except Exception:
        pass


def install_system_cert(ca_cert_path):
    if check_cert_trusted():
        return True
        
    if sys.platform == "darwin":
        # 1. 尝试直接安装至用户 Login 钥匙串
        try:
            keychain_path = os.path.expanduser("~/Library/Keychains/login.keychain-db")
            if not os.path.exists(keychain_path):
                keychain_path = os.path.expanduser("~/Library/Keychains/login.keychain")
            res = subprocess.run([
                "security", "add-trusted-cert",
                "-r", "trustRoot",
                "-p", "ssl",
                "-k", keychain_path,
                str(ca_cert_path)
            ], capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and check_cert_trusted():
                return True
        except Exception as e:
            print(f"Login keychain installation note: {e}")

        # 2. 唤起系统提权弹窗安装至系统钥匙串 (/Library/Keychains/System.keychain)
        try:
            cert_str = str(ca_cert_path)
            inner = f"/usr/bin/security add-trusted-cert -d -r trustRoot -p ssl -k /Library/Keychains/System.keychain '{cert_str}'"
            osa = f'do shell script "{inner}" with administrator privileges'
            res = subprocess.run(["osascript", "-e", osa], capture_output=True, text=True, timeout=30)
            if res.returncode == 0 and check_cert_trusted():
                return True
        except Exception as system_err:
            print(f"System keychain osascript failed: {system_err}")

        return check_cert_trusted()
    elif sys.platform == "win32":
        try:
            system_root = os.environ.get("SystemRoot", r"C:\Windows")
            system32 = os.path.join(system_root, "System32")
            certutil = os.path.join(system32, "certutil.exe")
            env = os.environ.copy()
            env["PATH"] = f"{system32}{os.pathsep}{system_root}"
            # 向 CurrentUser/Root 导入自签名 CA 时，Windows 会弹出系统安全警告提示用户确认
            # 此处不设隐藏窗口 flags，并设置合理超时，确保系统弹窗能正常展示给用户点击确认
            subprocess.run(
                [certutil, "-f", "-addstore", "-user", "root", str(ca_cert_path)],
                capture_output=True, env=env, cwd=system32, timeout=20
            )
            return check_cert_trusted()
        except Exception as e:
            print(f"Failed to install Win cert: {e}")
            return check_cert_trusted()
    return False

def uninstall_system_cert():
    if sys.platform == "darwin":
        # 0. 若本身已不在钥匙串中且未受信任，直接判定为已卸载
        out_find = subprocess.run(
            ["security", "find-certificate", "-c", "Channels Interceptor CA"],
            capture_output=True
        )
        if out_find.returncode != 0 and not check_cert_trusted():
            return True

        cert_path = str(CA_CERT_PATH)
        # 1. 通过 SHA-1 哈希彻底清理用户登录钥匙串中的同名证书
        _delete_all_matching_mac_certs("Channels Interceptor CA")

        # 2. 清理用户域信任设置
        if CA_CERT_PATH.exists():
            try:
                subprocess.run(["security", "remove-trusted-cert", cert_path], capture_output=True)
            except Exception:
                pass

        # 3. 仅当证书确实存在于 System.keychain 时才调起系统管理员权限弹窗进行删除
        in_sys_kc = False
        try:
            r_sys = subprocess.run(
                ["security", "find-certificate", "-c", "Channels Interceptor CA", "/Library/Keychains/System.keychain"],
                capture_output=True
            )
            in_sys_kc = (r_sys.returncode == 0)
        except Exception:
            pass

        if in_sys_kc and CA_CERT_PATH.exists():
            inner = (
                f"/usr/bin/security remove-trusted-cert -d '{cert_path}' 2>/dev/null || true; "
                "/usr/bin/security delete-certificate -c 'Channels Interceptor CA' "
                "/Library/Keychains/System.keychain 2>/dev/null || true"
            )
            osa = (
                'do shell script "' + inner.replace('"', '\"') + '" '
                'with administrator privileges'
            )
            try:
                subprocess.run(["osascript", "-e", osa], capture_output=True, timeout=15)
            except Exception as e:
                print(f"osascript uninstall failed: {e}")

        # 4. 再次检查钥匙串：若已无该证书即代表卸载成功
        out_find_after = subprocess.run(
            ["security", "find-certificate", "-c", "Channels Interceptor CA"],
            capture_output=True
        )
        if out_find_after.returncode != 0:
            return True

        still_trusted = check_cert_trusted()
        if still_trusted:
            print("Cert still trusted after uninstall attempt")
        return not still_trusted
    elif sys.platform == "win32":
        try:
            _run_certutil(["-delstore", "-user", "root", "Channels Interceptor CA"])
            _run_certutil(["-delstore", "root", "Channels Interceptor CA"])
            return True
        except Exception as e:
            print(f"Failed to delete Win cert: {e}")
            return False
    return False

def get_active_mac_service():
    try:
        nwi_out = subprocess.check_output(["scutil", "--nwi"], timeout=2).decode("utf-8")
        match = re.search(r"Network interfaces:\s*([^\s]+)", nwi_out)
        if match:
            iface = match.group(1)
            ports_out = subprocess.check_output(["networksetup", "-listallhardwareports"], timeout=2).decode("utf-8")
            blocks = ports_out.split("Hardware Port:")
            for block in blocks:
                block = block.strip()
                if not block:
                    continue
                lines = block.split("\n")
                service = lines[0].strip()
                if f"Device: {iface}" in block or any(f"Device: {iface}" in l for l in lines):
                    return service
    except Exception as e:
        print(f"Error getting active service: {e}")
    return "Wi-Fi"

_original_socks_state = {}

def get_all_mac_network_services():
    """获取 macOS 上所有有效的网络服务名称列表（如 'USB 10/100 LAN', 'Wi-Fi' 等）"""
    services = []
    try:
        out = subprocess.check_output(["networksetup", "-listallnetworkservices"], timeout=3).decode("utf-8")
        for line in out.splitlines():
            line = line.strip()
            if line and not line.startswith("*") and "An asterisk" not in line:
                services.append(line)
    except Exception as e:
        print(f"Error listing network services: {e}")
    if not services:
        services = ["Wi-Fi"]
    return services

import socket

def _is_tcp_port_open(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False

def detect_upstream_proxy() -> str | None:
    """智能探测本机系统当前原本正在运行并启用的 VPN / Web 代理服务。
    仅在用户系统网络配置中明确开启了代理服务时才返回上游代理进行链式转发。
    避免盲目扫描本地端口导致国内微信请求被误转发给已断开或无效的上游代理造成页面无限转圈加载。
    """
    # 1. 检查 macOS 系统中原有的 Web 代理设置
    if sys.platform == "darwin":
        try:
            services = get_all_mac_network_services()
            active = get_active_mac_service()
            if active in services:
                services.remove(active)
                services.insert(0, active)
            for s in services:
                for opt in ("-getwebproxy", "-getsecurewebproxy", "-getsocksfirewallproxy"):
                    try:
                        out = subprocess.check_output(["networksetup", opt, s], timeout=1.5, text=True)
                        if "Enabled: Yes" in out:
                            m_srv = re.search(r"Server:\s*(\S+)", out)
                            m_prt = re.search(r"Port:\s*(\d+)", out)
                            if m_srv and m_prt:
                                srv, prt = m_srv.group(1), int(m_prt.group(1))
                                if prt not in (5202, 5200) and _is_tcp_port_open(srv, prt):
                                    if opt == "-getsocksfirewallproxy":
                                        # mitmproxy 的 upstream 模式仅支持 HTTP/HTTPS 代理协议。
                                        # 检测该端口是否同时支持 HTTP 代理请求（如 Clash/v2ray/Shadowrocket 的 mixed-port），
                                        # 若支持则以 http:// 格式供 mitmproxy 链式转发；若为纯 SOCKS5 端口则跳过以防抛出 Invalid server scheme 异常。
                                        try:
                                            with socket.create_connection((srv, prt), timeout=0.3) as s:
                                                s.sendall(b"CONNECT 127.0.0.1:80 HTTP/1.1\r\nHost: 127.0.0.1:80\r\n\r\n")
                                                s.settimeout(0.3)
                                                resp = s.recv(16)
                                                if resp.startswith(b"HTTP/"):
                                                    return f"http://{srv}:{prt}"
                                        except Exception:
                                            pass
                                        continue
                                    return f"http://{srv}:{prt}"
                    except Exception:
                        pass
        except Exception:
            pass

    # 2. 检查 Windows 注册表中原有的 ProxyServer（仅在 ProxyEnable 为 1 时生效）
    elif sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                0,
                winreg.KEY_READ
            )
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
            winreg.CloseKey(key)
            if enabled and server:
                if "=" in server:
                    parts = dict(p.split("=", 1) for p in server.split(";") if "=" in p)
                    server = parts.get("http") or parts.get("https") or ""
                if server and ":" in server:
                    srv, prt_str = server.split(":", 1)
                    prt = int(prt_str)
                    if prt not in (5202, 5200) and _is_tcp_port_open(srv, prt):
                        return f"http://{srv}:{prt}"
        except Exception:
            pass


    return None

_original_mac_proxy_backup = {}

def set_mac_proxy(enabled, host="127.0.0.1", port=5202):
    global _original_socks_state, _original_mac_proxy_backup
    services = get_all_mac_network_services()
    active_service = get_active_mac_service()
    if active_service in services:
        services.remove(active_service)
        services.insert(0, active_service)

    for service in services:
        try:
            if enabled:
                # 备份原有 HTTP / HTTPS 代理配置，防止关闭时误杀用户的 VPN
                if service not in _original_mac_proxy_backup:
                    info = {}
                    try:
                        w_out = subprocess.check_output(["networksetup", "-getwebproxy", service], timeout=2, text=True)
                        if "Enabled: Yes" in w_out:
                            m_s = re.search(r"Server:\s*(\S+)", w_out)
                            m_p = re.search(r"Port:\s*(\d+)", w_out)
                            if m_s and m_p and int(m_p.group(1)) not in (port, 5200):
                                info["web"] = (m_s.group(1), m_p.group(1))
                    except Exception:
                        pass
                    try:
                        s_out = subprocess.check_output(["networksetup", "-getsecurewebproxy", service], timeout=2, text=True)
                        if "Enabled: Yes" in s_out:
                            m_s = re.search(r"Server:\s*(\S+)", s_out)
                            m_p = re.search(r"Port:\s*(\d+)", s_out)
                            if m_s and m_p and int(m_p.group(1)) not in (port, 5200):
                                info["secure"] = (m_s.group(1), m_p.group(1))
                    except Exception:
                        pass
                    _original_mac_proxy_backup[service] = info

                # 检查并临时关闭 PAC 自动代理（防止 PAC 脚本覆盖）
                try:
                    pac_out = subprocess.check_output(["networksetup", "-getautoproxyurl", service], timeout=2, text=True)
                    if "Enabled: Yes" in pac_out:
                        subprocess.run(["networksetup", "-setautoproxystate", service, "off"], capture_output=True)
                except Exception:
                    pass

                # 设置 HTTP / HTTPS 代理至 5202
                subprocess.run(["networksetup", "-setwebproxy", service, host, str(port)], check=True)
                subprocess.run(["networksetup", "-setsecurewebproxy", service, host, str(port)], check=True)
            else:
                # 关闭时：若原本开启了用户的 VPN 代理，则精准恢复，绝不切断用户的科学上网！
                orig = _original_mac_proxy_backup.get(service, {})
                if "web" in orig:
                    subprocess.run(["networksetup", "-setwebproxy", service, orig["web"][0], orig["web"][1]], check=True)
                    subprocess.run(["networksetup", "-setwebproxystate", service, "on"], check=True)
                else:
                    subprocess.run(["networksetup", "-setwebproxystate", service, "off"], check=True)

                if "secure" in orig:
                    subprocess.run(["networksetup", "-setsecurewebproxy", service, orig["secure"][0], orig["secure"][1]], check=True)
                    subprocess.run(["networksetup", "-setsecurewebproxystate", service, "on"], check=True)
                else:
                    subprocess.run(["networksetup", "-setsecurewebproxystate", service, "off"], check=True)
        except Exception as e:
            print(f"Error setting Mac proxy for {service} (enabled={enabled}): {e}")

_original_windows_pac = None
_original_win_proxy_backup = None
_original_win_override_backup = None

def set_windows_proxy(enabled, host="127.0.0.1", port=5202):
    global _original_windows_pac, _original_win_proxy_backup, _original_win_override_backup
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            0,
            winreg.KEY_READ | winreg.KEY_WRITE
        )
        if enabled:
            # 备份用户原有的 ProxyServer 与 ProxyEnable
            try:
                penable, _ = winreg.QueryValueEx(key, "ProxyEnable")
                pserver, _ = winreg.QueryValueEx(key, "ProxyServer")
                if penable and pserver and f":{port}" not in pserver:
                    _original_win_proxy_backup = (penable, pserver)
            except Exception:
                pass

            # 备份用户原有的 ProxyOverride（例外名单）
            try:
                p_override, _ = winreg.QueryValueEx(key, "ProxyOverride")
                if p_override and _original_win_override_backup is None:
                    _original_win_override_backup = p_override
            except Exception:
                pass

            # 备份并临时清理 PAC 脚本，避免第三方代理的 PAC 规则冲突
            try:
                pac_val, _ = winreg.QueryValueEx(key, "AutoConfigURL")
                if pac_val:
                    _original_windows_pac = pac_val
                    winreg.DeleteValue(key, "AutoConfigURL")
            except FileNotFoundError:
                pass
            except Exception:
                pass

            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"{host}:{port}")
            # Ensure local and intranet addresses bypass the proxy to prevent local loops
            # with Flask (127.0.0.1:5200) and WebView2 / internal services.
            override_val = "<local>;localhost;127.*;10.*;172.16.*;172.17.*;172.18.*;172.19.*;172.20.*;172.21.*;172.22.*;172.23.*;172.24.*;172.25.*;172.26.*;172.27.*;172.28.*;172.29.*;172.30.*;172.31.*;192.168.*"
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, override_val)
        else:
            if _original_win_proxy_backup:
                # 优雅还原用户原有的 VPN 代理设置
                penable, pserver = _original_win_proxy_backup
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, penable)
                winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, pserver)
                _original_win_proxy_backup = None
            else:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)

            # 还原用户原有的 ProxyOverride 例外列表
            if _original_win_override_backup:
                try:
                    winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, _original_win_override_backup)
                except Exception:
                    pass
                _original_win_override_backup = None

            if _original_windows_pac:
                try:
                    winreg.SetValueEx(key, "AutoConfigURL", 0, winreg.REG_SZ, _original_windows_pac)
                except Exception:
                    pass
                _original_windows_pac = None
        winreg.CloseKey(key)
        
        import ctypes
        internet_set_option = ctypes.windll.wininet.InternetSetOptionW
        internet_set_option(0, 39, 0, 0) # INTERNET_OPTION_SETTINGS_CHANGED
        internet_set_option(0, 37, 0, 0) # INTERNET_OPTION_REFRESH
    except Exception as e:
        print(f"Error setting Windows proxy state to {enabled}: {e}")

def set_system_proxy(enabled, port=5202):
    if sys.platform == "darwin":
        set_mac_proxy(enabled, port=port)
    elif sys.platform == "win32":
        set_windows_proxy(enabled, port=port)


# ── mitmproxy 拦截插件 (Interception Addon) ──────────────────────
# 用成熟的 mitmproxy 引擎替代手写 HTTP/1.1 解析器:
# HTTP/2、chunked、SSE/长轮询、WebSocket 全部由引擎正确处理,
# 不会再因解析错位或 read-until-EOF 阻塞导致视频号页面疯狂重刷。

