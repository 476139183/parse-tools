/**
 * 单一页面注册表：Router / 侧栏 data-page / mp-mode 共用。
 * 在各 Page 组件脚本加载之后、router.js 之前引入。
 */
window.PageRegistry = (function () {
    const entries = [
        { key: 'login', group: 'wechat', mp: true, get: () => typeof LoginPage !== 'undefined' ? LoginPage : null },
        { key: 'accounts', group: 'wechat', mp: true, get: () => typeof AccountsPage !== 'undefined' ? AccountsPage : null },
        { key: 'articles', group: 'wechat', mp: true, get: () => typeof ArticlesPage !== 'undefined' ? ArticlesPage : null },
        { key: 'download', group: 'wechat', mp: true, get: () => typeof DownloadPage !== 'undefined' ? DownloadPage : null },
        { key: 'history', group: 'wechat', mp: true, get: () => typeof HistoryPage !== 'undefined' ? HistoryPage : null },
        { key: 'proxy', group: 'system', mp: true, get: () => typeof ProxyPage !== 'undefined' ? ProxyPage : null },
        { key: 'settings', group: 'system', mp: true, get: () => typeof SettingsPage !== 'undefined' ? SettingsPage : null },

        { key: 'channels', group: 'channels', get: () => typeof ChannelsPage !== 'undefined' ? ChannelsPage : null },
        { key: 'channels_login', group: 'channels', get: () => typeof ChannelsLoginPage !== 'undefined' ? ChannelsLoginPage : null },
        { key: 'channels_accounts', group: 'channels', get: () => typeof ChannelsAccountsPage !== 'undefined' ? ChannelsAccountsPage : null },
        { key: 'channels_history', group: 'channels', get: () => typeof ChannelsHistoryPage !== 'undefined' ? ChannelsHistoryPage : null },
        { key: 'channels_user', group: 'channels', get: () => typeof ChannelsUserPage !== 'undefined' ? ChannelsUserPage : null },

        { key: 'transcode', group: 'system', get: () => typeof TranscodePage !== 'undefined' ? TranscodePage : null },
        { key: 'dy_transcode', group: 'douyin', get: () => typeof TranscodePage !== 'undefined' ? TranscodePage : null },

        { key: 'dy_login', group: 'douyin', get: () => typeof DyLoginComponent !== 'undefined' ? DyLoginComponent : null },
        { key: 'dy_dashboard', group: 'douyin', get: () => typeof DyDashboardPage !== 'undefined' ? DyDashboardPage : null },
        { key: 'dy_search', group: 'douyin', get: () => typeof DySearchPage !== 'undefined' ? DySearchPage : null },
        { key: 'dy_user', group: 'douyin', get: () => typeof DyUserPage !== 'undefined' ? DyUserPage : null },
        { key: 'dy_parse', group: 'douyin', get: () => typeof DyParsePage !== 'undefined' ? DyParsePage : null },
        { key: 'dy_recommend', group: 'douyin', get: () => typeof DyRecommendPage !== 'undefined' ? DyRecommendPage : null },
        { key: 'dy_downloads', group: 'douyin', get: () => typeof DyDownloadsPage !== 'undefined' ? DyDownloadsPage : null },
        { key: 'dy_liked', group: 'douyin', get: () => typeof DyLikedPage !== 'undefined' ? DyLikedPage : null },
        { key: 'dy_collections', group: 'douyin', get: () => typeof DyCollectionsPage !== 'undefined' ? DyCollectionsPage : null },

        { key: 'ks_login', group: 'kuaishou', get: () => typeof KsLoginComponent !== 'undefined' ? KsLoginComponent : null },
        { key: 'ks_accounts', group: 'kuaishou', get: () => typeof KsAccountsPage !== 'undefined' ? KsAccountsPage : null },
        { key: 'ks_user', group: 'kuaishou', get: () => typeof KsUserPage !== 'undefined' ? KsUserPage : null },
        { key: 'ks_parse', group: 'kuaishou', get: () => typeof KsParsePage !== 'undefined' ? KsParsePage : null },
        { key: 'ks_downloads', group: 'kuaishou', get: () => typeof KsDownloadsPage !== 'undefined' ? KsDownloadsPage : null },

        { key: 'xhs_login', group: 'xhs', get: () => typeof XhsLoginPage !== 'undefined' ? XhsLoginPage : null },
        { key: 'xhs_accounts', group: 'xhs', get: () => typeof XhsAccountsPage !== 'undefined' ? XhsAccountsPage : null },
        { key: 'xhs_notes', group: 'xhs', get: () => typeof XhsNotesPage !== 'undefined' ? XhsNotesPage : null },
        { key: 'xhs_download', group: 'xhs', get: () => typeof XhsDownloadPage !== 'undefined' ? XhsDownloadPage : null },
        { key: 'xhs_history', group: 'xhs', get: () => typeof XhsHistoryPage !== 'undefined' ? XhsHistoryPage : null },

        { key: 'bili_login', group: 'bilibili', get: () => typeof BiliLoginPage !== 'undefined' ? BiliLoginPage : null },
        { key: 'bili_accounts', group: 'bilibili', get: () => typeof BiliAccountsPage !== 'undefined' ? BiliAccountsPage : null },
        { key: 'bili_videos', group: 'bilibili', get: () => typeof BiliVideosPage !== 'undefined' ? BiliVideosPage : null },
        { key: 'bili_download', group: 'bilibili', get: () => typeof BiliDownloadPage !== 'undefined' ? BiliDownloadPage : null },
        { key: 'bili_history', group: 'bilibili', get: () => typeof BiliHistoryPage !== 'undefined' ? BiliHistoryPage : null },
    ];

    function buildRoutes() {
        const routes = {};
        entries.forEach((e) => {
            routes[e.key] = e.get();
        });
        return routes;
    }

    function mpAllowedKeys() {
        return entries.filter((e) => e.mp).map((e) => e.key);
    }

    return { entries, buildRoutes, mpAllowedKeys };
})();
