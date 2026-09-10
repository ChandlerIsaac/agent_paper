# ResearchMate Agent

多用户工作台已加入账号登录、持久化连续对话、笔记语义检索、
可点击的论文引用图谱，以及可选联网补充和执行过程摘要。
**当前版本启动、旧数据归属迁移与功能边界请阅读 [工作台使用说明](docs/workspace.md)。**
首次升级后请注册账号，再按文档运行本地旧知识库分配命令。

ResearchMate 是一个面向论文阅读和专题调研的多文档研究助理。第一版采用
LangChain、LangGraph、FastAPI、SQLite、Milvus Lite 和 Sentence Transformers，
支持本地文档入库、语义检索、多轮问答以及页码级引用。

## 当前能力

- 解析 PDF、DOCX、Markdown 和 TXT；
- 保留文件名、页码、文档 ID、切片 ID 等溯源元数据；
- 使用 multilingual-e5-small 生成归一化稠密向量；
- 使用持久化 Okapi BM25 补充精确词项检索，并通过 RRF 融合排名；
- 使用 Milvus Lite 存储向量，并按知识库隔离检索；
- 使用 LangGraph 执行“检索—必要时改写一次—生成回答”流程；
- 返回来源编号、文件名、页码、相关度和原文片段；
- 使用 SQLite 保存知识库、文档、消息和研究笔记；
- 从论文参考文献表构建“上传论文 → 引用论文”有向图，保留原始引文；
- 经用户逐次授权后使用 Crossref 补全引用论文元数据，并加入 RAG；
- 提供 FastAPI、SSE 状态事件和简单浏览器界面。

## 处理流程

```text
上传文档
  → 解析正文与页码
  → 递归文本切分
  ├→ E5 passage 向量 → Milvus Lite
  └→ BM25 词项索引 → SQLite

用户问题
  → E5 稠密检索 + BM25 稀疏检索
  → RRF 排名融合
  → 当前知识库 Top-K 证据
  → 证据不足时改写一次
  → MIMO 生成回答
  → 返回引用与原文片段
```

E5 使用模型论文推荐的非对称检索方式：问题添加 `query:` 前缀，文档添加
`passage:` 前缀，并使用余弦相似度检索。

## 项目结构

```text
agent_paper/
├── app/
│   ├── api/          # 请求和响应数据模型
│   ├── agent/        # LangGraph 状态、模型与工作流
│   ├── rag/          # 加载、切分、Embedding、Milvus 和 RAG 服务
│   ├── memory/       # SQLite 业务数据
│   ├── citations/    # 引用解析、Crossref 匹配和图谱持久化
│   ├── core/         # 配置、日志和异常
│   ├── static/       # 简单 Web 页面
│   ├── main.py       # FastAPI 应用
│   └── runtime.py    # 服务依赖的延迟初始化
├── scripts/          # 独立验证脚本
├── tests/            # 自动化测试
├── data/             # 上传文件、SQLite 和 Milvus Lite 数据
├── .env              # 真实配置，不提交 Git
├── .env.example      # 配置模板
├── pyproject.toml    # 固定版本的项目依赖
└── 项目书.md
```

## 环境要求

- Python 3.11；
- 当前项目使用 Conda 环境 `researchmate`；
- CUDA 可选；没有 NVIDIA GPU 时将 `EMBEDDING_DEVICE` 改为 `cpu`。

确认当前解释器：

```bash
conda activate researchmate
which python
python --version
```

安装项目和开发依赖：

```bash
python -m pip install -e ".[dev]"
```

该命令只会安装到当前激活的 Python 环境。

## 配置

从模板创建本地配置：

```bash
cp .env.example .env
```

必须配置：

```dotenv
MIMO_API_KEY=你的密钥
MIMO_BASE_URL=https://你的兼容接口/v1
MODEL_NAME=你的模型名称
```

本地存储默认值：

```dotenv
DATABASE_PATH=data/researchmate.sqlite3
UPLOAD_DIR=data/uploads
MILVUS_LITE_PATH=data/milvus/researchmate.db
MILVUS_COLLECTION=researchmate_chunks
HYBRID_SEARCH_ENABLED=true
HYBRID_CANDIDATE_K=10
RRF_RANK_CONSTANT=60
```

不要把 `.env` 或任何真实 API Key 提交到 Git。

## 分层验证

先验证大模型连接：

```bash
python -m tests.scripts.check_llm
```

验证 Embedding：

```bash
python -m scripts.check_embedding
```

项目默认 `EMBEDDING_OFFLINE=true`，模型加载使用 `local_files_only=True`，
直接启动 Uvicorn 即可读取本地缓存，无需额外 export。这只影响 Embedding，
MIMO 问答仍使用在线 API。缓存缺失时加载会失败；首次下载可运行
`EMBEDDING_OFFLINE=false python -m scripts.check_embedding`（若设置过
`HF_HUB_OFFLINE` 或 `TRANSFORMERS_OFFLINE`，需先取消这些全局离线设置）。

也可以额外使用 Hugging Face 全局离线模式：

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
python -m scripts.check_embedding
```

验证完整的本地 RAG 检索链，不调用外部大模型：

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
python -m scripts.check_rag \
  data/uploads/MlanDTI.pdf \
  "What is the multilevel attention mechanism?"
```

该脚本使用临时 SQLite 和 Milvus 文件，结束后不会污染正式知识库。

## 启动服务

在服务器项目根目录运行：

```bash
conda activate researchmate
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

服务器内可检查：

```bash
curl http://127.0.0.1:8000/api/health
```

Swagger 接口文档位于 `http://127.0.0.1:8000/docs`。

## 从本地电脑访问服务器界面

在本地电脑新开一个 PowerShell 窗口并保持运行：

```powershell
ssh -N -p 2223 -L 18000:127.0.0.1:8000 l@isaacyy.cn
```

随后在本地浏览器访问：

```text
http://127.0.0.1:18000
```

这个本地端口转发与下载模型所使用的反向代理方向不同，可以同时开启。

## 主要接口

| 方法 | 路径 | 功能 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| POST | `/api/knowledge-bases` | 创建知识库 |
| GET | `/api/knowledge-bases` | 查询知识库 |
| DELETE | `/api/knowledge-bases/{kb_id}` | 删除知识库及其向量 |
| POST | `/api/knowledge-bases/{kb_id}/documents` | 上传并索引文档 |
| GET | `/api/knowledge-bases/{kb_id}/documents` | 查询文档 |
| DELETE | `/api/knowledge-bases/{kb_id}/documents/{doc_id}` | 删除文档 |
| POST | `/api/knowledge-bases/{kb_id}/documents/{doc_id}/reindex` | 重建索引 |
| GET | `/api/knowledge-bases/{kb_id}/citation-graph` | 查询论文引用图谱 |
| POST | `/api/knowledge-bases/{kb_id}/documents/{doc_id}/citations/extract` | 离线重建引用关系 |
| POST | `/api/knowledge-bases/{kb_id}/citation-graph/enrich` | 经明确授权后补全元数据 |
| POST | `/api/chat` | 带引用问答 |
| POST | `/api/chat/stream` | SSE 状态和结果事件 |
| GET | `/api/conversations/{thread_id}/messages` | 查询消息历史 |
| POST | `/api/knowledge-bases/{kb_id}/notes` | 保存研究笔记 |
| GET | `/api/knowledge-bases/{kb_id}/notes?query=...` | 搜索笔记 |

## 测试

```bash
python -m pytest -q
```

自动化测试覆盖文档解析、切分元数据、SQLite、引用抽取、书目匹配、
FastAPI 健康检查，以及 Milvus 的知识库过滤和删除语义。

## 第一版边界

当前版本使用 E5 + BM25 + RRF 混合检索和 SQLite LangGraph Checkpointer，重启后可恢复会话状态。
Cross-Encoder 重排序、二跳引用扩展、人工实体消歧、评价数据集和 Docker Compose 属于后续阶段。
已有聊天接口现在需要账号登录及服务端创建的会话 ID，
详见工作台使用说明。
