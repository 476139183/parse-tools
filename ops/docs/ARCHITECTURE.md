# Parse Tools 架构指南

`main.py` / `app.py` / `app_mp.py` 是入口；业务在 `parse_tools/`；静态 UI 在 `parse_tools/frontend/`（含 `frontend/js/router.js` 哈希路由与 `api.js`）。运行时由 `resource_dir` / `app_dir` / `log_file` / `configure_runtime` 处理路径与日志。

## 架构视图

- 组件和依赖：[ops/docs/diagrams/software-architecture.mmd](ops/docs/diagrams/software-architecture.mmd)
- 启动、请求与任务生命周期：[ops/docs/diagrams/application-flow.mmd](ops/docs/diagrams/application-flow.mmd)
- Windows 与 macOS 打包流程：[ops/docs/diagrams/build-flow.mmd](ops/docs/diagrams/build-flow.mmd)

## 目录约定

| 路径 | 用途 |
|---|---|
| `parse_tools/core` | create_app、config、TaskStore、registry |
| `parse_tools/platforms/*` | 八平台适配（公众号 / 视频号 / 抖音 / 快手 / 小红书 / B 站 / 微博 / 支付宝）；公众号分 **文章** / **图文**，Live 仅图文 |
| `parse_tools/services` | proxy / transcode / updater / waterwall |
| `parse_tools/frontend/` | Hash SPA（`page_registry.js` + `router.js` + `api.js`） |
| `ops/injection/src/` | 视频号页面注入（第一方） |
| `ops/injection/lib/` | 注入依赖（vendored） |
| `ops/automation/` | mac / windows 自动化 |
| `ops/packaging/parse_tools.spec` | PyInstaller |
| `ops/vendor/subtitle_remover/` | 字幕擦除（vendored） |

## 模块地图

入口经 `parse_tools.core.app_factory.create_app(mode)` 注册蓝图；`mode=full|mp`。  
后台 RSS 由 `start_background_services()` 显式启动。  
任务进度进 `TaskStore`。

兼容说明：旧路径 `backend/*.py` 已移除，请使用 `parse_tools.*`。  
文档中若仍出现 `backend/config.py` 等字样，等价于 `parse_tools.core.config`（历史别名）：backend/config.py、backend/runtime.py、backend/account_pool.py、backend/rss_scheduler.py、backend/mitm_proxy.py、backend/transcode.py、backend/downloader.py、backend/articles.py、backend/channels.py。

## 请求流

浏览器/pywebview → Flask 蓝图 → 平台 Client → TaskStore → `DATA_DIR` 落盘 → 前端轮询。

## 启动流

1. `configure_runtime()`
2. `create_app(mode)`
3. `start_background_services()`
4. 桌面模式由 `main.py` 开窗口

## 后台工作

RSS 调度、账号池、转码队列、各平台下载线程。

## 存储

数据目录为 `data/`：`data/parse_tools.db` 与各平台下载目录。

## 构建与自动化

`ops/packaging/parse_tools.spec`；`.github/workflows/build.yml`；`ops/scripts/verify_macos_bundle.py`。产出含 macOS ARM64 / macOS x86_64。

## 扩展路径

在 `parse_tools/platforms/<name>/` 增加平台并在 `PlatformRegistry` 注册；前端改 `page_registry.js`。

## 平台能力速览

| 平台 | 包路径 | 典型入口 | 备注 |
|---|---|---|---|
| 微信公众号 | `platforms/wechat/` | 文章列表 / 下载 | **文章** vs **图文**；图文可下 Live mp4 |
| 视频号 | `platforms/channels/` | 分享链接 / MITM | 可选注入采集 |
| 抖音 | `platforms/douyin/` | 单条 / 主页 | 图集支持 Live |
| 快手 | `platforms/kuaishou/` | 单条 / 主页 | 图集 WebP；尝试 Live + BGM |
| 小红书 | `platforms/xiaohongshu/` | 链接下载 | 图集 Live mp4 |
| B 站 | `platforms/bilibili/` | 多分 P 下载 | 需 ffmpeg 混流 |
| 微博 | `platforms/weibo/` | `#weibo_parse` | Cookie；单条图文 / 视频 |
| 支付宝 | `platforms/alipay/` | `#alipay_parse` | 生活号+ 短链；**无需 Cookie** |

落盘目录（相对 `DATA_DIR`）：`wechat_*` / `douyin_downloads` / `kuaishou_downloads` / `xhs_downloads` / `bilibili_downloads` / `weibo_downloads` / `alipay_downloads` 等。

## Bug 路由

| 现象 | 入口 |
|---|---|
| 白屏 | `main.py`、`parse_tools.log` |
| 注入失败 | `ops/injection/src/`、mitm |
| 打包缺文件 | `ops/packaging/parse_tools.spec` |
