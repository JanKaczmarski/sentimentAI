"""Port contract coverage for the real supervisor-demo adapters."""

from types import SimpleNamespace

from sentiment_system.adapters.outbound.embeddings.ollama import OllamaEmbeddingProvider
from sentiment_system.adapters.outbound.llm.local_llama import LocalLlamaLLMScorer
from sentiment_system.adapters.outbound.sources.demo_manifest import DemoManifestDocumentSource
from sentiment_system.application.ports.document_sources import DocumentSource
from sentiment_system.application.ports.embeddings import EmbeddingProvider
from sentiment_system.application.ports.llm import LLMScorer


def test_supervisor_adapters_implement_the_application_ports(tmp_path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        '{"manifest_version":"v1","cutoff_date":"2025-01-01","records":['
        '{"document_id":"d","source_id":"s","company":"AAPL",'
        '"source":"sec","published_at":"2025-01-01","document_type":"8-K",'
        '"raw_path":"source.txt","raw_sha256":"'
        '2a97516c354b68848cdbd8f54a226a0a55b21ed138e207ad6c5cbb9c00aa5aea",'
        '"cleaned_content_version":"processing-v2"}]}',
        encoding="utf-8",
    )
    (tmp_path / "source.txt").write_text("demo", encoding="utf-8")

    source = DemoManifestDocumentSource(root=tmp_path, manifest_path=manifest_path)
    scorer = LocalLlamaLLMScorer(
        model_name="llama3.1:8b",
        base_url="http://localhost:11434/v1",
        api_key="ollama",
        client=SimpleNamespace(),
    )
    embeddings = OllamaEmbeddingProvider(
        model_name="nomic-embed-text",
        base_url="http://localhost:11434/v1",
        api_key="ollama",
        client=SimpleNamespace(),
    )

    assert isinstance(source, DocumentSource)
    assert isinstance(scorer, LLMScorer)
    assert isinstance(embeddings, EmbeddingProvider)
