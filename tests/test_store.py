from pathlib import Path

from app.memory.store import SQLiteStore


def test_sqlite_store_round_trip(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "researchmate.sqlite3")
    kb = store.create_knowledge_base("DTI papers")

    assert store.knowledge_base_exists(kb["id"])
    assert store.list_knowledge_bases()[0]["name"] == "DTI papers"

    store.add_document(
        document_id="doc-1",
        knowledge_base_id=kb["id"],
        filename="paper.pdf",
        file_path="/tmp/paper.pdf",
        page_count=9,
        chunk_count=30,
    )
    assert store.list_documents(kb["id"])[0]["chunk_count"] == 30

    store.add_message("thread-1", "user", "question")
    store.add_message("thread-1", "assistant", "answer")
    assert [x["role"] for x in store.get_messages("thread-1")] == [
        "user",
        "assistant",
    ]

    note = store.save_note(kb["id"], "method", "multilevel attention")
    assert note["title"] == "method"
    assert store.search_notes(kb["id"], "attention")[0]["id"] == note["id"]

    second_kb = store.create_knowledge_base("Second library")
    store.add_document(
        document_id="doc-1",
        knowledge_base_id=second_kb["id"],
        filename="paper.pdf",
        file_path="/tmp/second-paper.pdf",
        page_count=9,
        chunk_count=30,
    )
    assert store.get_document(kb["id"], "doc-1") is not None
    assert store.get_document(second_kb["id"], "doc-1") is not None
    assert store.delete_document(second_kb["id"], "doc-1")
    assert store.get_document(second_kb["id"], "doc-1") is None
    assert store.delete_knowledge_base(second_kb["id"])
