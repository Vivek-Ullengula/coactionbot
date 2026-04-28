from pydantic import BaseModel, HttpUrl, Field
from typing import Optional
from enum import Enum


class CrawlStatus(str, Enum):
    PENDING = "pending"
    CRAWLING = "crawling"
    INDEXING = "indexing"
    DONE = "done"
    FAILED = "failed"


class CrawlRequest(BaseModel):
    url: HttpUrl
    max_depth: Optional[int] = Field(default=None, ge=1, le=5)
    max_pages: Optional[int] = Field(default=None, ge=1, le=200)


class CrawlResponse(BaseModel):
    job_id: str
    status: CrawlStatus
    url: str
    pages_crawled: int = 0
    chunks_indexed: int = 0
    message: str = ""


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    session_id: Optional[str] = Field(default=None, description="Optional session ID for multi-turn conversations")


class QueryResponse(BaseModel):
    query: str
    answer: str
    sources: list[str] = []
    session_id: str = Field(..., description="Session ID for the conversation")
    follow_up_questions: list[str] = Field(default=[], description="Suggested follow-up questions based on the conversation")
