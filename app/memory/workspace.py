"""User-owned workspaces and completed turns. Legacy data stays unassigned."""
import json
import secrets
import time
import uuid
from app.core.auth import hash_password, token_digest, verify_password
from app.memory.store import SQLiteStore


class WorkspaceStore(SQLiteStore):
    def initialize(self):
        super().initialize()
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id), expires REAL);
            CREATE TABLE IF NOT EXISTS login_attempts (username TEXT, attempted REAL);
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY, owner_id TEXT REFERENCES users(id) NOT NULL,
                knowledge_base_id TEXT REFERENCES knowledge_bases(id) ON DELETE CASCADE,
                title TEXT NOT NULL, updated REAL, busy_until REAL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS chat_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
                question TEXT, result TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS note_vectors (
                note_id TEXT PRIMARY KEY REFERENCES notes(id) ON DELETE CASCADE,
                model_key TEXT NOT NULL, vector TEXT NOT NULL);
            """)
            if 'owner_id' not in {x['name'] for x in db.execute('PRAGMA table_info(knowledge_bases)')}:
                db.execute('ALTER TABLE knowledge_bases ADD COLUMN owner_id TEXT REFERENCES users(id)')

    def register(self, username, password):
        user = dict(id=uuid.uuid4().hex, username=username.casefold())
        encoded = hash_password(password)
        with self.connect() as db:
            db.execute('INSERT INTO users VALUES (?,?,?)', (user['id'],user['username'],encoded))
        return user

    def login(self, username, password):
        name = username.casefold()
        with self.connect() as db:
            db.execute('DELETE FROM login_attempts WHERE attempted<?', (time.time()-300,))
            if db.execute('SELECT count(*) FROM login_attempts WHERE username=?',(name,)).fetchone()[0]>=10:
                raise ValueError('尝试次数过多，请五分钟后再试')
            db.execute('INSERT INTO login_attempts VALUES (?,?)',(name,time.time()))
            row = db.execute('SELECT * FROM users WHERE username=?',(name,)).fetchone()
        encoded = row['password_hash'] if row else hash_password('invalid-account')
        if not verify_password(password, encoded) or not row:
            return None
        with self.connect() as db:
            db.execute('DELETE FROM login_attempts WHERE username=?',(name,))
        return dict(id=row['id'],username=row['username'])

    def new_session(self, user_id):
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
            db.execute('INSERT INTO sessions VALUES (?,?,?)',(token_digest(token),user_id,time.time()+604800))
        return token

    def session_user(self, token):
        with self.connect() as db:
            row = db.execute('''SELECT u.id,u.username FROM users u JOIN sessions s ON u.id=s.user_id
                WHERE s.token_hash=? AND s.expires>?''',(token_digest(token),time.time())).fetchone()
        return dict(row) if row else None

    def logout(self, token):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?',(token_digest(token),))

    def create_owned_kb(self, name, owner):
        kb = dict(id=uuid.uuid4().hex,name=name)
        with self.connect() as db:
            db.execute('INSERT INTO knowledge_bases (id,name,owner_id) VALUES (?,?,?)',(kb['id'],name,owner))
        return kb

    def owned_kbs(self, owner):
        with self.connect() as db:
            return [dict(x) for x in db.execute('SELECT id,name FROM knowledge_bases WHERE owner_id=? ORDER BY created_at DESC',(owner,))]

    def require_kb(self, kb, owner):
        with self.connect() as db:
            row = db.execute('SELECT id,name FROM knowledge_bases WHERE id=? AND owner_id=?',(kb,owner)).fetchone()
        if not row:
            raise KeyError('知识库不存在或无权访问')
        return dict(row)

    def new_conversation(self, owner, kb, title):
        self.require_kb(kb,owner)
        item = dict(id=uuid.uuid4().hex,knowledge_base_id=kb,title=title)
        with self.connect() as db:
            db.execute('INSERT INTO conversations (id,owner_id,knowledge_base_id,title,updated) VALUES (?,?,?,?,?)',
                       (item['id'],owner,kb,title,time.time()))
        return item

    def conversations(self, owner):
        with self.connect() as db:
            return [dict(x) for x in db.execute('SELECT id,knowledge_base_id,title,updated FROM conversations WHERE owner_id=? ORDER BY updated DESC',(owner,))]

    def require_conversation(self, thread, owner):
        with self.connect() as db:
            row = db.execute('SELECT * FROM conversations WHERE id=? AND owner_id=?',(thread,owner)).fetchone()
        if not row:
            raise KeyError('会话不存在或无权访问')
        self.require_kb(row['knowledge_base_id'],owner)
        return dict(row)

    def acquire(self, thread, owner):
        self.require_conversation(thread,owner)
        with self.connect() as db:
            return db.execute('UPDATE conversations SET busy_until=? WHERE id=? AND owner_id=? AND busy_until<?',
                              (time.time()+900,thread,owner,time.time())).rowcount==1

    def release(self, thread):
        with self.connect() as db:
            db.execute('UPDATE conversations SET busy_until=0 WHERE id=?',(thread,))

    def reset_processing(self):
        """Clear locks left by a previous process after a server restart."""
        with self.connect() as db:
            db.execute('UPDATE conversations SET busy_until=0')

    def record_turn(self, thread, question, result):
        with self.connect() as db:
            db.execute('INSERT INTO chat_turns (conversation_id,question,result,created) VALUES (?,?,?,?)',
                       (thread,question,json.dumps(result,ensure_ascii=False),time.time()))
            db.execute("UPDATE conversations SET updated=?,title=CASE WHEN title='新会话' THEN ? ELSE title END WHERE id=?",
                       (time.time(),question[:40],thread))

    def history(self, thread):
        with self.connect() as db:
            rows = db.execute('SELECT question,result FROM chat_turns WHERE conversation_id=? ORDER BY id',(thread,)).fetchall()
        messages = []
        for row in rows:
            result = json.loads(row['result'])
            messages.extend([dict(role='user',content=row['question']),dict(role='assistant',content=result['answer'],**result)])
        return messages

    def rename_conversation(self, thread, title):
        with self.connect() as db:
            db.execute('UPDATE conversations SET title=? WHERE id=?',(title,thread))

    def remove_conversation(self, thread):
        with self.connect() as db:
            db.execute('DELETE FROM conversations WHERE id=?',(thread,))

    def claim_legacy(self, username):
        """Local administrator command only; not exposed by the HTTP API."""
        with self.connect() as db:
            row = db.execute('SELECT id FROM users WHERE username=?',(username.casefold(),)).fetchone()
            if not row:
                raise ValueError('请先在网页注册此账号')
            return db.execute('UPDATE knowledge_bases SET owner_id=? WHERE owner_id IS NULL',(row['id'],)).rowcount
