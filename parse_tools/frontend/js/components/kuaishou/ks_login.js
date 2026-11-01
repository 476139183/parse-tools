const KsLoginComponent = {
    settings: {},

    render() {
        return `
            <div class="page-header">
                <h2 class="page-title">快手登录与凭证管理</h2>
                <p style="color: var(--text-secondary); margin-top: 8px;">单作品解析多半免登录。主页 / 点赞 / 收藏需要 <strong>www.kuaishou.com 主站 Cookie</strong>（不要用创作者平台）。</p>
            </div>

            <div class="card" style="max-width: 640px; margin: 24px auto;">
                <div class="card-body">
                    <div style="background: rgba(15, 118, 110, 0.08); border: 1px solid rgba(15, 118, 110, 0.25); border-radius: 8px; padding: 14px 16px; margin-bottom: 18px; text-align: left; font-size: 0.88rem; color: var(--text-secondary); line-height: 1.65;">
                        <strong style="color: var(--teal, #0f766e);">2026 更稳的做法（业界通用）</strong>
                        <ul style="margin: 6px 0 0 16px; padding: 0;">
                            <li>用你<strong>日常 Chrome</strong>登录 <code>www.kuaishou.com/new-reco</code>，从 Network 复制请求头 Cookie 粘贴进来。</li>
                            <li>必须含 <code>kuaishou.server.webday7_st</code>（或 <code>web_st</code>）。创作者平台 <code>cp.kuaishou.com</code> 的 Cookie <strong>不能</strong>当主站登录。</li>
                            <li>不要用 <code>document.cookie</code>（缺 HttpOnly）；不要反复扫码 / 反复换 passToken，容易「账号异常」踢会话。</li>
                        </ul>
                    </div>

                    <div id="ks-login-status" style="margin: 8px 0 16px; font-size: 1.05rem; color: var(--text-primary); text-align: center;">
                        检查登录状态…
                    </div>
                </div>
            </div>

            <!-- 主路径：日常浏览器粘贴 -->
            <div class="card" style="max-width: 640px; margin: 0 auto 24px;">
                <div class="card-header">
                    <h3 class="card-title">推荐：从日常 Chrome 粘贴主站 Cookie</h3>
                </div>
                <div class="card-body" style="padding: 0 var(--spacing-md) var(--spacing-md); text-align: left;">
                    <div style="display: flex; gap: 10px; flex-wrap: wrap; margin: 12px 0 14px;">
                        <button type="button" class="btn btn-primary" style="padding: 10px 18px; border-radius: 8px;" onclick="KsLoginComponent.openKuaishouSite()">
                            ① 打开快手主站
                        </button>
                        <button type="button" class="btn btn-secondary" style="padding: 10px 18px; border-radius: 8px;" onclick="KsLoginComponent.showCookieGuide()">
                            怎么复制 Cookie？
                        </button>
                    </div>

                    <div style="background: var(--bg-input, #f5f7fa); border: 1px solid var(--border-color); border-radius: 10px; padding: 14px 16px; font-size: 0.88rem; color: var(--text-secondary); line-height: 1.75;">
                        <div style="font-weight: 600; color: var(--text-primary); margin-bottom: 6px;">照着做（约 1 分钟）</div>
                        <ol style="margin: 0 0 0 18px; padding: 0;">
                            <li>点上面「打开快手主站」，用<strong>已登录</strong>的 Chrome（右上角能看到自己头像）。</li>
                            <li>键盘按 <kbd style="padding:2px 6px;border:1px solid #ccc;border-radius:4px;background:#fff;">F12</kbd>（Mac 可用 <kbd style="padding:2px 6px;border:1px solid #ccc;border-radius:4px;background:#fff;">⌥⌘I</kbd>）打开开发者工具。</li>
                            <li>点顶部的 <strong>Network</strong>（网络）→ 再按 <kbd style="padding:2px 6px;border:1px solid #ccc;border-radius:4px;background:#fff;">⌘R</kbd> 刷新页面。</li>
                            <li>左侧列表里点一个名字像 <code>graphql</code> 或 <code>profile</code> 的请求（域名是 www.kuaishou.com）。</li>
                            <li>右侧找 <strong>Headers / 标头</strong> → 往下翻到 <strong>Request Headers / 请求标头</strong>。</li>
                            <li>找到 <code>Cookie:</code> 那一行，把<strong>后面那一整串</strong>复制下来（很长，正常）。</li>
                            <li>粘贴到下方输入框，点「保存并校验」。</li>
                        </ol>
                        <p style="margin: 10px 0 0; font-size: 0.82rem; color: var(--text-muted);">
                            正确内容里一般能搜到 <code>webday7_st</code> 或 <code>web_st</code>。不要复制 Response 里的 Set-Cookie，也不要只复制一两项。
                        </p>
                    </div>

                    <div class="form-group" style="margin-top: 16px;">
                        <label class="form-label" style="color: var(--text-primary); font-weight: 500;">粘贴 Cookie 到这里</label>
                        <textarea id="ks-cookie-textarea" class="form-input" style="height: 120px; font-family: monospace; font-size: 0.85rem; resize: vertical; border-radius: 8px;" placeholder="例如：kpf=PC_WEB; clientid=3; did=web_xxx; userId=xxx; kuaishou.server.webday7_st=xxx; …"></textarea>
                    </div>
                    <div style="display: flex; gap: var(--spacing-sm); justify-content: flex-end; margin-top: var(--spacing-md);">
                        <button class="btn btn-secondary" onclick="KsLoginComponent.clearCookie()" style="padding: 8px 16px; border-radius: 8px;">清空</button>
                        <button class="btn btn-primary" onclick="KsLoginComponent.saveCookie()" style="padding: 8px 20px; border-radius: 8px;">保存并校验</button>
                    </div>
                </div>
            </div>

            <!-- 备选：独立浏览器自动截获（快手风控下不如抖音/元宝稳） -->
            <div class="card" style="max-width: 640px; margin: 0 auto 24px;">
                <div class="card-header">
                    <h3 class="card-title">备选：打开独立浏览器自动获取</h3>
                </div>
                <div class="card-body" style="padding: 0 var(--spacing-md) var(--spacing-md); text-align: left;">
                    <p style="margin: 12px 0; font-size: 0.86rem; color: var(--text-muted); line-height: 1.6;">
                        快手对「自动化浏览器 + 二次注入 Cookie」风控更严，容易秒变「账号异常」。不如上面粘贴稳；仅当你不想翻 Network 时再试。
                    </p>
                    <div style="display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-bottom: 8px;">
                        <button id="btn-ks-capture-cookie" class="btn btn-secondary" style="padding: 10px 20px; border-radius: 8px;" onclick="KsLoginComponent.startCaptureCookie()">
                            打开浏览器自动获取
                        </button>
                        <button id="btn-ks-capture-cancel" class="btn btn-secondary" style="padding: 10px 16px; border-radius: 8px; display: none;" onclick="KsLoginComponent.cancelCaptureCookie()">
                            取消
                        </button>
                    </div>
                    <div id="ks-capture-msg" style="font-size: 0.85rem; color: var(--text-muted); min-height: 20px;"></div>
                </div>
            </div>

            <!-- 末选：扫码（会踢手机） -->
            <div class="card" style="max-width: 640px; margin: 0 auto 24px; text-align: center;">
                <div class="card-header" style="text-align: left;">
                    <h3 class="card-title">末选：扫码登录（可能挤下线手机）</h3>
                </div>
                <div class="card-body">
                    <p style="margin: 0 0 14px; font-size: 0.86rem; color: var(--text-muted); text-align: left; line-height: 1.55;">
                        会刷新 passToken，主号慎用。仅建议小号。
                    </p>
                    <button id="btn-ks-start-login" class="btn btn-secondary" style="padding: 10px 28px; border-radius: 8px;">
                        我知道会踢手机，仍要扫码
                    </button>
                </div>
            </div>

            <div id="ks-qr-modal" style="display: none; position: fixed; inset: 0; background: rgba(0, 0, 0, 0.6); z-index: 9999; align-items: center; justify-content: center; backdrop-filter: blur(4px); padding: 20px;">
                <div style="background: var(--bg-card, #ffffff); border: 1px solid var(--border-color, #e0e0e0); border-radius: 16px; width: 100%; max-width: 380px; padding: 24px; text-align: center; box-shadow: 0 20px 45px rgba(0,0,0,0.3); position: relative;">
                    <button id="btn-ks-modal-close" style="position: absolute; top: 14px; right: 14px; background: none; border: none; font-size: 1.25rem; color: var(--text-muted, #999); cursor: pointer; padding: 4px 8px; border-radius: 6px; line-height: 1;" title="关闭">✕</button>
                    <h3 style="margin: 0 0 6px; font-size: 1.15rem; color: var(--text-primary); font-weight: 700;">快手扫码登录</h3>
                    <p style="margin: 0 0 16px; font-size: 0.84rem; color: #dc2626;">确认登录后，手机 App 可能会被挤下线</p>
                    <div id="ks-qr-box" style="min-height: 220px; display: flex; align-items: center; justify-content: center; background: #fff; border-radius: 12px; padding: 12px;">
                        <div class="spinner"></div>
                    </div>
                    <div id="ks-qr-msg" style="margin-top: 14px; font-size: 0.85rem; color: var(--text-secondary); min-height: 22px;">正在加载二维码...</div>
                    <div style="margin-top: 18px; display: flex; gap: 10px; justify-content: center;">
                        <button class="btn btn-secondary btn-sm" id="btn-ks-cancel-login" style="padding: 6px 18px;">取消</button>
                    </div>
                </div>
            </div>
        `;
    },

    init() {
        this.statusTimer = null;
        this.captureTimer = null;
        this._loginFlowActive = false;
        this.statusText = document.getElementById('ks-login-status');
        this.startBtn = document.getElementById('btn-ks-start-login');
        this.cancelBtn = document.getElementById('btn-ks-cancel-login');
        this.modal = document.getElementById('ks-qr-modal');
        this.qrBox = document.getElementById('ks-qr-box');
        this.qrMsg = document.getElementById('ks-qr-msg');
        this.closeBtn = document.getElementById('btn-ks-modal-close');

        if (this.startBtn) this.startBtn.addEventListener('click', () => this.startLogin());
        if (this.cancelBtn) this.cancelBtn.addEventListener('click', () => this.cancelLogin());
        if (this.closeBtn) this.closeBtn.addEventListener('click', () => this.cancelLogin());

        this.checkStatus();
        this.loadSettings();
    },

    _setCaptureUi(running, msg) {
        const btn = document.getElementById('btn-ks-capture-cookie');
        const cancel = document.getElementById('btn-ks-capture-cancel');
        const tip = document.getElementById('ks-capture-msg');
        if (btn) {
            btn.disabled = !!running;
            btn.textContent = running ? '获取中…' : '打开浏览器自动获取';
        }
        if (cancel) cancel.style.display = running ? 'inline-flex' : 'none';
        if (tip) tip.textContent = msg || '';
    },

    async startCaptureCookie() {
        try {
            this._setCaptureUi(true, '正在唤起本地浏览器…');
            const res = await API.kuaishou.auth.captureCookie();
            this._setCaptureUi(true, res.message || '请在弹出窗口中登录快手网页');
            if (this.captureTimer) clearInterval(this.captureTimer);
            this.captureTimer = setInterval(() => this.pollCaptureStatus(), 1500);
            this.pollCaptureStatus();
        } catch (err) {
            this._setCaptureUi(false, '');
            Toast.show(err.message || '启动失败', 'error');
        }
    },

    async cancelCaptureCookie() {
        try {
            await API.kuaishou.auth.captureCookieCancel().catch(() => null);
            this._setCaptureUi(false, '已取消');
            if (this.captureTimer) {
                clearInterval(this.captureTimer);
                this.captureTimer = null;
            }
        } catch (err) {
            Toast.show(err.message || '取消失败', 'error');
        }
    },

    async pollCaptureStatus() {
        try {
            const st = await API.kuaishou.auth.captureCookieStatus();
            if (!st) return;
            if (st.status === 'running') {
                this._setCaptureUi(true, st.message || '等待登录…');
                return;
            }
            if (this.captureTimer) {
                clearInterval(this.captureTimer);
                this.captureTimer = null;
            }
            if (st.status === 'success') {
                this._setCaptureUi(false, st.message || '获取成功');
                const textarea = document.getElementById('ks-cookie-textarea');
                if (textarea && st.cookie) textarea.value = st.cookie;
                Toast.show(st.message || 'Cookie 已自动获取并保存', 'success');
                this.checkStatus();
                this.loadSettings();
            } else if (st.status === 'cancelled') {
                this._setCaptureUi(false, '已取消');
            } else if (st.status === 'failed') {
                this._setCaptureUi(false, st.error || '获取失败');
                Toast.show(st.error || '获取失败', 'error');
            } else {
                this._setCaptureUi(false, st.message || '');
            }
        } catch (err) {
            console.error('poll ks capture status', err);
        }
    },

    _showModal() {
        if (!this.modal) return;
        this.modal.style.display = 'flex';
    },

    _hideModal() {
        if (!this.modal) return;
        this.modal.style.display = 'none';
    },

    _renderQr(qrcode) {
        if (!this.qrBox || !qrcode) return;
        this.qrBox.innerHTML = `<img src="${qrcode}" alt="快手登录二维码" style="width: 220px; height: 220px; object-fit: contain; border-radius: 8px;" />`;
    },

    openKuaishouSite() {
        window.open('https://www.kuaishou.com/new-reco', '_blank', 'noopener');
        Toast.show('已打开快手主站：登录后按 F12 → Network 复制 Cookie', 'info');
    },

    showCookieGuide() {
        Modal.open({
            title: '如何复制快手 Cookie',
            content: `
                <div style="text-align:left;font-size:0.92rem;line-height:1.7;color:var(--text-secondary);">
                    <p style="margin:0 0 10px;"><strong style="color:var(--text-primary);">目标：</strong>从已登录的 Chrome 里，复制发给 www.kuaishou.com 的完整 Cookie 文本。</p>
                    <ol style="margin:0 0 12px 18px;padding:0;">
                        <li>打开 <code>https://www.kuaishou.com/new-reco</code>，确认右上角是你的头像（已登录）。</li>
                        <li>按 <strong>F12</strong>（Mac：Option + Command + I）。</li>
                        <li>点 <strong>Network / 网络</strong>。</li>
                        <li>按 <strong>Command + R</strong> 刷新；左侧会出现很多请求。</li>
                        <li>点选一个请求名含 <code>graphql</code> 的（或任意 www.kuaishou.com 的 XHR）。</li>
                        <li>右侧 <strong>Headers</strong> → 找到 <strong>Request Headers</strong> 里的 <code>cookie:</code>。</li>
                        <li>双击 Cookie 值（或右键 Copy value），粘贴回本页输入框。</li>
                    </ol>
                    <p style="margin:0;padding:10px 12px;background:rgba(220,38,38,0.06);border-radius:8px;font-size:0.86rem;">
                        <strong>常见踩坑：</strong>创作者平台 cp.kuaishou.com 的 Cookie 无效；Console 里敲 document.cookie 也不完整；Cookie 很长是正常的。
                    </p>
                </div>
            `,
        });
    },

    async loadSettings() {
        try {
            const data = await API.settings.get();
            this.settings = data;
            const textarea = document.getElementById('ks-cookie-textarea');
            if (textarea) textarea.value = data.kuaishou_cookie || '';
        } catch (err) {
            console.error('Failed to load settings:', err);
        }
    },

    async saveCookie() {
        const textarea = document.getElementById('ks-cookie-textarea');
        let cookieVal = textarea ? textarea.value.trim() : '';
        // 允许误粘贴整段 "Cookie: xxx"
        cookieVal = cookieVal.replace(/^cookie\s*:\s*/i, '').trim();
        if (!cookieVal) {
            Toast.show('请先粘贴 Cookie', 'warning');
            return;
        }
        if (/kuaishou\.web\.cp\.api_st=/.test(cookieVal) && !/kuaishou\.server\.web(?:day7)?_st=/.test(cookieVal)) {
            Toast.show('这是创作者平台 Cookie，不能用于主站。请从 www.kuaishou.com 复制。', 'error');
            return;
        }
        if (!/kuaishou\.server\.web(?:day7)?_st=/.test(cookieVal)) {
            Toast.show('缺少 webday7_st / web_st，请从已登录的主站 Network 请求头复制完整 Cookie', 'error');
            return;
        }
        try {
            if (textarea) textarea.value = cookieVal;
            const settings = await API.settings.get();
            settings.kuaishou_cookie = cookieVal;
            await API.settings.save(settings);
            this.settings = settings;
            // 保存后立刻走服务端校验，避免「有 Cookie 却未登录」
            const st = await API.kuaishou.auth.status();
            if (st.status === 'success') {
                Toast.show(st.message || 'Cookie 有效，已保存', 'success');
            } else {
                Toast.show(st.message || '已保存，但 www 校验未通过，请换一份有效 Cookie', 'warning');
            }
            this.checkStatus();
        } catch (err) {
            Toast.show('保存失败: ' + err.message, 'error');
        }
    },

    async clearCookie() {
        Modal.confirm('清除 Cookie 凭证', '确定要清除已保存的快手 Cookie 凭证吗？', async () => {
            try {
                const settings = await API.settings.get();
                settings.kuaishou_cookie = '';
                await API.settings.save(settings);
                Toast.show('快手 Cookie 凭证已清空', 'success');
                this.settings = settings;
                const textarea = document.getElementById('ks-cookie-textarea');
                if (textarea) textarea.value = '';
                this.checkStatus();
            } catch (err) {
                Toast.show('操作失败: ' + err.message, 'error');
            }
        });
    },

    async startLogin() {
        Modal.confirm(
            '确认扫码？可能挤下线手机',
            '快手网页扫码会刷新通行证，手机 App 很可能被挤下线。<br><br>更推荐上方「粘贴 Cookie」。若仍要扫码，请用小号。',
            () => this._doStartQrLogin()
        );
    },

    async _doStartQrLogin() {
        try {
            this.startBtn.disabled = true;
            this._showModal();
            if (this.qrBox) this.qrBox.innerHTML = '<div class="spinner"></div>';
            if (this.qrMsg) {
                this.qrMsg.textContent = '正在获取二维码...';
                this.qrMsg.style.color = 'var(--text-secondary)';
            }

            this._loginFlowActive = true;
            const res = await API.kuaishou.auth.start();
            if (res.qrcode) this._renderQr(res.qrcode);
            if (this.qrMsg) this.qrMsg.textContent = res.message || '请使用快手 App 扫码（可能踢手机）';

            if (this.statusTimer) clearInterval(this.statusTimer);
            this.statusTimer = setInterval(() => this.checkStatus(), 1500);
            this.checkStatus();
        } catch (err) {
            this._loginFlowActive = false;
            Toast.show(err.message, 'error');
            this.startBtn.disabled = false;
            if (this.qrMsg) {
                this.qrMsg.textContent = err.message || '启动失败，请重试';
                this.qrMsg.style.color = 'var(--error)';
            }
        }
    },

    async cancelLogin() {
        try {
            if (this.cancelBtn) this.cancelBtn.disabled = true;
            this._loginFlowActive = false;
            await API.kuaishou.auth.cancel().catch(() => null);
            if (this.statusTimer) {
                clearInterval(this.statusTimer);
                this.statusTimer = null;
            }
            this._hideModal();
            this.startBtn.disabled = false;
            if (this.cancelBtn) this.cancelBtn.disabled = false;
            this.statusText.textContent = '登录已取消';
            this.statusText.style.color = 'var(--text-secondary)';
        } catch (err) {
            Toast.show(err.message, 'error');
            if (this.cancelBtn) this.cancelBtn.disabled = false;
        }
    },

    async checkStatus() {
        try {
            const data = await API.kuaishou.auth.status();

            if (data.status === 'scanning' || data.status === 'scanned') {
                this.startBtn.disabled = true;
                this._showModal();
                if (data.qrcode) this._renderQr(data.qrcode);
                if (this.qrMsg) {
                    this.qrMsg.textContent = data.message || (data.status === 'scanned' ? '扫码成功，正在登录...' : '请使用快手 App 扫码');
                    this.qrMsg.style.color = data.status === 'scanned' ? 'var(--success)' : 'var(--primary)';
                }
                this.statusText.textContent = data.message || '扫码登录进行中...';
                this.statusText.style.color = 'var(--primary)';
            } else if (data.status === 'success') {
                const fromFlow = this._loginFlowActive;
                this._loginFlowActive = false;
                this._hideModal();
                this.statusText.innerHTML = `<p style="color: var(--success); font-weight: 600; font-size: 1.1rem;">✅ ${(data.message || '快手登录有效').replace(/[<>&]/g, '')}</p>`;
                this.startBtn.disabled = false;
                this.startBtn.textContent = '重新扫码登录';

                // 仅扫码/自动获取成功时回填；日常状态轮询不要覆盖用户正在粘贴的内容
                if (fromFlow && data.cookie) {
                    const textarea = document.getElementById('ks-cookie-textarea');
                    if (textarea) textarea.value = data.cookie;
                }

                if (this.statusTimer) {
                    clearInterval(this.statusTimer);
                    this.statusTimer = null;
                }
                if (fromFlow) Toast.show(data.message || '登录成功', 'success');
            } else if (data.status === 'expired') {
                this._loginFlowActive = false;
                if (this.qrMsg) {
                    this.qrMsg.textContent = data.message || '二维码已过期';
                    this.qrMsg.style.color = '#ff9800';
                }
                this.statusText.innerHTML = `<div style="background: rgba(255,152,0,0.12); border: 1px solid rgba(255,152,0,0.4); border-radius: 8px; padding: 16px; text-align: center;">
                    <p style="color: #ff9800; font-weight: 600; font-size: 1.15rem; margin: 0 0 6px 0;">⚠️ ${(data.message || '登录已失效').replace(/[<>&]/g, '')}</p>
                    <p style="color: var(--text-secondary); margin: 0; font-size: 0.95rem;">请重新从日常 Chrome 粘贴 Cookie（不要点「保存」覆盖成旧内容）</p>
                </div>`;
                this.startBtn.disabled = false;
                this.startBtn.textContent = '重新扫码登录';
                if (this.statusTimer) {
                    clearInterval(this.statusTimer);
                    this.statusTimer = null;
                }
            } else if (data.status === 'error') {
                this._loginFlowActive = false;
                if (this.qrMsg) {
                    this.qrMsg.textContent = data.message || '登录失败';
                    this.qrMsg.style.color = 'var(--error)';
                }
                this.statusText.textContent = `❌ ${data.message}`;
                this.statusText.style.color = 'var(--error)';
                this.startBtn.disabled = false;
                if (this.statusTimer) {
                    clearInterval(this.statusTimer);
                    this.statusTimer = null;
                }
            } else if (data.status === 'cancelled') {
                this._loginFlowActive = false;
                this._hideModal();
                this.statusText.textContent = '登录已取消';
                this.statusText.style.color = 'var(--text-secondary)';
                this.startBtn.disabled = false;
                if (this.statusTimer) {
                    clearInterval(this.statusTimer);
                    this.statusTimer = null;
                }
            } else {
                this.startBtn.disabled = false;
            }
        } catch (err) {
            console.error('Check ks auth status error:', err);
        }
    },

    destroy() {
        if (this.statusTimer) {
            clearInterval(this.statusTimer);
            this.statusTimer = null;
        }
        if (this.captureTimer) {
            clearInterval(this.captureTimer);
            this.captureTimer = null;
        }
    }
};
