const AlipayParsePage = {
    currentItem: null,
    pollTimer: null,
    lastSavedPath: '',

    render() {
        return `
            <div class="page-header">
                <h2 class="page-title">解析支付宝</h2>
                <p class="page-description">粘贴生活号+ 分享短链，解析图文或视频后一键下载（无需 Cookie）</p>
            </div>

            <div class="card" style="margin-bottom: var(--spacing-lg);">
                <div class="form-group" style="margin-bottom: var(--spacing-md);">
                    <label class="form-label" style="font-weight: 600;">分享链接</label>
                    <div style="display: flex; gap: var(--spacing-md);">
                        <input type="text" id="alipay-url-input" class="form-input"
                               placeholder="https://ur.lepudding.com/... 或 ur.alipay.com / 含 contentId 的分享页"
                               style="flex: 1;" onkeydown="if(event.key==='Enter') AlipayParsePage.parseUrl()">
                        <button class="btn btn-primary" onclick="AlipayParsePage.parseUrl()" id="alipay-parse-btn" style="min-width: 110px;">
                            解析
                        </button>
                    </div>
                </div>
            </div>

            <div id="alipay-preview-card" style="display: none; padding: 20px; background: var(--bg-card); border-radius: var(--radius-md); margin-bottom: var(--spacing-lg); border: 1px solid var(--border-color);">
                <div style="display: flex; gap: 20px; align-items: flex-start; flex-wrap: wrap;">
                    <div style="width: 140px; height: 140px; border-radius: 8px; overflow: hidden; background: var(--bg-input); flex-shrink: 0;">
                        <img id="alipay-preview-cover" src="" style="width:100%;height:100%;object-fit:cover;" alt="" />
                    </div>
                    <div style="flex: 1; min-width: 200px;">
                        <div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;">
                            <strong id="alipay-preview-author"></strong>
                            <span id="alipay-preview-badge" style="font-size:0.75rem;padding:2px 8px;border-radius:4px;background:rgba(20,184,166,0.15);color:#0f766e;"></span>
                        </div>
                        <div id="alipay-preview-title" style="font-size:0.95rem;line-height:1.5;color:var(--text-primary);margin-bottom:12px;max-height:4.5em;overflow:auto;"></div>
                        <div style="display:flex; gap:10px; flex-wrap:wrap;">
                            <button class="btn btn-primary" onclick="AlipayParsePage.startDownload()" id="alipay-download-btn">下载</button>
                            <button class="btn btn-secondary btn-sm" onclick="AlipayParsePage.clearPreview()">清空</button>
                        </div>
                    </div>
                </div>
            </div>

            <div class="card" id="alipay-download-status" style="display: none;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--spacing-md);">
                    <h3 style="margin:0;font-size:1.05rem;">下载进度</h3>
                    <button class="btn btn-secondary btn-sm" onclick="AlipayParsePage.cancelDownload()">取消</button>
                </div>
                <div style="height:8px;background:var(--bg-input);border-radius:4px;overflow:hidden;margin-bottom:8px;">
                    <div id="alipay-progress-bar" style="width:0%;height:100%;background:var(--gradient-primary);transition:width 0.3s;"></div>
                </div>
                <div id="alipay-progress-text" style="font-size:0.85rem;color:var(--text-muted);margin-bottom:8px;">0%</div>
                <div id="alipay-log-container" style="background:var(--bg-body);border-radius:var(--radius-sm);padding:var(--spacing-sm);height:140px;overflow-y:auto;font-family:monospace;font-size:0.8rem;color:var(--text-muted);"></div>
                <div id="alipay-done-actions" style="display:none;margin-top:12px;">
                    <button class="btn btn-secondary btn-sm" onclick="AlipayParsePage.openFolder()">打开目录</button>
                    <button class="btn btn-primary btn-sm" onclick="AlipayParsePage.openFile()" style="margin-left:8px;">打开结果</button>
                </div>
            </div>
        `;
    },

    init() {
        const quick = sessionStorage.getItem('parse_tools_quick_url');
        if (quick && /ur\.lepudding\.com|ur\.alipay\.com|render\.alipay\.com|contentId=/i.test(quick)) {
            const input = document.getElementById('alipay-url-input');
            if (input) input.value = quick;
            sessionStorage.removeItem('parse_tools_quick_url');
        }
    },

    onShow() {
        this.init();
    },

    destroy() {
        if (this.pollTimer) {
            clearInterval(this.pollTimer);
            this.pollTimer = null;
        }
    },

    _esc(s) {
        const d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    },

    async parseUrl() {
        const input = document.getElementById('alipay-url-input');
        const btn = document.getElementById('alipay-parse-btn');
        const url = (input && input.value || '').trim();
        if (!url) {
            Toast.warning('请粘贴支付宝分享链接');
            return;
        }
        if (btn) {
            btn.disabled = true;
            btn.textContent = '解析中…';
        }
        try {
            const res = await API.alipay.parse(url);
            this.currentItem = res;
            const card = document.getElementById('alipay-preview-card');
            if (card) card.style.display = 'block';
            const cover = document.getElementById('alipay-preview-cover');
            if (cover) cover.src = res.cover || '';
            const author = document.getElementById('alipay-preview-author');
            if (author) author.textContent = res.author || '未知';
            const title = document.getElementById('alipay-preview-title');
            if (title) title.textContent = res.text || res.title || '';
            const badge = document.getElementById('alipay-preview-badge');
            if (badge) {
                if (res.type === 'video') badge.textContent = '视频';
                else if (res.type === 'image') badge.textContent = `图文 · ${(res.images || []).length} 张`;
                else badge.textContent = '纯文本';
            }
            Toast.success('解析成功');
        } catch (e) {
            this.currentItem = null;
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.textContent = '解析';
            }
        }
    },

    clearPreview() {
        this.currentItem = null;
        const card = document.getElementById('alipay-preview-card');
        if (card) card.style.display = 'none';
    },

    async startDownload() {
        if (!this.currentItem) {
            Toast.warning('请先解析链接');
            return;
        }
        try {
            await API.alipay.download({ item: this.currentItem });
            const status = document.getElementById('alipay-download-status');
            if (status) status.style.display = 'block';
            const done = document.getElementById('alipay-done-actions');
            if (done) done.style.display = 'none';
            this.startPoll();
        } catch (e) { /* handled */ }
    },

    startPoll() {
        if (this.pollTimer) clearInterval(this.pollTimer);
        this.pollTimer = setInterval(() => this.pollProgress(), 800);
        this.pollProgress();
    },

    async pollProgress() {
        try {
            const data = await API.alipay.progress();
            const bar = document.getElementById('alipay-progress-bar');
            const text = document.getElementById('alipay-progress-text');
            const logEl = document.getElementById('alipay-log-container');
            const pct = data.current_percent || 0;
            if (bar) bar.style.width = `${pct}%`;
            if (text) text.textContent = `${data.status || ''} · ${pct}% · ${data.current_title || ''}`;
            if (logEl && Array.isArray(data.logs)) {
                logEl.innerHTML = data.logs.map((l) => this._esc(l)).join('<br>');
                logEl.scrollTop = logEl.scrollHeight;
            }
            if (data.status === 'completed' || data.status === 'failed' || data.status === 'cancelled') {
                clearInterval(this.pollTimer);
                this.pollTimer = null;
                if (data.status === 'completed') {
                    this.lastSavedPath = data.saved_path || '';
                    const done = document.getElementById('alipay-done-actions');
                    if (done) done.style.display = 'block';
                    Toast.success('下载完成');
                } else if (data.status === 'failed') {
                    Toast.error('下载失败');
                }
            }
        } catch (e) { /* ignore poll errors */ }
    },

    async cancelDownload() {
        try {
            await API.alipay.cancel();
        } catch (e) { /* */ }
    },

    async openFolder() {
        try { await API.alipay.openFolder(); } catch (e) { /* */ }
    },

    async openFile() {
        if (!this.lastSavedPath) return;
        try { await API.alipay.openFile(this.lastSavedPath); } catch (e) { /* */ }
    },
};
