"""Persistent Qdrant adapter for chunk embeddings and retrieval."""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient, models

from sentiment_system.application.ports.vector_store import EmbeddedChunk, VectorMatch, VectorQuery
from sentiment_system.domain.documents import DocumentChunk


class QdrantVectorStore:
    """Persist embedded chunks in a cosine-distance Qdrant collection."""

    def __init__(
        self,
        *,
        collection_name: str = "sentiment_chunks",
        url: str | None = None,
        client: QdrantClient | None = None,
    ) -> None:
        if not collection_name.strip():
            raise ValueError("collection_name is required")
        if client is None and not url:
            raise ValueError("url or client is required")
        self._client = client or QdrantClient(url=url)
        self._collection_name = collection_name

    def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None:
        """Insert or replace points while retaining all retrieval metadata."""
        if not chunks:
            return
        dimension = len(chunks[0].embedding)
        if any(len(chunk.embedding) != dimension for chunk in chunks):
            raise ValueError("all embeddings must have the same dimension")
        self._ensure_collection(dimension)
        points = [
            models.PointStruct(
                id=str(uuid5(NAMESPACE_URL, f"sentiment-system/chunk/{embedded.chunk.chunk_id}")),
                vector=list(embedded.embedding),
                payload=_payload(embedded),
            )
            for embedded in chunks
        ]
        self._client.upsert(collection_name=self._collection_name, points=points, wait=True)

    def search(self, query: VectorQuery) -> tuple[VectorMatch, ...]:
        """Search with company, as-of, and soft-exclusion filters applied server-side."""
        self._ensure_collection(len(query.embedding))
        response = self._client.query_points(
            collection_name=self._collection_name,
            query=list(query.embedding),
            query_filter=_query_filter(query),
            limit=query.limit,
            with_payload=True,
        )
        return tuple(_match_from_point(point) for point in response.points)

    def _ensure_collection(self, dimension: int) -> None:
        if not self._client.collection_exists(self._collection_name):
            self._client.create_collection(
                collection_name=self._collection_name,
                vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE),
            )
            return
        collection = self._client.get_collection(self._collection_name)
        configured_vectors = collection.config.params.vectors
        configured_dimension = getattr(configured_vectors, "size", None)
        if configured_dimension != dimension:
            raise ValueError("query or point embedding has a different dimension than the collection")


def _payload(embedded: EmbeddedChunk) -> dict[str, Any]:
    return {
        "chunk_id": embedded.chunk.chunk_id,
        "document_id": embedded.chunk.document_id,
        "ordinal": embedded.chunk.ordinal,
        "content": embedded.chunk.content,
        "processing_config_version": embedded.chunk.processing_config_version,
        "company": embedded.company,
        "published_at": embedded.published_at.isoformat(),
        "published_at_ordinal": embedded.published_at.toordinal(),
        "excluded": embedded.excluded,
    }


def _query_filter(query: VectorQuery) -> models.Filter | None:
    conditions: list[models.FieldCondition | models.Filter] = []
    if query.company is not None:
        conditions.append(models.FieldCondition(key="company", match=models.MatchValue(value=query.company)))
    if query.as_of is not None:
        conditions.append(
            models.FieldCondition(
                key="published_at_ordinal",
                range=models.Range(lte=query.as_of.toordinal()),
            )
        )
    if not query.include_excluded:
        conditions.append(models.FieldCondition(key="excluded", match=models.MatchValue(value=False)))
    return models.Filter(must=cast(Any, conditions)) if conditions else None


def _match_from_point(point: Any) -> VectorMatch:
    payload = point.payload
    if not isinstance(payload, Mapping):
        raise ValueError("Qdrant point is missing its chunk payload")
    return VectorMatch(
        chunk=DocumentChunk(
            chunk_id=_payload_string(payload, "chunk_id"),
            document_id=_payload_string(payload, "document_id"),
            ordinal=_payload_int(payload, "ordinal"),
            content=_payload_string(payload, "content"),
            processing_config_version=_payload_string(payload, "processing_config_version"),
        ),
        company=_payload_string(payload, "company"),
        published_at=date.fromisoformat(_payload_string(payload, "published_at")),
        score=float(point.score),
        excluded=_payload_bool(payload, "excluded"),
    )


def _payload_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Qdrant payload field {key} must be a string")
    return value


def _payload_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Qdrant payload field {key} must be an integer")
    return value


def _payload_bool(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"Qdrant payload field {key} must be a boolean")
    return value
