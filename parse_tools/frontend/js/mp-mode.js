/**
 * 公众号精简模式（app_mp.py 部署时生效）
 *
 * 服务端 /api/capabilities 返回 mode === 'mp-only' 时：
 *   1. 隐藏未打包模块的导航入口（抖音 / 快手 / 小红书 / B 站 / 视频号 / 转码）
 *   2. 隐藏空掉的导航分组
 *   3. 拦截直接输地址访问未启用页面的情况
 *
 * 桌面版（app.py）没有这个接口返回 mp-only，本文件不产生任何影响。
 */
(function () {
    'use strict';

    // 公众号版保留的页面：优先读 PageRegistry，避免与路由表漂移
    var ALLOWED = (window.PageRegistry && window.PageRegistry.mpAllowedKeys)
        ? window.PageRegistry.mpAllowedKeys()
        : ['login', 'accounts', 'articles', 'download', 'history', 'proxy', 'settings'];
    var FALLBACK = 'articles';

    function applyNav() {
        document.querySelectorAll('.nav-item[data-page]').forEach(function (el) {
            var page = el.getAttribute('data-page');
            if (ALLOWED.indexOf(page) === -1) {
                el.style.display = 'none';
            }
        });

        // 整组都被隐藏时，把分组标题、分组上方的分隔线一起收起来
        document.querySelectorAll('.nav-group-title[data-group]').forEach(function (title) {
            var items = title.nextElementSibling;
            if (!items || !items.classList.contains('nav-group-items')) return;
            var visible = Array.prototype.some.call(
                items.querySelectorAll('.nav-item'),
                function (item) { return item.style.display !== 'none'; }
            );
            if (!visible) {
                title.style.display = 'none';
                items.style.display = 'none';
                var divider = title.previousElementSibling;
                if (divider && divider.classList.contains('nav-divider')) {
                    divider.style.display = 'none';
                }
            }
        });

        // 登录状态只保留微信
        ['dy-status', 'xhs-status', 'bili-status'].forEach(function (id) {
            var el = document.getElementById(id);
            if (el) el.style.display = 'none';
        });

        // 平台轨道只留公众号 + 工具
        document.querySelectorAll('.platform-chip[data-group]').forEach(function (chip) {
            var g = chip.getAttribute('data-group');
            if (g !== 'wechat' && g !== 'common') {
                chip.style.display = 'none';
            }
        });
    }

    function applyBranding() {
        var h1 = document.querySelector('.logo-text h1');
        var sub = document.querySelector('.logo-text .logo-subtitle');
        if (h1) h1.textContent = 'Parse Tools';
        if (sub) sub.textContent = '公众号 + RSS';
    }

    /**
     * 隐藏只对全功能版有意义的设置项（如视频号 Worker、微信读书中转）。
     *
     * 用注入 CSS 的方式，而不是直接遍历 DOM：
     * 设置页是路由懒渲染的，页面可能在 capabilities 返回之后才渲染出来，
     * 靠 CSS 选择器能覆盖到之后才出现的节点。
     */
    function applyHiddenBlocks() {
        document.body.classList.add('mp-only');

        if (document.getElementById('mp-mode-style')) return;
        var style = document.createElement('style');
        style.id = 'mp-mode-style';
        style.textContent =
            'body.mp-only [data-mp-hide]{display:none !important;}';
        document.head.appendChild(style);
    }

    function guardHash() {
        var key = (window.location.hash.slice(1) || 'login').split('?')[0];
        if (ALLOWED.indexOf(key) === -1) {
            window.location.hash = '#' + FALLBACK;
        }
    }

    fetch('/api/capabilities', { headers: { Accept: 'application/json' } })
        .then(function (resp) {
            if (!resp.ok) return null;
            // 桌面版没有这个接口，会被 SPA 兜底返回 index.html，这里直接跳过
            var ct = resp.headers.get('content-type') || '';
            if (ct.indexOf('json') === -1) return null;
            return resp.json();
        })
        .then(function (cap) {
            if (!cap || cap.mode !== 'mp-only') return;

            window.MP_MODE = { allowed: ALLOWED, fallback: FALLBACK };

            applyNav();
            applyBranding();
            applyHiddenBlocks();
            guardHash();
            window.addEventListener('hashchange', guardHash);

            console.info('[mp-mode] 已切换为公众号精简模式，隐藏模块：', (cap.disabled || []).join('、'));
        })
        .catch(function () {
            /* 拿不到能力清单就按完整版处理，不影响使用 */
        });
})();
