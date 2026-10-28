const AlipayHistoryPage = {
    items: [],

    render() {
        return `
            <div class="page-header">
                <h2 class="page-title">支付宝下载历史</h2>
                <p class="page-description">查看已下载的生活号+ 图文与视频</p>
            </div>
            <div style="display:flex;justify-content:flex-end;gap:8px;margin-bottom:var(--spacing-md);">
                <button class="btn btn-secondary btn-sm" onclick="AlipayHistoryPage.openFolder()">打开下载目录</button>
                <button class="btn btn-secondary btn-sm" onclick="AlipayHistoryPage.clear()">清空历史</button>
            </div>
            <div id="alipay-history-list" class="card">
                <div class="card-body" style="color:var(--text-muted);">加载中…</div>
            </div>
        `;
    },

    async init() {
        await this.load();
    },

    async onShow() {
        await this.load();
    },

    _esc(s) {
        const d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    },

    async load() {
        const box = document.getElementById('alipay-history-list');
        try {
            this.items = await API.alipay.getHistory() || [];
            if (!box) return;
            if (!this.items.length) {
                box.innerHTML = '<div class="card-body" style="color:var(--text-muted);">暂无下载记录</div>';
                return;
            }
            box.innerHTML = this.items.map((it, idx) => `
                <div style="padding:14px 16px;border-bottom:1px solid var(--border-color);display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap;">
                    <div style="min-width:0;flex:1;">
                        <div style="font-weight:600;color:var(--text-primary);">${this._esc(it.title)}</div>
                        <div style="font-size:0.8rem;color:var(--text-muted);margin-top:4px;">
                            ${this._esc(it.type)} · ${this._esc(it.size)} · ${this._esc(it.time)}
                        </div>
                    </div>
                    <button class="btn btn-secondary btn-sm" onclick="AlipayHistoryPage.openItem(${idx})">打开</button>
                </div>
            `).join('');
        } catch (e) {
            if (box) box.innerHTML = '<div class="card-body" style="color:var(--badge-danger-color);">加载失败</div>';
        }
    },

    async openItem(idx) {
        const it = this.items[idx];
        if (!it || !it.path) return;
        try { await API.alipay.openFile(it.path); } catch (e) { /* */ }
    },

    async openFolder() {
        try { await API.alipay.openFolder(); } catch (e) { /* */ }
    },

    async clear() {
        Modal.confirm('清空历史', '仅清空列表，不会删除本地文件。确定？', async () => {
            try {
                await API.alipay.clearHistory();
                Toast.success('已清空');
                await this.load();
            } catch (e) { /* */ }
        });
    },
};
