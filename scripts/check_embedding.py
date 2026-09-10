"""Check the the local embedding model works correctly."""

import numpy as np
from sentence_transformers import SentenceTransformer

from app.core.config import get_settings


def main() -> None:
    settings = get_settings()

    model = SentenceTransformer(
        settings.embedding_model,
        revision=settings.embedding_model_revision,
        device=settings.embedding_device,
        local_files_only=settings.embedding_offline,
    )

    query = ["query: 什么是检索增强生成？"]

    passages = [
        (
            "passage: 检索增强生成先从外部知识库检索相关证据，"
            "再让大语言模型依据证据生成回答。"
        ),
        (
            "passage: 光合作用是植物将光能转化为化学能的过程。"
        ),
    ]

    query_vectors = model.encode(
        query,
        normalize_embeddings=True,
    )
    passage_vectors = model.encode(
        passages,
        normalize_embeddings=True,
    )

    scores = np.matmul(query_vectors, passage_vectors.T)

    print(f"运行设备：{settings.embedding_device}")
    print(f"查询向量形状：{query_vectors.shape}")
    print(f"文档向量形状：{passage_vectors.shape}")
    print(f"相关文档得分：{scores[0, 0]:.4f}")
    print(f"无关文档得分：{scores[0, 1]:.4f}")

    assert query_vectors.shape == (1, 384)
    assert passage_vectors.shape == (2, 384)
    assert scores[0, 0] > scores[0, 1]

    print("Embedding 模型验证成功")


if __name__ == "__main__":
    main()