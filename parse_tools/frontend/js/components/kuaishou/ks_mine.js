const KsMinePage = {
    tab: 'liked', // liked | collect
    items: [],
    pcursor: '',
    hasMore: false,
    loading: false,
    loadingMore: false,
    isSelectMode: false,

    render() {
        return `
            <div class="page-header">
                <h2 class="page-title">我的点赞 / 收藏</h2>
                <p class="page-description">展示当前登录账号在快手网页端可见的「点赞」「收藏」列表，支持多选下载</p>
            </div>

            <div class="card" style="margin-bottom: var(--spacing-lg);">
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
                    <div style="display: flex; gap: 8px;">
                        <button class="btn btn-secondary" id="ks-mine-tab-liked" onclick="KsMinePage.switchTab('liked')">点赞</button>
                        <button class="btn btn-secondary" id="ks-mine-tab-collect" onclick="KsMinePage.switchTab('collect')">收藏</button>
                    </div>
                    <div style="display: flex; gap: 8px; align-items: center;">
                        <button class="btn btn-secondary btn-sm" onclick="KsMinePage.refresh()">刷新</button>
                        <div id="ks-mine-header-actions"></div>
                    </div>
                </div>
                <p style="margin: 12px 0 0; font-size: 0.85rem; color: var(--text-muted);">
                    需有效的 www 登录 Cookie（推荐在「扫码登录」页粘贴 Cookie，避免扫码挤下线手机）。列表依赖网页可见内容。
                </p>
            </div>

            <div class="card" id="ks-mine-list-card">
                <div id="ks-mine-grid" class="video-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: var(--spacing-md);"></div>
                <div id="ks-mine-empty" style="display: none; text-align: center; padding: var(--spacing-xl); color: var(--text-muted);">
                    暂无内容。请确认已登录，且该列表在网页端有作品。
                </div>
                <div id="ks-mine-loading" style="display: none; text-align: center; padding: var(--spacing-xl);">
                    <div class="spinner"></div>
                    <p style="margin-top: 12px; color: var(--text-muted);">正在通过浏览器拉取列表（含签名）...</p>
                </div>
                <div id="ks-mine-more" style="display: none; text-align: center; padding: var(--spacing-md);">
                    <button class="btn btn-secondary" id="ks-mine-more-btn" onclick="KsMinePage.loadMore()">加载更多</button>
                </div>
            </div>
        `;
    },

    init() {
        this.tab = 'liked';
        this.items = [];
        this.pcursor = '';
        this.hasMore = false;
        this.isSelectMode = false;
        this.updateTabButtons();
        this.loadList();
    },

    onShow() {
        this.updateTabButtons();
    },

    switchTab(tab) {
        if (this.tab === tab || this.loading || this.loadingMore) return;
        this.tab = tab;
        this.items = [];
        this.pcursor = '';
        this.hasMore = false;
        this.isSelectMode = false;
        this.updateTabButtons();
        this.loadList();
    },

    updateTabButtons() {
        const liked = document.getElementById('ks-mine-tab-liked');
        const collect = document.getElementById('ks-mine-tab-collect');
        if (liked) {
            liked.className = this.tab === 'liked' ? 'btn btn-primary' : 'btn btn-secondary';
        }
        if (collect) {
            collect.className = this.tab === 'collect' ? 'btn btn-primary' : 'btn btn-secondary';
        }
    },

    async refresh() {
        this.pcursor = '';
        this.items = [];
        this.hasMore = false;
        await this.loadList();
    },

    async loadList() {
        if (this.loading) return;
        this.loading = true;
        const isFirstPage = !this.pcursor;
        this.showLoading(isFirstPage);
        try {
            const endpoint = this.tab === 'liked' ? '/api/kuaishou/liked' : '/api/kuaishou/collected';
            const res = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pcursor: this.pcursor || '' }),
            });
            const data = await res.json();
            if (data.error) throw new Error(data.error);

            if (isFirstPage) {
                this.items = data.items || [];
            } else {
                this.items = this.items.concat(data.items || []);
            }
            this.pcursor = data.pcursor || '';
            this.hasMore = !!data.has_more;
            this.renderGrid();
        } catch (err) {
            const msg = err.message || '';
            const needLogin = /登录|扫码|凭证|登录态|未登录|已失效/.test(msg);
            if (needLogin) {
                Modal.confirm(
                    '快手登录无效或已过期',
                    `${this.escape(msg)}<br><br>请到「扫码登录」用「打开浏览器自动获取」重新登录（不要反复扫码挤 App）。`,
                    () => Router.navigate('ks_login')
                );
            } else {
                Toast.show(msg, 'error');
            }
            if (!this.items.length) this.renderGrid();
        } finally {
            this.loading = false;
            this.showLoading(false);
        }
    },

    async loadMore() {
        if (this.loadingMore || !this.hasMore || this.loading) return;
        this.loadingMore = true;
        const btn = document.getElementById('ks-mine-more-btn');
        if (btn) { btn.disabled = true; btn.textContent = '加载中...'; }
        try {
            await this.loadList();
        } finally {
            this.loadingMore = false;
            if (btn) { btn.disabled = false; btn.textContent = '加载更多'; }
        }
    },

    showLoading(on) {
        const el = document.getElementById('ks-mine-loading');
        if (el) el.style.display = on ? 'block' : 'none';
    },

    renderGrid() {
        const grid = document.getElementById('ks-mine-grid');
        const empty = document.getElementById('ks-mine-empty');
        const more = document.getElementById('ks-mine-more');
        if (!grid) return;

        if (!this.items.length) {
            grid.innerHTML = '';
            grid.style.display = 'none';
            if (empty) empty.style.display = 'block';
            if (more) more.style.display = 'none';
            this.updateHeaderActions();
            return;
        }

        if (empty) empty.style.display = 'none';
        grid.style.display = 'grid';
        grid.innerHTML = this.items.map((it, idx) => this.renderCard(it, idx)).join('');
        if (more) more.style.display = this.hasMore ? 'block' : 'none';
        this.updateHeaderActions();
    },

    renderCard(item, idx) {
        const title = item.title || item.caption || '无标题';
        const cover = item.cover || item.cover_url || '';
        const author = item.author || item.nickname || '';
        const pid = item.photo_id || item.id || idx;
        return `
            <div class="video-card" style="border-radius: 12px; overflow: hidden; background: var(--bg-secondary); position: relative;">
                <div style="position: relative; padding-top: 133%; background: var(--bg-body);">
                    <img src="${cover}" alt="" style="position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover;" onerror="this.style.display='none'">
                    <input type="checkbox" class="ks-mine-check" data-idx="${idx}" style="position:absolute;top:8px;left:8px;width:18px;height:18px;z-index:5;display:${this.isSelectMode ? 'block' : 'none'};" onclick="event.stopPropagation(); KsMinePage.updateDownloadButton();">
                </div>
                <div style="padding: 10px;">
                    <div style="font-size: 0.9rem; line-height: 1.35; height: 2.7em; overflow: hidden;">${this.escape(title)}</div>
                    <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 6px;">${this.escape(author)}</div>
                    <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 4px;">ID: ${this.escape(String(pid))}</div>
                </div>
            </div>
        `;
    },

    escape(s) {
        return String(s || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    },

    updateHeaderActions() {
        const box = document.getElementById('ks-mine-header-actions');
        if (!box) return;
        if (!this.items.length) {
            box.innerHTML = '';
            return;
        }
        if (this.isSelectMode) {
            box.innerHTML = `
                <button class="btn btn-secondary btn-sm" onclick="KsMinePage.toggleSelectAll()">全选</button>
                <button class="btn btn-primary btn-sm" id="ks-mine-dl-btn" onclick="KsMinePage.downloadSelected()" disabled>下载选中</button>
                <button class="btn btn-secondary btn-sm" onclick="KsMinePage.exitSelectMode()">取消</button>
            `;
            this.updateDownloadButton();
        } else {
            box.innerHTML = `
                <button class="btn btn-secondary btn-sm" onclick="KsMinePage.enterSelectMode()">多选</button>
                <button class="btn btn-primary btn-sm" onclick="KsMinePage.downloadAll()">下载本页全部</button>
            `;
        }
    },

    enterSelectMode() {
        this.isSelectMode = true;
        document.querySelectorAll('.ks-mine-check').forEach(cb => cb.style.display = 'block');
        this.updateHeaderActions();
    },

    exitSelectMode() {
        this.isSelectMode = false;
        document.querySelectorAll('.ks-mine-check').forEach(cb => {
            cb.checked = false;
            cb.style.display = 'none';
        });
        this.updateHeaderActions();
    },

    toggleSelectAll() {
        const boxes = [...document.querySelectorAll('.ks-mine-check')];
        const allOn = boxes.every(b => b.checked);
        boxes.forEach(b => b.checked = !allOn);
        this.updateDownloadButton();
    },

    updateDownloadButton() {
        const btn = document.getElementById('ks-mine-dl-btn');
        if (!btn) return;
        const n = document.querySelectorAll('.ks-mine-check:checked').length;
        btn.disabled = n === 0;
        btn.textContent = n ? `下载选中 (${n})` : '下载选中';
    },

    selectedItems() {
        return [...document.querySelectorAll('.ks-mine-check:checked')]
            .map(cb => this.items[Number(cb.dataset.idx)])
            .filter(Boolean);
    },

    async downloadSelected() {
        const items = this.selectedItems();
        if (!items.length) return;
        await this._startDownload(items);
    },

    async downloadAll() {
        if (!this.items.length) return;
        await this._startDownload(this.items);
    },

    async _startDownload(items) {
        try {
            Toast.show('已加入下载队列...', 'info');
            const res = await API.kuaishou.downloadSelected(items);
            if (res.error) throw new Error(res.error);
            Toast.show(res.message || '下载已启动', 'success');
            Router.navigate('ks_downloads');
        } catch (err) {
            Toast.show(err.message || '下载失败', 'error');
        }
    },
};
