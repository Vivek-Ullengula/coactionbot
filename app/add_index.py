import psycopg2
from app.config import get_settings

def add_index():
    s = get_settings()
    conn = psycopg2.connect(
        host=s.db_host,
        database=s.db_name,
        user=s.db_user,
        password=s.db_password,
        port=s.db_port,
        sslmode='verify-full',
        sslrootcert='global-bundle.pem'
    )
    cur = conn.cursor()
    print("Adding GIN index...")
    cur.execute("CREATE INDEX IF NOT EXISTS coaction_chunks_content_idx ON coaction_chunks USING gin (to_tsvector('english', content));")
    
    print("Adding HNSW index...")
    cur.execute("CREATE INDEX IF NOT EXISTS coaction_chunks_embedding_idx ON coaction_chunks USING hnsw (embedding vector_cosine_ops);")
    
    conn.commit()
    conn.close()
    print("✅ Full-Text Search index added successfully!")

if __name__ == "__main__":
    add_index()
