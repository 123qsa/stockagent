# RAG 模块

基于 RAGFlow 的向量检索与问答能力，为股票公告提供深度检索和对话分析。

## 前置要求

- Docker >= 24.0.0
- Docker Compose >= v2.26.1
- CPU >= 4核, RAM >= 16GB, Disk >= 50GB

## 部署 RAGFlow

```bash
cd rag
docker compose -f docker-compose.ragflow.yml up -d
```

首次启动需要下载模型（约 2GB），请耐心等待。

服务就绪后访问 http://localhost:9380，默认账号：
- 邮箱：`admin@ragflow.io`
- 密码：`ragflow`

## 配置

在项目根目录 `.env` 中添加：

```env
RAGFLOW_API_KEY=ragflow-your-api-key
RAGFLOW_BASE_URL=http://localhost:9380
```

API Key 在 RAGFlow Web UI 的「个人设置」中生成。

## 使用

### 命令行

```bash
# 同步公告到 RAGFlow
python main.py ragflow-sync 000001 --limit 10

# 检索公告
python main.py ragflow-query 000001 "2024年净利润是多少"

# Chat 问答
python main.py ragflow-chat 000001 "分析这份年报的风险"
```

### Python API

```python
from rag import RAGFlowAdapter

adapter = RAGFlowAdapter()

# 同步公告
adapter.sync_stock_announcements("000001", limit=10)

# 检索
chunks = adapter.retrieve("000001", "净利润同比增长率")

# 问答
answer = adapter.chat("000001", "这份公告对股价有什么影响？")
```

## 架构

```
rag/
├── __init__.py              # 模块入口
├── ragflow_adapter.py       # RAGFlow SDK 封装
└── docker-compose.ragflow.yml  # 部署配置
```
