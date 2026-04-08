"""
Vector store — Qdrant in-memory wrapper for POC.

Uses qdrant-client's in-memory mode (no Docker needed).
In production, switch to a persistent Qdrant instance.
"""

import logging
from uuid import uuid4

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from poc.config import EMBEDDING_DIM, QDRANT_COLLECTION_NAME
from poc.models import DocumentChunk
from poc.processing import embed_texts

logger = logging.getLogger(__name__)


class VectorStore:
    def __init__(self):
        # In-memory Qdrant — no server needed
        self.client = QdrantClient(":memory:")
        self.collection_name = QDRANT_COLLECTION_NAME
        self._ensure_collection()

    def _ensure_collection(self):
        collections = [c.name for c in self.client.get_collections().collections]
        if self.collection_name not in collections:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=EMBEDDING_DIM,
                    distance=Distance.COSINE,
                ),
            )
            logger.info(f"Created Qdrant collection: {self.collection_name}")

    def index_chunks(self, chunks: list[DocumentChunk]) -> int:
        """Embed and index a list of document chunks. Returns number indexed."""
        if not chunks:
            return 0

        texts = [c.content for c in chunks]
        embeddings = embed_texts(texts)

        points = [
            PointStruct(
                id=str(uuid4()),
                vector=embedding,
                payload={
                    "chunk_id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "company_ticker": chunk.company_ticker,
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content,
                    "filing_date": chunk.filing_date.isoformat() if chunk.filing_date else None,
                },
            )
            for chunk, embedding in zip(chunks, embeddings)
        ]

        self.client.upsert(
            collection_name=self.collection_name,
            points=points,
        )

        logger.info(f"Indexed {len(points)} chunks for {chunks[0].company_ticker}")
        return len(points)

    def search(
        self,
        query_text: str,
        ticker: str | None = None,
        top_k: int = 5,
    ) -> list[dict]:
        """Semantic search for relevant chunks.

        Returns list of dicts with keys: chunk_id, content, score, filing_date, etc.
        """
        query_embedding = embed_texts([query_text])[0]

        query_filter = None
        if ticker:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="company_ticker",
                        match=MatchValue(value=ticker),
                    )
                ]
            )

        results = self.client.query_points(
            collection_name=self.collection_name,
            query=query_embedding,
            query_filter=query_filter,
            limit=top_k,
        )

        return [
            {
                "chunk_id": hit.payload["chunk_id"],
                "content": hit.payload["content"],
                "score": hit.score,
                "filing_date": hit.payload.get("filing_date"),
                "doc_id": hit.payload.get("doc_id"),
                "company_ticker": hit.payload.get("company_ticker"),
            }
            for hit in results.points
        ]

    def get_collection_info(self) -> dict:
        """Get basic stats about the collection."""
        info = self.client.get_collection(self.collection_name)
        return {
            "name": self.collection_name,
            "points_count": info.points_count,
        }
