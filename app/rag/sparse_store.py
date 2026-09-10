"""Persistent Okapi BM25 retrieval and rank fusion for small deployments."""

from collections import Counter
import json
import math
from pathlib import Path
import re
import sqlite3
import unicodedata

from langchain_core.documents import Document


def tokenize(text: str) -> list[str]:
    """Tokenize English identifiers and Chinese character unigrams/bigrams."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    words = re.findall(r"[a-z0-9]+", normalized)
    identifiers = re.findall(r"[a-z0-9]+(?:[._/-][a-z0-9]+)+", normalized)
    chinese = []
    for sequence in re.findall(r"[\u3400-\u9fff]+", normalized):
        chinese.extend(sequence)
        chinese.extend(sequence[index:index + 2] for index in range(len(sequence) - 1))
    return words + identifiers + chinese


class SparseBM25Store:
    """SQLite-backed chunk corpus scored with the Okapi BM25 formula."""

    def __init__(self, database_path: str | Path, *, k1: float = 1.5,
                 b: float = 0.75) -> None:
        self.database_path = Path(database_path)
        self.k1 = k1
        self.b = b
        self.initialize()

    def connect(self):
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sparse_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    knowledge_base_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    page INTEGER NOT NULL,
                    tokens TEXT NOT NULL,
                    token_count INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sparse_chunks_kb
                    ON sparse_chunks(knowledge_base_id);
                CREATE INDEX IF NOT EXISTS idx_sparse_chunks_document
                    ON sparse_chunks(knowledge_base_id, document_id);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(sparse_chunks)")}
            if "metadata_json" not in columns:
                db.execute("ALTER TABLE sparse_chunks ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")

    def replace_document(self, knowledge_base_id: str, document_id: str,
                         documents: list[Document]) -> None:
        rows = []
        for document in documents:
            terms = tokenize(document.page_content)
            rows.append((
                str(document.metadata["chunk_id"]), knowledge_base_id,
                document_id, document.page_content,
                str(document.metadata["source"]), int(document.metadata["page"]),
                json.dumps(terms,ensure_ascii=False), len(terms),
                json.dumps(document.metadata,ensure_ascii=False),
            ))
        with self.connect() as db:
            db.execute(
                "DELETE FROM sparse_chunks WHERE knowledge_base_id=? AND document_id=?",
                (knowledge_base_id,document_id),
            )
            db.executemany("""
                INSERT INTO sparse_chunks
                    (chunk_id,knowledge_base_id,document_id,content,source,page,tokens,token_count,metadata_json)
                VALUES (?,?,?,?,?,?,?,?,?)
            """,rows)

    def delete_document(self, knowledge_base_id: str, document_id: str) -> None:
        with self.connect() as db:
            db.execute(
                "DELETE FROM sparse_chunks WHERE knowledge_base_id=? AND document_id=?",
                (knowledge_base_id,document_id),
            )

    def delete_knowledge_base(self, knowledge_base_id: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM sparse_chunks WHERE knowledge_base_id=?",
                       (knowledge_base_id,))

    def search(self, query: str, knowledge_base_id: str,
               top_k: int) -> list[tuple[Document,float]]:
        query_terms = tokenize(query)
        if not query_terms:
            return []
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM sparse_chunks WHERE knowledge_base_id=?",
                (knowledge_base_id,),
            ).fetchall()
        if not rows:
            return []
        documents = [(row,Counter(json.loads(row["tokens"]))) for row in rows]
        document_count = len(documents)
        average_length = sum(row["token_count"] for row,_ in documents) / document_count
        document_frequency = Counter()
        for _,frequencies in documents:
            document_frequency.update(frequencies.keys())
        scores = []
        for row,frequencies in documents:
            score = 0.0
            length = row["token_count"]
            for term in query_terms:
                frequency = frequencies.get(term,0)
                if not frequency:
                    continue
                df = document_frequency[term]
                inverse_frequency = math.log(1 + (document_count-df+0.5)/(df+0.5))
                denominator = frequency + self.k1*(1-self.b+self.b*length/average_length)
                score += inverse_frequency * frequency*(self.k1+1)/denominator
            if score>0:
                metadata = json.loads(row["metadata_json"] or "{}")
                metadata.update({
                    "chunk_id":row["chunk_id"],
                    "document_id":row["document_id"],
                    "knowledge_base_id":row["knowledge_base_id"],
                    "source":row["source"],
                    "page":row["page"],
                })
                document = Document(page_content=row["content"],metadata=metadata)
                scores.append((document,score))
        return sorted(scores,key=lambda item:item[1],reverse=True)[:top_k]


def reciprocal_rank_fusion(
    dense: list[tuple[Document,float]],
    sparse: list[tuple[Document,float]],
    *,
    top_k: int,
    rank_constant: int = 60,
) -> list[tuple[Document,float]]:
    """Fuse ranked lists without assuming their raw scores are comparable."""
    if not sparse:
        return dense[:top_k]
    if not dense:
        return sparse[:top_k]
    fused: dict[str,dict] = {}
    for channel,results in (("dense",dense),("sparse",sparse)):
        for rank,(document,raw_score) in enumerate(results,1):
            chunk_id = str(document.metadata["chunk_id"])
            item = fused.setdefault(chunk_id,{
                "document":document,"score":0.0,"channels":[],"raw":{},
            })
            item["score"] += 1/(rank_constant+rank)
            item["channels"].append(channel)
            item["raw"][channel] = float(raw_score)
    ordered = sorted(fused.values(),key=lambda item:item["score"],reverse=True)
    output = []
    for item in ordered[:top_k]:
        document = Document(page_content=item["document"].page_content,
                            metadata=dict(item["document"].metadata))
        document.metadata["retrieval_channels"] = item["channels"]
        document.metadata["retrieval_scores"] = item["raw"]
        output.append((document,item["score"]))
    return output
