# ResearchMate Agent

## 项目目录结构

```text
agent_paper/
├── app/
│   ├── api/          # FastAPI 接口
│   ├── agent/        # LangGraph 和 Agent 工作流
│   ├── rag/          # 文档解析、切分、检索和重排序
│   ├── memory/       # 长短期记忆
│   └── core/         # 配置、日志和异常处理
├── tests/            # 自动化测试
├── data/             # 上传文件、数据库和向量索引
├── .env              # 真实配置，不提交
├── .env.example      # 配置模板，可以提交
├── .gitignore
├── pyproject.toml    # 项目元数据和依赖
├── README.md
└── 项目书.md
```
