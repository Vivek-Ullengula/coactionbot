from sqlalchemy import Column, BigInteger, String, DateTime, JSON, Text
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func
from datetime import datetime

Base = declarative_base()

class DBUser(Base):
    __tablename__ = "app_users"
    
    id = Column(BigInteger, primary_key=True, index=True)
    name = Column(Text, nullable=False)
    email = Column(Text, unique=True, nullable=False)
    role = Column(Text, nullable=False)
    password_hash = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class DBChatSession(Base):
    __tablename__ = "app_chat_sessions"
    
    session_id = Column(String, primary_key=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_accessed = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    messages = Column(JSON, default=list)
    metadata_ = Column("metadata", JSON, default=dict)
