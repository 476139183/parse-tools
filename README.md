# Parse Tools

多平台内容解析、下载与归档工具箱。

## 目录

```
parse-tools/
  app.py / app_mp.py / main.py
  parse_tools/          # 业务代码 + frontend/
  ops/                  # 运维与附属：injection / packaging / deploy / docs / scripts / ...
  tests/
  data/                 # 运行时数据（本地生成）
```

## 启动

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

打包：`pyinstaller ops/packaging/parse_tools.spec`  
架构说明：`ops/docs/ARCHITECTURE.md`
