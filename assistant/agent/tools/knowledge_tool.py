"""
Tool 2 — search_knowledge_base

Retrieves boiler / turbine / chimney engineering documents from the
ChromaDB vector store built by knowledge_base/indexer.py.

Used by the agent for:
  - WHY questions (root cause explanations)
  - HOW-TO questions (procedures, action steps)
  - WHAT-IS questions (definitions, IBR concepts)
  - Multi-sensor diagnostic guides
"""
import os
import chromadb
from chromadb.utils import embedding_functions
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file

from assistant.config import (
    CHROMA_PATH, CHROMA_COLLECTION, EMBEDDING_MODEL, TOP_K_DOCS,
)

# Optional dependencies for hybrid search
try:
    from rank_bm25 import BM25Okapi
    import numpy as np
    from sentence_transformers import CrossEncoder
    HAS_HYBRID_DEPS = True
except ImportError:
    HAS_HYBRID_DEPS = False

# Must use the same embedding function as knowledge_base/indexer.py
# so that query vectors are compatible with stored document vectors.
OPEN_AI_API = os.getenv("OPENAI_API_KEY")
_embedding_fn = embedding_functions.OpenAIEmbeddingFunction(
    api_key=OPEN_AI_API,
    model_name=EMBEDDING_MODEL,
)
_client = chromadb.PersistentClient(path=CHROMA_PATH)

try:
    _collection = _client.get_collection(
        name=CHROMA_COLLECTION,
        embedding_function=_embedding_fn,
    )
except Exception:
    _collection = None


def search_knowledge_base(query: str, top_k: int = TOP_K_DOCS) -> str:
    """
    Semantic search over the boiler/chimney knowledge base.

    Args:
        query:  Natural-language query (e.g. "why is CO high in chimney").
        top_k:  How many top documents to return (default: TOP_K_DOCS from config).

    Returns:
        Concatenated text of top documents with title + similarity score,
        or a clear error/empty string if the KB is missing.
    """
    if _collection is None:
        return (
            "ERROR: Knowledge base collection not found. "
            "Run: python -m knowledge_base.indexer --mode=full"
        )

    try:
        if HAS_HYBRID_DEPS:
            # Hybrid search: Fetch more candidates and rerank
            results = _collection.query(
                query_texts=[query],
                n_results=top_k * 3,
            )
            docs = results.get("documents", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            ids = results.get("ids", [[]])[0]
            
            # Reranking logic
            cross_encoder = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
            pairs = [(query, doc) for doc in docs]
            scores = cross_encoder.predict(pairs)
            
            ranked_indices = np.argsort(scores)[::-1][:top_k]
            
            final_docs = [docs[i] for i in ranked_indices]
            final_metas = [metadatas[i] for i in ranked_indices]
            final_ids = [ids[i] for i in ranked_indices]
            final_scores = [float(scores[i]) for i in ranked_indices]
        else:
            # Pure ChromaDB fallback
            results = _collection.query(
                query_texts=[query],
                n_results=max(1, int(top_k)),
            )
            final_ids = results.get("ids", [[]])[0]
            final_docs = results.get("documents", [[]])[0]
            final_metas = results.get("metadatas", [[]])[0]
            final_scores = [1.0 - d for d in results.get("distances", [[]])[0]]

        if not final_docs:
            return f"No knowledge base documents matched query: '{query}'."

        lines = [f"=== KNOWLEDGE BASE RESULTS for: '{query}' ==="]
        for doc_id, meta, text, score in zip(final_ids, final_metas, final_docs, final_scores):
            similarity = round(score * 100, 1)
            title    = meta.get("title", doc_id)
            category = meta.get("category", "general")
            lines.append(
                f"\n--- {title}  "
                f"(id={doc_id}, category={category}, similarity={similarity}%) ---"
            )
            lines.append(text.strip())

        return "\n".join(lines)

    except Exception as e:
        return f"ERROR querying knowledge base: {e}"
