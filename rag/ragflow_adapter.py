"""RAGFlow 集成适配器

通过 ragflow-sdk 与 RAGFlow 服务交互，提供：
1. 股票公告知识库管理（Dataset）
2. PDF 上传与解析
3. 检索与问答

使用前提：
- 部署 RAGFlow 服务（见 docker-compose.ragflow.yml）
- 配置 RAGFLOW_API_KEY 和 RAGFLOW_BASE_URL
"""

import os
from typing import List, Optional, Dict

from config import RAGFLOW_API_KEY, RAGFLOW_BASE_URL


class RAGFlowAdapter:
    """RAGFlow 股票公告适配器"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._client = None
        return cls._instance

    def _get_client(self):
        if self._client is None:
            if not RAGFLOW_API_KEY or not RAGFLOW_BASE_URL:
                raise RuntimeError(
                    "RAGFlow 未配置。请设置环境变量：\n"
                    "  RAGFLOW_API_KEY=<your_api_key>\n"
                    "  RAGFLOW_BASE_URL=http://localhost:9380\n"
                    "或修改 .env 文件。"
                )
            try:
                from ragflow_sdk import RAGFlow
                self._client = RAGFlow(api_key=RAGFLOW_API_KEY, base_url=RAGFLOW_BASE_URL)
            except ImportError:
                raise RuntimeError("ragflow-sdk 未安装，请执行: pip install ragflow-sdk")
        return self._client

    def _dataset_name(self, stock_code: str) -> str:
        """生成股票知识库名称"""
        return f"stock_{stock_code}_announcements"

    def get_or_create_dataset(
        self,
        stock_code: str,
        embedding_model: Optional[str] = None,
        chunk_method: str = "naive",
    ) -> "DataSet":
        """获取或创建某只股票的知识库"""
        client = self._get_client()
        name = self._dataset_name(stock_code)

        # 尝试获取已有
        try:
            ds = client.get_dataset(name=name)
            print(f"[RAGFlow] 找到知识库: {name} (id={ds.id})")
            return ds
        except Exception:
            pass

        # 创建新的
        print(f"[RAGFlow] 创建知识库: {name}")
        ds = client.create_dataset(
            name=name,
            description=f"股票 {stock_code} 公告知识库",
            embedding_model=embedding_model,
            chunk_method=chunk_method,
            permission="me",
        )
        return ds

    def upload_announcement(
        self,
        stock_code: str,
        pdf_path: str,
        display_name: Optional[str] = None,
    ) -> "Document":
        """上传单条公告 PDF 到知识库

        Returns:
            Document 对象
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF 不存在: {pdf_path}")

        ds = self.get_or_create_dataset(stock_code)

        if display_name is None:
            display_name = os.path.basename(pdf_path)

        with open(pdf_path, "rb") as f:
            blob = f.read()

        docs = ds.upload_documents([{"display_name": display_name, "blob": blob}])
        if docs:
            print(f"[RAGFlow] 上传成功: {display_name} (doc_id={docs[0].id})")
            return docs[0]
        raise RuntimeError("上传失败，未返回文档对象")

    def parse_documents(
        self,
        stock_code: str,
        document_ids: Optional[List[str]] = None,
    ) -> List[tuple]:
        """触发知识库中的文档解析（DeepDoc 解析 + 分块 + Embedding）

        Args:
            document_ids: 指定文档ID列表，None则解析该知识库所有文档

        Returns:
            [(doc_id, status, chunk_count, token_count), ...]
        """
        ds = self.get_or_create_dataset(stock_code)

        if document_ids is None:
            docs = ds.list_documents(page_size=100)
            document_ids = [d.id for d in docs if hasattr(d, "id")]

        if not document_ids:
            print(f"[RAGFlow] 知识库中没有待解析文档")
            return []

        print(f"[RAGFlow] 开始解析 {len(document_ids)} 个文档...")
        results = ds.parse_documents(document_ids)
        for doc_id, status, chunk_count, token_count in results:
            print(f"  {doc_id}: {status} (chunks={chunk_count}, tokens={token_count})")
        return results

    def retrieve(
        self,
        stock_code: str,
        question: str,
        top_k: int = 10,
        similarity_threshold: float = 0.2,
        keyword: bool = True,
    ) -> List["Chunk"]:
        """在股票公告知识库中检索相关内容

        Args:
            question: 查询问题，如"2024年Q3净利润同比增长率是多少"
            top_k: 返回最相关的 top_k 个 chunk
            similarity_threshold: 相似度阈值
            keyword: 是否启用关键词检索（混合检索）

        Returns:
            Chunk 对象列表
        """
        client = self._get_client()
        ds = self.get_or_create_dataset(stock_code)

        chunks = client.retrieve(
            dataset_ids=[ds.id],
            question=question,
            page_size=top_k,
            similarity_threshold=similarity_threshold,
            keyword=keyword,
        )
        print(f"[RAGFlow] 检索 '{question}' 返回 {len(chunks)} 条结果")
        return chunks

    def chat(
        self,
        stock_code: str,
        question: str,
        chat_name: Optional[str] = None,
    ) -> str:
        """通过 Chat Assistant 进行问答（带 RAG 检索）

        Args:
            question: 用户问题
            chat_name: Chat Assistant 名称，默认 auto-create

        Returns:
            LLM 回答文本
        """
        client = self._get_client()
        ds = self.get_or_create_dataset(stock_code)

        if chat_name is None:
            chat_name = f"{stock_code}_analyst"

        # 获取或创建 Chat
        chats = client.list_chats(name=chat_name)
        if chats:
            chat = chats[0]
        else:
            chat = client.create_chat(
                name=chat_name,
                dataset_ids=[ds.id],
            )

        # 创建会话并提问
        session = chat.create_session()
        response = session.ask(question)
        return response.content

    def sync_stock_announcements(
        self,
        stock_code: str,
        limit: int = 10,
        auto_parse: bool = True,
        batch_size: int = 10,
        skip_existing: bool = True,
    ) -> Dict:
        """同步某只股票的最新公告到 RAGFlow

        从本地 SQLite 数据库读取已下载的公告，上传到 RAGFlow。
        支持批量上传、进度显示、断点续传。

        Args:
            stock_code: 股票代码
            limit: 最多同步多少条，None 表示全部
            auto_parse: 上传后是否自动触发解析
            batch_size: 每批上传的文档数量
            skip_existing: 是否跳过知识库中已存在的同名文档

        Returns:
            {"uploaded": int, "skipped": int, "parsed": int, "errors": int, "doc_ids": [...]}
        """
        from database import get_db, Announcement

        db = get_db()
        try:
            query = (
                db.query(Announcement)
                .filter(
                    Announcement.stock_code == stock_code,
                    Announcement.downloaded == True,
                    Announcement.local_path.isnot(None),
                )
                .order_by(Announcement.announcement_time.desc())
            )
            if limit is not None:
                query = query.limit(limit)
            anns = query.all()

            print(f"[RAGFlow] 准备同步 {stock_code}，共 {len(anns)} 条公告（limit={limit}）")

            ds = self.get_or_create_dataset(stock_code)

            # 获取知识库中已有文档列表（用于去重）
            existing_names = set()
            if skip_existing:
                try:
                    existing_docs = ds.list_documents(page_size=1000)
                    existing_names = {d.name for d in existing_docs if hasattr(d, "name")}
                    print(f"[RAGFlow] 知识库已有 {len(existing_names)} 个文档")
                except Exception as e:
                    print(f"[RAGFlow] 获取已有文档列表失败，跳过去重检查: {e}")

            results = {"uploaded": 0, "skipped": 0, "parsed": 0, "errors": 0, "doc_ids": []}
            batch = []
            batch_meta = []  # 对应的 (announcement_id, display_name)

            def _flush_batch():
                """上传当前批次"""
                nonlocal batch, batch_meta, results
                if not batch:
                    return
                try:
                    docs = ds.upload_documents(batch)
                    if docs and len(docs) == len(batch):
                        for i, doc in enumerate(docs):
                            if hasattr(doc, "id"):
                                results["uploaded"] += 1
                                results["doc_ids"].append(doc.id)
                                print(f"  ✓ {batch_meta[i][1][:60]}... (doc_id={doc.id})")
                            else:
                                results["errors"] += 1
                                print(f"  ✗ {batch_meta[i][1][:60]}... (返回文档无ID)")
                    else:
                        # 批量上传部分失败，逐个重试
                        for i, item in enumerate(batch):
                            try:
                                docs_retry = ds.upload_documents([item])
                                if docs_retry and hasattr(docs_retry[0], "id"):
                                    results["uploaded"] += 1
                                    results["doc_ids"].append(docs_retry[0].id)
                                    print(f"  ✓ {batch_meta[i][1][:60]}... (retry ok)")
                                else:
                                    results["errors"] += 1
                                    print(f"  ✗ {batch_meta[i][1][:60]}... (retry failed)")
                            except Exception as e2:
                                results["errors"] += 1
                                print(f"  ✗ {batch_meta[i][1][:60]}... (retry error: {e2})")
                except Exception as e:
                    print(f"[RAGFlow] 批量上传失败，尝试逐个上传: {e}")
                    for i, item in enumerate(batch):
                        try:
                            docs_retry = ds.upload_documents([item])
                            if docs_retry and hasattr(docs_retry[0], "id"):
                                results["uploaded"] += 1
                                results["doc_ids"].append(docs_retry[0].id)
                                print(f"  ✓ {batch_meta[i][1][:60]}... (fallback ok)")
                            else:
                                results["errors"] += 1
                                print(f"  ✗ {batch_meta[i][1][:60]}... (fallback failed)")
                        except Exception as e2:
                            results["errors"] += 1
                            print(f"  ✗ {batch_meta[i][1][:60]}... (fallback error: {e2})")
                batch = []
                batch_meta = []

            for idx, ann in enumerate(anns, 1):
                display_name = (
                    f"{ann.announcement_time.strftime('%Y%m%d')}_{ann.title[:80]}.pdf"
                    if ann.announcement_time
                    else f"{ann.announcement_id}_{ann.title[:80]}.pdf"
                )

                if display_name in existing_names:
                    results["skipped"] += 1
                    if idx % 10 == 0 or idx == len(anns):
                        print(f"  [{idx}/{len(anns)}] 跳过已存在: {display_name[:60]}...")
                    continue

                if not os.path.exists(ann.local_path):
                    print(f"  [{idx}/{len(anns)}] PDF 文件不存在，跳过: {ann.local_path}")
                    results["errors"] += 1
                    continue

                try:
                    with open(ann.local_path, "rb") as f:
                        blob = f.read()
                except Exception as e:
                    print(f"  [{idx}/{len(anns)}] 读取失败: {e}")
                    results["errors"] += 1
                    continue

                batch.append({"display_name": display_name, "blob": blob})
                batch_meta.append((ann.announcement_id, display_name))

                if len(batch) >= batch_size:
                    print(f"  [{idx}/{len(anns)}] 上传批次 ({len(batch)} 个)...")
                    _flush_batch()
                elif idx == len(anns):
                    print(f"  [{idx}/{len(anns)}] 上传最后一批 ({len(batch)} 个)...")
                    _flush_batch()
                elif idx % 10 == 0:
                    print(f"  [{idx}/{len(anns)}] 处理中...")

            # 自动触发解析
            if auto_parse and results["doc_ids"]:
                print(f"[RAGFlow] 开始解析 {len(results['doc_ids'])} 个文档...")
                parse_results = self.parse_documents(stock_code, results["doc_ids"])
                results["parsed"] = sum(1 for _, s, _, _ in parse_results if s == "DONE")

            print(
                f"[RAGFlow] 同步完成: 上传 {results['uploaded']}, "
                f"跳过 {results['skipped']}, 解析成功 {results['parsed']}, 失败 {results['errors']}"
            )
            return results
        finally:
            db.close()

    def delete_stock_dataset(self, stock_code: str):
        """删除某只股票的知识库"""
        client = self._get_client()
        try:
            ds = client.get_dataset(name=self._dataset_name(stock_code))
            client.delete_datasets(ids=[ds.id])
            print(f"[RAGFlow] 已删除知识库: {self._dataset_name(stock_code)}")
        except Exception as e:
            print(f"[RAGFlow] 删除知识库失败: {e}")


def check_ragflow_available() -> bool:
    """检查 RAGFlow 服务是否可连接"""
    try:
        adapter = RAGFlowAdapter()
        client = adapter._get_client()
        # 简单调用 list_datasets 验证连通性
        client.list_datasets(page_size=1)
        return True
    except Exception as e:
        print(f"[RAGFlow] 服务不可用: {e}")
        return False
