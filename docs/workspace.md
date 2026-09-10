# 多用户研究工作台

## 启动与使用

在 researchmate 环境中运行：

```bash
python -m pip install -e ".[dev]"
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

本地 Windows 转发：

```powershell
ssh -N -p 2223 -L 18000:127.0.0.1:8000 l@isaacyy.cn
```

打开 http://127.0.0.1:18000，先注册账号（用户名 3–40 位字母/数字/下划线/连字符，
密码至少 10 个字符），创建知识库并上传文档。按 Enter 发送，Shift+Enter 换行。
问题发送后输入框清空；失败时问题恢复到输入框。左侧会话支持新建、重命名、
删除与切换，刷新后重新读取完整聊天记录及引用。切换知识库会开始新的会话，
不会把旧会话的上下文带到另一个库。

此版本面向单进程、SSH 本地访问的个人/小组部署。Milvus Lite 与运行期锁按单进程设计，
不要添加多个 workers。多个账号之间数据隔离，但模型/索引操作会排队。
公开部署前需要 HTTPS（设置 COOKIE_SECURE=true）、反向代理限流及注册策略。
密码经 scrypt 加盐哈希；浏览器只保存 HttpOnly、SameSite=Strict 的随机会话 Cookie，
服务端只存令牌摘要，登录有效期 7 天。写接口要求 X-ResearchMate: 1，前端自动添加。
忘记密码恢复和管理员控制台尚未实现。

## 旧数据迁移

升级只新增表和 owner_id 字段。旧知识库不自动分配给第一个注册者，避免抢注获得旧资料。
在网页注册你自己的账号后，在服务器项目目录执行：

```bash
python -m scripts.claim_legacy 你的用户名
```

命令先备份业务 SQLite，再将 owner_id 为空的知识库分配给指定用户。
已有归属的知识库不会被改动，原文与 Milvus 向量继续复用。
旧版 messages 表保留，但其记录缺少可靠的知识库/用户关联，因此不自动导入新版会话。
如需导入旧会话，必须先人工确认归属。

## 存储与记忆边界

默认相对于项目根目录：

| 数据 | 路径/表 | 作用 |
|---|---|---|
| 账号、登录会话 | data/researchmate.sqlite3：users、sessions | 身份验证 |
| 知识库、文档记录 | 同一数据库：knowledge_bases、documents | owner_id 隔离知识库 |
| 会话、完整回答与引用 | 同一数据库：conversations、chat_turns | 页面刷新恢复 |
| LangGraph 状态 | data/checkpoints.sqlite3 | 重启后保留消息和工作流状态 |
| 笔记与向量 | 业务数据库：notes、note_vectors | 长期记忆及语义检索 |
| 文档切片向量 | data/milvus/researchmate.db | Milvus Lite 文档检索 |
| 原始文件 | data/uploads/知识库ID/上传ID/文件名 | 保留原文 |

Checkpointer 路径位于 DATABASE_PATH 的同级目录。会话 ID 由服务端生成，
每次读取、提问、重命名和删除都检查 owner_id。会话绑定知识库且不允许修改。
LangGraph 读取持久化消息，模型使用最近 12 条消息进行查询改写与回答。
短期历史消息只用于指代消解，不作为论文事实的独立证据。

笔记由用户明确点击“保存笔记”后建立索引；不会自动保存所有对话为长期记忆。
笔记全文按 700 字符分段、600 字符步长嵌入，再取向量均值作为检索表示。
小规模个人笔记采用 SQLite JSON 向量 + 精确余弦扫描；这不是 Milvus 的笔记 Collection，
数据量大时可升级。每个知识库只检索自己的笔记，旧笔记或模型版本变化时懒重建向量。
当前返回 Top-K 候选，不将相似度称为正确概率。笔记在回答中明确标为“个人笔记”，
不能充当原文证据。删除笔记不会追溯改写已保存的历史回答。

## 联网工具及执行过程

联网默认在每轮聊天中关闭。勾选“需要联网时询问我”只允许 Agent 提出授权请求，
不会立即联网；真正需要调用工具时，页面显示搜索服务和即将发送的搜索词，用户可以接受或拒绝。
拒绝、按 Esc 或 60 秒未确认时，本轮仅使用本地证据，不发送公开搜索请求。

快速流程：结合压缩后的近期历史确定问题 → 本地文档/笔记检索 →
必要时做一次证据充分性评估 → 用户授权 → 公开搜索 → 带来源回答。
期刊、会议、DOI、发表地点等明确的出版元数据问题，会从文档来源名构造书目查询，
跳过模型评估和二次本地检索。其他已判定需要联网的问题也不再重复模型评估。
证据评估最多读取 3 条、每条 600 字符的摘要；连续对话仅携带最近 6 条截断历史，
用于降低输入 Token 数和首段响应延迟。
如果未勾选联网，现阶段只按是否检索到片段控制一次本地重试，不进行额外的充分性模型评估。

默认使用无需密钥的 Crossref 学术元数据搜索，适用于查论文标题、DOI、出版载体、
会议/期刊信息；它不是覆盖所有网站的通用搜索，也不保证包含所有会议论文。
设置如下：

```dotenv
WEB_SEARCH_PROVIDER=crossref
WEB_SEARCH_TIMEOUT=20
```

需要通用网页搜索时配置：

```dotenv
WEB_SEARCH_PROVIDER=tavily
TAVILY_API_KEY=你的搜索服务密钥
```

修改后重启服务。联网只提交最长 500 字符的搜索查询，不直接上传整篇 PDF 或笔记；
查询可能含问题中的信息或从论文提取的标题，因此仅在你允许公开搜索时勾选。
服务器仍需可用的出站网络，Embedding 的离线设置不影响搜索或 MIMO。
API 密钥缺失、超时、网络失败都会在执行过程里提示并保留本地证据。

执行过程通过 SSE 逐阶段发送，并与最终回答一起保存：
上下文处理、检索结果数量、查询改写、公开搜索词、搜索结果 URL、引用编号检查。
这属于可核查的工具执行摘要，不展示或声称还原模型内部隐藏思维链。
最终答案通过 SSE token 事件逐段流式返回，并在完成引用检查后发送 result 事件。断线后服务器会继续完成已接受任务；
稍后重新打开会话查看结果，避免反复发送重复请求。
联网请求发出前会显示“正在联网搜索”及服务名称，完成或失败后显示结果数和耗时；
等待模型首段回答时也会持续显示当前阶段与累计等待秒数。
执行过程在每秒刷新时保留用户的展开/收起状态；回答完成后显示服务器记录的总用时，
并随聊天结果持久化，因此刷新页面后仍然可见。旧回答没有计时字段时不显示用时。
新回答同时汇总本轮所有 MIMO 调用的输入、输出和总 Token。Token 来自 API 返回的
usage，不使用字符数估算；如果兼容服务没有返回 usage，界面明确显示“Token 用量未返回”。

所有搜索记录都是候选，必须核对标题/作者/年份。Conference ’17 等占位模板不能当成
可靠出版信息。程序检查引用编号是否存在，并标记无效编号，但尚未自动完成事实蕴含验证。
论文、网页、笔记使用不同 kind 标签；网页返回 URL，文档返回页码和原文入口。
回答使用安全的 Markdown 子集渲染，包括标题、粗体、斜体、列表、引用、代码块和链接；
模型文本不会作为 HTML 直接注入页面。组合引用 `[来源 2, 6]`、`[来源 2.6]`、
`[来源 2，6]` 会统一解析，并在来源区域同时展示第 2 和第 6 条来源。
Crossref 来源以书目字段展示，不再显示原始 JSON；前端也会转换旧聊天记录中已保存的
Crossref JSON，因此无需修改历史数据库。

参考官方接口：
- [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)
- [Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search)

## 图谱

当前展示真实的“知识库 → 文档”结构；点击文档展开页码按钮，点击页码查看解析原文。
节点来自数据库，不凭模型生成关系。多于 100 页的文档可以直接输入页码。
这不是实体语义知识图谱，不声称论文 A 改进了论文 B，也不把向量相似视为因果关系。
实体/关系抽取和人工审核属于下一阶段。

## 主要接口

| 操作 | 接口 |
|---|---|
| 注册/登录/退出/当前账号 | /api/auth/register、login、logout、me |
| 知识库 CRUD | /api/knowledge-bases 与 /api/knowledge-bases/{kb} |
| 文档上传、列表、删除、重建 | /api/knowledge-bases/{kb}/documents… |
| 会话新建、列表、改名、删除 | /api/conversations 与 /api/conversations/{id} |
| 历史消息 | /api/conversations/{id}/messages |
| 普通聊天 / SSE | /api/chat、/api/chat/stream |
| 联网授权决定 | /api/chat/approvals/{approval_id} |
| 笔记保存、列表、语义搜索 | /api/knowledge-bases/{kb}/notes?query=… |
| 笔记删除 | /api/knowledge-bases/{kb}/notes/{note} |
| 文档结构图 | /api/knowledge-bases/{kb}/graph |
| 原文页面 | /api/knowledge-bases/{kb}/documents/{doc}/pages/{page} |

除了健康检查与注册/登录，所有 API 都需要登录 Cookie。
所有 POST/PATCH/DELETE 包括注册与登录需携带 X-ResearchMate: 1。
禁止从其他 Origin 跨域调用写接口，网页使用同源请求。

## 验证

```bash
python -m pytest -q
python -m pip install -e ".[browser]"
RUN_BROWSER_TESTS=1 python -m pytest tests/test_browser.py -q
```

浏览器测试使用服务器已有的 /opt/google/chrome/chrome，可按部署环境调整测试中的路径。
测试采用临时数据库、合成资料与假模型，不调用真实 MIMO。覆盖连续发送、
刷新恢复、笔记保存、原文查看与移动布局。持久化状态测试使用真正的 SQLite Saver，
关闭连接后重新构造图，再验证上下文恢复。
