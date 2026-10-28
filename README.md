<div align="center">

# Parse Tools

**多平台内容解析 · 下载 · 归档**

微信公众号 / 视频号 / 抖音 / 快手 / 小红书 / 哔哩哔哩

[![Python](https://img.shields.io/badge/Python-3.10+-0f766e?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.x-0f2233?style=flat-square&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/License-见仓库-5a6e82?style=flat-square)](LICENSE)
[![Version](https://img.shields.io/badge/version-3.0.0-14b8a6?style=flat-square)](https://github.com/476139183/parse-tools)

[快速开始](#快速开始) · [功能一览](#功能一览) · [目录结构](#目录结构) · [部署](#部署) · [文档](#文档)

</div>

---

## 这是什么

Parse Tools 是一款本地优先的**多平台内容工具箱**：粘贴链接即可解析下载，也支持账号池、批量采集、RSS 订阅、转码与桌面端封装。

| 入口 | 用途 |
|------|------|
| `python app.py` | 全功能 Web（浏览器） |
| `python app_mp.py` | 公众号 + RSS 精简服务 |
| `python main.py` | 桌面窗口（pywebview） |

默认地址：`http://127.0.0.1:5200`

---

## 功能一览

<table>
<tr>
<td width="50%" valign="top">

### 微信公众号
- 多账号池与轮换调度
- 历史文章 / 增量采集
- 离线 HTML · Markdown · PDF
- 标准 RSS 2.0 订阅

### 视频号
- 分享链接解析下载
- 作者主页与关注同步
- MITM 注入采集（可选）

### 抖音
- 无水印视频 / 图集 / Live
- 主页、喜欢、合集批量
- 评论抓取与直播解析

</td>
<td width="50%" valign="top">

### 快手 · 小红书 · B 站
- 单条 / 批量无水印下载
- 断点续传与重试
- B 站多分 P、弹幕 / 字幕

### 转码与系统
- FFmpeg 格式互转 / 压流
- 代理池与出站配置
- SQLite 默认，可切 MySQL

</td>
</tr>
</table>

---

## 快速开始

**环境：** Python 3.10+（建议 3.12）

```bash
git clone https://github.com/476139183/parse-tools.git
cd parse-tools

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
python app.py --port 5200
```

浏览器打开 [http://127.0.0.1:5200](http://127.0.0.1:5200)，顶栏粘贴链接即可「一键解析」。

<details>
<summary><b>可选：桌面端 / 公众号精简 / Playwright</b></summary>

```bash
# 桌面窗口
python main.py

# 仅公众号 + RSS（依赖更少）
pip install -r requirements-mp.txt
python app_mp.py --host 0.0.0.0 --port 5200

# 部分平台登录 / 浏览器通道需要
playwright install chromium
```

</details>

---

## 目录结构

```text
parse-tools/
├── app.py / app_mp.py / main.py   # 启动入口
├── parse_tools/                   # 业务包
│   ├── core/                      # 应用工厂 · TaskStore · 配置
│   ├── platforms/                 # 六平台适配
│   ├── services/                  # 代理 · 转码 · 更新
│   └── frontend/                  # Web UI
├── ops/                           # 运维与附属
│   ├── packaging/                 # PyInstaller spec
│   ├── deploy/                    # Docker / Nginx
│   ├── injection/                 # 视频号页面注入
│   ├── docs/                      # 架构与设计文档
│   └── vendor/                    # 字幕擦除等内嵌依赖
├── tests/
└── data/                          # 运行时数据（本地生成，不入库）
```

---

## 部署

### Docker（示意）

```bash
cd ops/deploy/docker
cp -n .env.example .env
mkdir -p data
docker compose up -d --build
```

更完整的说明见 [`ops/deploy/README.md`](ops/deploy/README.md)。

### 桌面打包

```bash
pyinstaller ops/packaging/parse_tools.spec
```

构建细节：[`ops/packaging/BUILD.md`](ops/packaging/BUILD.md)

---

## 文档

| 文档 | 说明 |
|------|------|
| [架构指南](ops/docs/ARCHITECTURE.md) | 包结构、启动流、扩展方式 |
| [学习路径](ops/docs/CODE_LEARNING_PATH.md) | 新人阅读顺序 |
| [部署说明](ops/deploy/README.md) | Docker / Nginx / RSS |
| [构建说明](ops/packaging/BUILD.md) | Windows / macOS 打包 |

---

## 开发提示

```bash
# 架构相关单测
pytest tests/test_app_factory.py tests/test_task_store.py -q

# 能力探针
curl -s http://127.0.0.1:5200/api/capabilities | python -m json.tool
```

数据默认落在 `data/parse_tools.db`；若存在旧版 `wechat_tools.db`，启动时会自动迁移改名。

---

## License

见仓库内 [`LICENSE`](LICENSE) 文件。请合规使用各平台内容，仅供学习与个人备份。

---

<div align="center">

Made for parsing · [Issues](https://github.com/476139183/parse-tools/issues)

</div>
