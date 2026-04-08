"""
Data models for the Sentiment Analysis POC.
"""

from datetime import date, datetime
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# --- Enums ---

class RiskTolerance(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class InvestmentHorizon(str, Enum):
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"


class InvestmentStyle(str, Enum):
    PASSIVE = "passive"
    ACTIVE = "active"


class Sentiment(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"


class ComputationType(str, Enum):
    BATCH = "batch"
    AD_HOC = "ad_hoc"


# --- User Profile ---

class UserProfileCreate(BaseModel):
    name: str
    risk_tolerance: RiskTolerance = RiskTolerance.MEDIUM
    investment_horizon: InvestmentHorizon = InvestmentHorizon.LONG_TERM
    investment_style: InvestmentStyle = InvestmentStyle.PASSIVE
    watchlist: list[str] = Field(default_factory=list, description="List of tickers, e.g. ['NVDA', 'AAPL']")


class UserProfile(UserProfileCreate):
    user_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)


# --- Document ---

class Document(BaseModel):
    doc_id: str = Field(default_factory=lambda: str(uuid4()))
    company_ticker: str
    filename: str
    filing_date: Optional[date] = None
    doc_type: str = ""  # e.g. "8-K", "10-K"
    raw_content: str
    ingested_at: datetime = Field(default_factory=datetime.utcnow)


class DocumentChunk(BaseModel):
    chunk_id: str = Field(default_factory=lambda: str(uuid4()))
    doc_id: str
    company_ticker: str
    chunk_index: int
    content: str
    filing_date: Optional[date] = None


# --- Sentiment Result ---

class SentimentResult(BaseModel):
    result_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    company_ticker: str
    sentiment: Sentiment
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    source_chunks: list[str] = Field(default_factory=list, description="chunk_ids used")
    computation_type: ComputationType = ComputationType.BATCH
    batch_date: date = Field(default_factory=date.today)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# --- Batch Run ---

class BatchRun(BaseModel):
    batch_id: str = Field(default_factory=lambda: str(uuid4()))
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    tickers_processed: int = 0
    users_processed: int = 0
    results_generated: int = 0
    status: str = "running"  # running | completed | failed
