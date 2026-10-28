"""Channels ProxyManager process lifecycle."""
from parse_tools.platforms.channels.mitm_certs import *  # noqa: F401,F403
from parse_tools.platforms.channels.mitm_addon import ChannelsAddon, get_injected_official_js  # noqa: F401

def cleanup_mitmproxy_logging_handlers():
    import logging
    
    def is_mitm_handler(h):
        cls = h.__class__
        if "mitm" in getattr(cls, "__module__", "").lower():
            return True
        if "mitm" in cls.__name__.lower():
            return True
        for base in getattr(cls, "__mro__", []):
            if "mitm" in base.__name__.lower() or "mitm" in getattr(base, "__module__", "").lower():
                return True
        return False

    # 1. Clean root logger
    root = logging.getLogger()
    for h in list(root.handlers):
        if is_mitm_handler(h):
            try:
                root.removeHandler(h)
                h.close()
            except Exception:
                pass
                
    # 2. Clean all other loggers
    for name in list(logging.Logger.manager.loggerDict.keys()):
        logger = logging.getLogger(name)
        for h in list(logger.handlers):
            if is_mitm_handler(h):
                try:
                    logger.removeHandler(h)
                    h.close()
                except Exception:
                    pass


def _set_no_proxy():
    """设置 NO_PROXY=* 使 Python 的 requests/urllib3/curl_cffi 绕过系统代理。

    MITM 代理会通过 networksetup（macOS）/ 注册表（Windows）设置系统级代理，
    浏览器读取系统代理来走 MITM 拦截，但 Python 后端代码不需要走 MITM。
    设置 NO_PROXY=* 后，Python 的 HTTP 库不再自动使用系统代理，
    而用户在应用设置中配置的显式代理（通过 proxies= 参数传递）不受影响。
    """
    global _original_no_proxy
    _original_no_proxy = os.environ.get("NO_PROXY")
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    print("NO_PROXY=* set: Python HTTP clients will bypass system proxy.")


def _restore_no_proxy():
    """还原 MITM 启动前的 NO_PROXY 环境变量。"""
    global _original_no_proxy
    if _original_no_proxy is not None:
        os.environ["NO_PROXY"] = _original_no_proxy
        os.environ["no_proxy"] = _original_no_proxy
    else:
        os.environ.pop("NO_PROXY", None)
        os.environ.pop("no_proxy", None)
    _original_no_proxy = None
    print("NO_PROXY restored to original.")


def get_worker_python() -> str:
    """获取运行 mitmproxy worker 的最佳 Python 解释器。
    在打包模式下返回 sys.executable；
    在源码模式下优先返回项目同级的 venv312 解释器，避免 macOS Homebrew Python
    或外部 Python 启动子进程时因丢失虚拟环境路径导致找不到 mitmproxy 模块。
    """
    if getattr(sys, 'frozen', False):
        return sys.executable
    project_root = Path(__file__).resolve().parent.parent
    if sys.platform == "win32":
        venv_py = project_root / "venv312" / "Scripts" / "python.exe"
    else:
        venv_py = project_root / "venv312" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    if sys.platform == "win32":
        prefix_py = Path(sys.prefix) / "Scripts" / "python.exe"
    else:
        prefix_py = Path(sys.prefix) / "bin" / "python"
    if prefix_py.exists():
        return str(prefix_py)
    return sys.executable


# ── Proxy Service Manager (代理服务单例管理器) ─────────────────────

class ProxyManager:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
        
    def __init__(self):
        self._running = False
        self.process = None
        self.port = 5202
        self.last_error = None
        self._monitor_thread = None

    @property
    def running(self):
        if self._running and self.process and self.process.poll() is None:
            return True
        return False

    @running.setter
    def running(self, val):
        self._running = bool(val)

    def _is_port_listening(self, port: int, timeout: float = 1.0) -> bool:
        import socket
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=timeout):
                return True
        except Exception:
            return False

    def _kill_port_owner(self, port: int):
        """强制清理霸占代理端口的任何遗留孤儿进程（排除当前进程本身）"""
        try:
            curr_pid = os.getpid()
            if sys.platform == "win32":
                flags = 0x08000000  # CREATE_NO_WINDOW
                out = subprocess.check_output(
                    f"netstat -ano | findstr :{port}",
                    shell=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    creationflags=flags
                )
                for line in out.strip().splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 5 and "LISTENING" in parts:
                        pid = parts[-1]
                        if pid.isdigit() and int(pid) != curr_pid:
                            subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True, creationflags=flags)
            else:
                out = subprocess.check_output(["lsof", "-ti", f":{port}"], text=True).strip()
                if out:
                    for pid in out.splitlines():
                        if pid.strip().isdigit() and int(pid.strip()) != curr_pid:
                            try:
                                os.kill(int(pid.strip()), 9)
                            except Exception:
                                pass
        except Exception:
            pass

    def start(self):
        if self.running and self._is_port_listening(self.port):
            return True

        self.last_error = None
        cleanup_mitmproxy_logging_handlers()

        try:
            # 0. 准备证书与目录
            ensure_ca_certificates()
            cert_ok = install_system_cert(CA_CERT_PATH)
            if not cert_ok:
                print("[WARNING] CA 证书可能未被系统信任，MITM 拦截可能失败。"
                      "请检查是否有其他 VPN/安全软件的证书冲突。")

            confdir = prepare_mitm_confdir()

            # 1. 检查端口是否有残留，若有则强制清理孤儿进程
            if self._is_port_listening(self.port):
                print(f"[Proxy] 检测到端口 {self.port} 处于监听状态，正在清理旧实例...")
                self._kill_port_owner(self.port)
                self.stop()
                time.sleep(0.5)

            # 2. 智能探测本机是否运行着 VPN / 科学上网代理客户端
            upstream_proxy = detect_upstream_proxy()
            if upstream_proxy:
                print(f"[Proxy] 🚀 自动探测到本机正在运行的 VPN 代理 ({upstream_proxy})，"
                      f"已启用链式上游转发 (Upstream Chaining)，实现 VPN 与同步助手无缝并存！")

            # 3. 以完全隔离的独立子进程启动 mitmproxy worker
            worker_py = get_worker_python()
            if getattr(sys, 'frozen', False):
                cmd = [
                    worker_py,
                    "--proxy-worker",
                    "--port", str(self.port),
                    "--confdir", str(confdir),
                ]
            else:
                cmd = [
                    worker_py,
                    "-m", "parse_tools.services.proxy_worker",
                    "--port", str(self.port),
                    "--confdir", str(confdir),
                ]
            if upstream_proxy:
                cmd.extend(["--upstream", upstream_proxy])
            
            popen_kwargs = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "text": True,
                "bufsize": 1,
            }
            if sys.platform == "win32":
                popen_kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW: 彻底隐藏子进程黑色控制台窗口

            self.process = subprocess.Popen(
                cmd,
                **popen_kwargs
            )

            # 3. 等待子进程启动就绪握手（最多 6 秒）
            is_ready = False
            start_wait = time.time()
            while time.time() - start_wait < 6.0:
                if self.process.poll() is not None:
                    # 子进程提前退出
                    out_text = self.process.stdout.read() if self.process.stdout else ""
                    raise RuntimeError(f"代理工作进程异常退出: {out_text.strip()}")
                
                # 读取一行输出验证 WORKER_READY
                import select
                if sys.platform != "win32":
                    rlist, _, _ = select.select([self.process.stdout], [], [], 0.2)
                    if rlist:
                        line = self.process.stdout.readline()
                        if "WORKER_READY" in line:
                            is_ready = True
                            break
                else:
                    if self._is_port_listening(self.port, timeout=0.2):
                        is_ready = True
                        break
                    time.sleep(0.2)

            if not is_ready:
                is_ready = self._is_port_listening(self.port, timeout=1.0)

            if not is_ready:
                self.stop()
                raise RuntimeError("mitmproxy 代理助手启动握手超时，未能成功就绪。")

            self._running = True

            # 4. 启动后台监控线程：收集日志并在子进程意外退出时自动回滚系统代理
            def _monitor_worker():
                try:
                    while self.process and self.process.poll() is None:
                        line = self.process.stdout.readline()
                        if not line:
                            break
                        line_s = line.strip()
                        if line_s and not line_s.startswith("WORKER_READY"):
                            print(f"[ProxyWorker] {line_s}", flush=True)
                except Exception:
                    pass
                if self._running:
                    print("[ProxyWorker] 代理进程退出，正在自动还原系统代理...", flush=True)
                    self._running = False
                    try:
                        set_system_proxy(False, port=self.port)
                    except Exception:
                        pass

            self._monitor_thread = threading.Thread(target=_monitor_worker, daemon=True)
            self._monitor_thread.start()

            # 5. 设置 NO_PROXY=* 使 Python 后端代码绕过系统代理（仅浏览器需走 MITM）
            _set_no_proxy()

            # 6. 开启系统代理（浏览器/微信客户端会走此代理）
            set_system_proxy(True, port=self.port)
            if not getattr(self, "_atexit_registered", False):
                import atexit
                atexit.register(self.stop)
                self._atexit_registered = True
            print(f"Channels MITM proxy started on 127.0.0.1:{self.port} and system proxy enabled.")
            return True
        except Exception as ex:
            self._running = False
            self.last_error = str(ex)
            # 兜底清理，确保系统网络立即可用
            self.stop()
            raise ex

    def stop(self):
        # 1. 首先无论如何优先还原系统代理，保障用户系统网络通畅
        try:
            set_system_proxy(False, port=self.port)
        except Exception as e:
            print(f"Error restoring system proxy: {e}")

        self._running = False

        # 2. 干净终结子进程，操作系统内核会在微秒级回收所有绑定的 socket
        if self.process:
            try:
                if self.process.poll() is None:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=1.0)
            except Exception as e:
                print(f"Error terminating proxy worker process: {e}")
            finally:
                try:
                    if self.process.stdout:
                        self.process.stdout.close()
                except Exception:
                    pass
                self.process = None

        cleanup_mitmproxy_logging_handlers()

        # 3. 还原 NO_PROXY 环境变量
        _restore_no_proxy()

        print("Channels MITM proxy stopped and system proxy disabled.")
        return True
