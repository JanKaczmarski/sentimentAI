"""Integration coverage for the bounded external supervisor demonstration."""

import os
from datetime import date
from pathlib import Path

import pytest

from sentiment_system.adapters.outbound.llm.local_llama import LocalLlamaLLMScorer
from sentiment_system.adapters.outbound.sources.demo_manifest import DemoManifestDocumentSource
from sentiment_system.domain.documents import DocumentChunk


@pytest.mark.integration
def test_supervisor_manifest_loads_the_bounded_sec_and_ir_demo() -> None:
    root = Path(os.getenv("SENTIMENT_DATA_ROOT", "../sentimentAI-data"))
    manifest = Path("demo/manifest.json")
    if not (root / "data").is_dir():
        pytest.skip("external supervisor-demo data repository is not available")

    documents = DemoManifestDocumentSource(root=root, manifest_path=manifest).fetch_documents(
        company="AMAT",
        published_before=date(2026, 5, 15),
    )

    assert len(documents) == 2
    assert {document.source for document in documents} == {"sec", "investor_relations"}
    assert {document.company for document in documents} == {"AMAT"}
    assert all(document.manifest_version == "supervisor-demo-v1" for document in documents)


@pytest.mark.integration
def test_configured_ollama_scores_one_real_demo_chunk() -> None:
    if os.getenv("RUN_REAL_LLM_TESTS") != "1":
        pytest.skip("set RUN_REAL_LLM_TESTS=1 to call the host-managed Ollama model")

    scorer = LocalLlamaLLMScorer(
        model_name=os.getenv("LLM_MODEL", "llama3.1:8b"),
        base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
        api_key=os.getenv("LLM_API_KEY", "ollama"),
    )
    result = scorer.score_chunk(
        DocumentChunk(
            chunk_id="supervisor-demo-test",
            document_id="supervisor-demo",
            ordinal=0,
            content="Applied Materials reported stronger demand and disciplined operating costs.",
        )
    )

    assert 0 <= result.sentiment.score <= 1
    assert 0 <= result.sentiment.confidence <= 1
    assert 0 <= result.importance_score <= 1
    assert result.raw_response
