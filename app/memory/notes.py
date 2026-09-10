"""Persistent E5 note vectors. Exact cosine search suits a small personal notebook."""
import json
import math
import uuid


class NoteMemory:
    def __init__(self, store, embeddings, model_key):
        self.store, self.embeddings, self.model_key = store, embeddings, model_key

    def save(self, kb, title, content):
        vector = self.embed_note(title,content)
        note = dict(id=uuid.uuid4().hex, title=title, content=content)
        with self.store.connect() as db:
            db.execute('INSERT INTO notes (id,knowledge_base_id,title,content) VALUES (?,?,?,?)',
                       (note['id'],kb,title,content))
            db.execute('INSERT INTO note_vectors VALUES (?,?,?)',
                       (note['id'],self.model_key,json.dumps(vector)))
        return note

    def search(self, query, kb, top_k=3):
        with self.store.connect() as db:
            rows = [dict(x) for x in db.execute('''SELECT n.*,v.vector,v.model_key
                FROM notes n LEFT JOIN note_vectors v ON n.id=v.note_id
                WHERE n.knowledge_base_id=?''',(kb,))]
        if not rows:
            return []
        q = self.embeddings.embed_query(query)
        scored = []
        for note in rows:
            if note['model_key'] != self.model_key:
                v = self.embed_note(note['title'],note['content'])
                with self.store.connect() as db:
                    db.execute('INSERT OR REPLACE INTO note_vectors VALUES (?,?,?)',
                               (note['id'],self.model_key,json.dumps(v)))
            else:
                v = json.loads(note['vector'])
            if len(q) != len(v):
                raise ValueError('笔记向量维度不匹配，请重建笔记索引')
            norm = math.sqrt(sum(x*x for x in q)*sum(x*x for x in v))
            score = sum(a*b for a,b in zip(q,v))/norm if norm else 0.0
            scored.append(dict(id=note['id'],title=note['title'],content=note['content'],score=score))
        return sorted(scored,key=lambda x:x['score'],reverse=True)[:top_k]

    def embed_note(self, title, content):
        # Cover the full note instead of silently discarding everything after the first page.
        chunks = [title+'\n'+content[start:start+700] for start in range(0,max(1,len(content)),600)]
        vectors = self.embeddings.embed_documents(chunks)
        return [sum(values)/len(vectors) for values in zip(*vectors)]

    def list(self, kb):
        with self.store.connect() as db:
            return [dict(x) for x in db.execute('SELECT id,title,content,created_at FROM notes WHERE knowledge_base_id=? ORDER BY created_at DESC',(kb,))]

    def delete(self, kb, note_id):
        with self.store.connect() as db:
            return db.execute('DELETE FROM notes WHERE id=? AND knowledge_base_id=?',(note_id,kb)).rowcount > 0
