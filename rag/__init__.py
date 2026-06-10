"""RAG 模块

封装 RAGFlow 集成能力，提供：
1. 公告上传到 RAGFlow 知识库
2. 向量检索
3. Chat 问答

使用前提：
    部署 RAGFlow 服务（见 docker-compose.ragflow.yml）
    配置环境变量 RAGFLOW_API_KEY / RAGFLOW_BASE_URL

快速启动：
    cd rag && docker compose -f docker-compose.ragflow.yml up -d
"""

from .ragflow_adapter import RAGFlowAdapter, check_ragflow_available

__all__ = ["RAGFlowAdapter", "check_ragflow_available"]
