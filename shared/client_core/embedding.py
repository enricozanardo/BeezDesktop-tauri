"""Client-side embedding generation using fastembed.

Provides lightweight, ONNX-based embedding generation for RAG indexing and
query embedding. Both the client and the smart node use the same model name
constant to guarantee vector compatibility.

Usage:
    from shared.client_core.embedding import EmbeddingEngine

    engine = EmbeddingEngine()
    vectors = engine.embed_texts(["Hello world", "Another sentence"])
    query_vec = engine.embed_query("What is this about?")
"""

from typing import List, Optional
import numpy as np

# Canonical model name -- must match between client and smart node
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"  # 384-dim, ONNX, ~33MB
VECTOR_DIM = 384


class EmbeddingEngine:
    """Lightweight embedding engine backed by fastembed (ONNX runtime).

    The model is lazily loaded on first use to avoid import-time overhead.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL):
        """Initialize the embedding engine.

        Args:
            model_name: HuggingFace model identifier supported by fastembed.
        """
        self._model_name = model_name
        self._model = None

    def _ensure_model(self):
        """Lazily initialize the fastembed model."""
        if self._model is not None:
            return

        try:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(model_name=self._model_name)
            print(f"[EMBEDDING] Loaded model: {self._model_name}", flush=True)
        except ImportError:
            raise ImportError(
                "fastembed is required for embedding generation. "
                "Install it with: pip install fastembed"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to load embedding model '{self._model_name}': {e}")

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of text chunks.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (each is a list of floats, length VECTOR_DIM).
        """
        if not texts:
            return []

        self._ensure_model()

        embeddings = list(self._model.embed(texts))
        return [emb.tolist() if isinstance(emb, np.ndarray) else list(emb) for emb in embeddings]

    def embed_query(self, query: str) -> List[float]:
        """Generate an embedding for a single query string.

        Args:
            query: The query text.

        Returns:
            Embedding vector as a list of floats (length VECTOR_DIM).
        """
        if not query:
            return [0.0] * VECTOR_DIM

        self._ensure_model()

        # fastembed's embed() returns a generator; take the first result
        embeddings = list(self._model.embed([query]))
        emb = embeddings[0]
        return emb.tolist() if isinstance(emb, np.ndarray) else list(emb)


# Module-level singleton for convenience
_engine_instance: Optional[EmbeddingEngine] = None


def get_embedding_engine(model_name: str = DEFAULT_MODEL) -> EmbeddingEngine:
    """Get or create the singleton EmbeddingEngine.

    Args:
        model_name: Model name (only used on first call).

    Returns:
        EmbeddingEngine instance.
    """
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = EmbeddingEngine(model_name=model_name)
    return _engine_instance


def generate_embeddings(texts: List[str], model_name: str = DEFAULT_MODEL) -> List[List[float]]:
    """Convenience function to embed multiple texts.

    Args:
        texts: List of text strings.
        model_name: Model name.

    Returns:
        List of embedding vectors.
    """
    engine = get_embedding_engine(model_name)
    return engine.embed_texts(texts)


def embed_query(query: str, model_name: str = DEFAULT_MODEL) -> List[float]:
    """Convenience function to embed a single query.

    Args:
        query: Query text.
        model_name: Model name.

    Returns:
        Embedding vector.
    """
    engine = get_embedding_engine(model_name)
    return engine.embed_query(query)
