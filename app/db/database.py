import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import get_settings

settings = get_settings()

sslmode = os.getenv("DB_SSL_MODE", "require")

# Use a default string for local development if auth is bypassed, but strictly use settings generally
DB_USER = settings.db_user or "postgres"
DB_PASS = settings.db_password or ""
DB_HOST = settings.db_host or "localhost"
DB_PORT = settings.db_port or "5432"
DB_NAME = settings.db_name or "postgres"

DB_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}?sslmode={sslmode}"

connect_args = {}
sslrootcert = os.getenv("DB_SSL_ROOT_CERT", "global-bundle.pem")
if os.path.exists(sslrootcert):
    connect_args["sslrootcert"] = sslrootcert

engine = create_engine(DB_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
