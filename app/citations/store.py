"""SQLite persistence for paper entities and directed citation relations."""

from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _identity(reference: dict) -> str:
    doi = reference.get("doi", "").strip().casefold()
    if doi:
        return "doi:" + doi
    title = re.sub(r"\W+", "", reference.get("title", "").casefold())
    basis = title + ":" + str(reference.get("year") or "")
    if len(title) < 8:
        basis = reference.get("raw_reference", "").casefold()
    return "local:" + sha256(basis.encode()).hexdigest()


class CitationStore:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.initialize()

    def connect(self):
        db = sqlite3.connect(self.database_path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def initialize(self) -> None:
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS papers (
                    id TEXT PRIMARY KEY, knowledge_base_id TEXT NOT NULL,
                    identity_key TEXT NOT NULL, document_id TEXT,
                    role TEXT NOT NULL, title TEXT NOT NULL, abstract TEXT NOT NULL DEFAULT '',
                    authors_json TEXT NOT NULL DEFAULT '[]', venue TEXT NOT NULL DEFAULT '',
                    publication_date TEXT NOT NULL DEFAULT '', year INTEGER,
                    doi TEXT NOT NULL DEFAULT '', metadata_provider TEXT NOT NULL DEFAULT 'local',
                    match_status TEXT NOT NULL DEFAULT 'local_only', match_score REAL,
                    needs_enrichment INTEGER NOT NULL DEFAULT 1,
                    raw_reference TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(knowledge_base_id, identity_key)
                );
                CREATE INDEX IF NOT EXISTS idx_papers_kb ON papers(knowledge_base_id);
                CREATE INDEX IF NOT EXISTS idx_papers_doc ON papers(knowledge_base_id, document_id);
                CREATE TABLE IF NOT EXISTS citation_edges (
                    id TEXT PRIMARY KEY, knowledge_base_id TEXT NOT NULL,
                    citing_paper_id TEXT NOT NULL, cited_paper_id TEXT NOT NULL,
                    reference_number INTEGER, raw_reference TEXT NOT NULL,
                    extraction_page INTEGER NOT NULL, extraction_method TEXT NOT NULL,
                    match_score REAL, verification_status TEXT NOT NULL DEFAULT 'unverified',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_edges_kb ON citation_edges(knowledge_base_id);
                CREATE INDEX IF NOT EXISTS idx_edges_citing ON citation_edges(citing_paper_id);
            """)
            columns={row[1] for row in db.execute("PRAGMA table_info(papers)")}
            if "match_score" not in columns:
                db.execute("ALTER TABLE papers ADD COLUMN match_score REAL")
            if "needs_enrichment" not in columns:
                db.execute("ALTER TABLE papers ADD COLUMN needs_enrichment INTEGER NOT NULL DEFAULT 1")

    def replace_document(self, kb: str, document_id: str, filename: str,
                         references: list[dict]) -> dict:
        core_id = "paper_" + sha256(f"{kb}:uploaded:{document_id}".encode()).hexdigest()[:24]
        now = _now()
        with self.connect() as db:
            db.execute("""INSERT INTO papers
                (id,knowledge_base_id,identity_key,document_id,role,title,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(knowledge_base_id,identity_key)
                DO UPDATE SET title=excluded.title,document_id=excluded.document_id,
                              role='uploaded',updated_at=excluded.updated_at""",
                (core_id,kb,"uploaded:"+document_id,document_id,"uploaded",filename,now,now))
            db.execute("DELETE FROM citation_edges WHERE citing_paper_id=?",(core_id,))
            for position, ref in enumerate(references, 1):
                identity = _identity(ref)
                cited_id = "paper_" + sha256(f"{kb}:{identity}".encode()).hexdigest()[:24]
                label = ref.get("title") or ref.get("raw_reference", "")[:160] or "未解析引用"
                db.execute("""INSERT INTO papers
                    (id,knowledge_base_id,identity_key,role,title,year,doi,raw_reference,
                     authors_json,venue,metadata_provider,match_status,needs_enrichment,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(knowledge_base_id,identity_key) DO UPDATE SET
                      title=CASE WHEN papers.match_status IN ('matched','doi_exact') THEN papers.title ELSE excluded.title END,
                      authors_json=CASE WHEN papers.match_status IN ('matched','doi_exact') THEN papers.authors_json ELSE excluded.authors_json END,
                      venue=CASE WHEN papers.match_status IN ('matched','doi_exact') THEN papers.venue ELSE excluded.venue END,
                      match_status=CASE WHEN papers.match_status IN ('matched','doi_exact') THEN papers.match_status ELSE excluded.match_status END,
                      needs_enrichment=CASE WHEN papers.match_status IN ('matched','doi_exact') THEN 0 ELSE excluded.needs_enrichment END,
                      raw_reference=excluded.raw_reference,updated_at=excluded.updated_at""",
                    (cited_id,kb,identity,"cited",label,ref.get("year"),ref.get("doi", ""),
                     ref.get("raw_reference", ""),json.dumps(ref.get("authors",[]),ensure_ascii=False),
                     ref.get("venue",""),"local",
                     "local_only" if ref.get("needs_enrichment",True) else "local_extracted",
                     int(ref.get("needs_enrichment",True)),now,now))
                edge_basis = f"{core_id}:{ref.get('reference_number')}:{position}:{cited_id}"
                edge_id = "cite_" + sha256(edge_basis.encode()).hexdigest()[:24]
                db.execute("""INSERT INTO citation_edges
                    (id,knowledge_base_id,citing_paper_id,cited_paper_id,reference_number,
                     raw_reference,extraction_page,extraction_method,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (edge_id,kb,core_id,cited_id,ref.get("reference_number"),
                     ref.get("raw_reference", ""),ref.get("page",1),
                     ref.get("extraction_method","local"),now))
            self._delete_orphans(db,kb)
        return {"paper_id":core_id,"citation_count":len(references)}

    @staticmethod
    def _delete_orphans(db, kb: str) -> None:
        db.execute("""DELETE FROM papers WHERE knowledge_base_id=? AND role='cited'
          AND id NOT IN (SELECT cited_paper_id FROM citation_edges WHERE knowledge_base_id=?)""",(kb,kb))

    def graph(self, kb: str) -> dict:
        with self.connect() as db:
            papers = [dict(row) for row in db.execute(
                "SELECT * FROM papers WHERE knowledge_base_id=? ORDER BY role,title",(kb,))]
            edges = [dict(row) for row in db.execute(
                "SELECT * FROM citation_edges WHERE knowledge_base_id=? ORDER BY citing_paper_id,reference_number",(kb,))]
        for paper in papers:
            paper["authors"] = json.loads(paper.pop("authors_json"))
        return {"papers":papers,"edges":edges}

    def candidates(self, kb: str, limit: int = 100) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("""SELECT * FROM papers WHERE knowledge_base_id=?
                AND role='cited' AND match_status NOT IN ('doi_exact','matched')
                AND needs_enrichment=1
                ORDER BY updated_at LIMIT ?""",(kb,limit)).fetchall()
        return [dict(row) for row in rows]

    def update_metadata(self, paper_id: str, metadata: dict) -> None:
        with self.connect() as db:
            db.execute("""UPDATE papers SET title=?,abstract=?,authors_json=?,venue=?,
                publication_date=?,year=?,doi=?,metadata_provider=?,match_status=?,match_score=?,needs_enrichment=0,updated_at=?
                WHERE id=?""",(
                metadata.get("title", ""),metadata.get("abstract", ""),
                json.dumps(metadata.get("authors", []),ensure_ascii=False),metadata.get("venue", ""),
                metadata.get("publication_date", ""),metadata.get("year"),metadata.get("doi", ""),
                metadata.get("metadata_provider", "crossref"),metadata.get("match_status", "matched"),
                metadata.get("match_score"),_now(),paper_id,
            ))
            db.execute("""UPDATE citation_edges SET match_score=?,verification_status=?
                WHERE cited_paper_id=?""",(metadata.get("match_score"),
                "doi_exact" if metadata.get("match_status")=="doi_exact" else "automatic_match",
                paper_id))

    def delete_document(self, kb: str, document_id: str) -> list[str]:
        with self.connect() as db:
            row = db.execute("SELECT id FROM papers WHERE knowledge_base_id=? AND document_id=?",
                             (kb,document_id)).fetchone()
            if not row:
                return []
            before = {x[0] for x in db.execute(
                "SELECT cited_paper_id FROM citation_edges WHERE citing_paper_id=?",(row["id"],))}
            db.execute("DELETE FROM citation_edges WHERE citing_paper_id=?",(row["id"],))
            db.execute("DELETE FROM papers WHERE id=?",(row["id"],))
            self._delete_orphans(db,kb)
            remaining = {x[0] for x in db.execute("SELECT id FROM papers WHERE knowledge_base_id=?",(kb,))}
        return sorted(before-remaining)

    def delete_kb(self, kb: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM citation_edges WHERE knowledge_base_id=?",(kb,))
            db.execute("DELETE FROM papers WHERE knowledge_base_id=?",(kb,))
