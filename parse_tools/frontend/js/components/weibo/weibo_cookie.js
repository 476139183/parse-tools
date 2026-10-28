const WeiboCookiePage = {
    render() {
        return `
            <div class="page-header">
                <h2 class="page-title">微博 Cookie</h2>
                <p class="page-description">粘贴浏览器登录后的 Cookie，用于解析需登录可见的博文与原图 / 视频</p>
            </div>
            <div class="card">
                <div class="card-body" style="padding: 0 var(--spacing-md) var(--spacing-md);">
                    <div class="form-group" style="margin-top: var(--spacing-md);">
                        <label class="form-label" for="weibo-cookie-input">Cookie 字符串</label>
                        <textarea id="weibo-cookie-input" class="form-input" rows="8"
                            placeholder="从 weibo.com 或 m.weibo.cn 已登录页面复制 Cookie…"
                            style="font-family: monospace; font-size: 0.85rem;"></textarea>
                        <div class="form-hint">
                            在 Chrome 打开并登录微博 → F12 → Network → 任选请求 → Request Headers → Cookie。
                            仅保存在本机设置，不会上传。
                        </div>
                    </div>
                    <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                        <button class="btn btn-primary" onclick="WeiboCookiePage.save()">保存 Cookie</button>
                        <button class="btn btn-secondary" onclick="WeiboCookiePage.clear()">清空</button>
                        <span id="weibo-cookie-status" style="align-self: center; font-size: 0.85rem; color: var(--text-muted);"></span>
                    </div>
                </div>
            </div>
        `;
    },

    async init() {
        await this.load();
    },

    async onShow() {
        await this.load();
    },

    async load() {
        try {
            const data = await API.weibo.getCookie();
            const el = document.getElementById('weibo-cookie-input');
            if (el) el.value = data.cookie || '';
            const st = document.getElementById('weibo-cookie-status');
            if (st) st.textContent = data.has_cookie ? '已配置 Cookie' : '尚未配置 Cookie（部分博文可能解析失败）';
        } catch (e) {
            /* API wrapper */
        }
    },

    async save() {
        const el = document.getElementById('weibo-cookie-input');
        const cookie = el ? el.value.trim() : '';
        try {
            await API.weibo.saveCookie(cookie);
            Toast.success(cookie ? 'Cookie 已保存' : 'Cookie 已清空');
            await this.load();
        } catch (e) { /* handled */ }
    },

    async clear() {
        const el = document.getElementById('weibo-cookie-input');
        if (el) el.value = '';
        await this.save();
    },
};
