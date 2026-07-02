"""
assistant/retrieval/hybrid_retriever.py
─────────────────────────────────────────
Hybrid retrieval: BM25 (keyword) + ChromaDB (semantic) + Cross-Encoder reranker.

Why hybrid?
  - Pure cosine similarity misses exact keyword matches (fault codes like
    "HIGH_CO", "CONDENSER_VACUUM_LOSS" are not well-represented as embeddings).
  - Pure BM25 misses semantic similarity ("pressure too high" ≠ "over-pressure fault").
  - Combining both then reranking with a cross-encoder gives 15–25% better recall
    on domain-specific technical queries.

Architecture:
  1. BM25Okapi: tokenized keyword search over the full ChromaDB corpus.
  2. ChromaDB:  dense vector (cosine) search via OpenAI embeddings.
  3. Dedup:     merge candidates, deduplicate by document text.
  4. Reranker:  CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2') scores
                each (query, document) pair and re-sorts by relevance.
  5. Return:    top-K final documents with rerank scores.

Fallback:
  - If rank-bm25 or sentence-transformers are not installed, falls back to
    ChromaDB-only search (silently degrades, does not crash).

Usage:
    from assistant.retrieval.hybrid_retriever import hybrid_search
    results = hybrid_search("HIGH_CO fault causes and remedies", top_k=6, final_k=3)
    for r in results:
        print(r["meta"]["title"], r["rerank_score"], r["doc"][:200])
"""
import logging
from typing import Optional

import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

from assistant.config import (
    CHROMA_PATH,
    CHROMA_COLLECTION,
    EMBEDDING_MODEL,
    TOP_K_DOCS,
    OPENAI_API_KEY,
)

logger = logging.getLogger(__name__)

# ── Optional dependencies (degrade gracefully) ─────────────────────────────────
try:
    from rank_bm25 import BM25Okapi as _BM25Okapi
    _BM25_AVAILABLE = True
except ImportError:
    _BM25_AVAILABLE = False
    logger.warning(
        "rank-bm25 not installed — BM25 keyword search disabled. "
        "Run: pip install rank-bm25"
    )

try:
    from sentence_transformers import CrossEncoder as _CrossEncoder
    _RERANKER_AVAILABLE = True
except ImportError:
    _RERANKER_AVAILABLE = False
    logger.warning(
        "sentence-transformers not installed — cross-encoder reranking disabled. "
        "Run: pip install sentence-transformers"
    )


# ── ChromaDB setup ─────────────────────────────────────────────────────────────
_chroma: Optional[chromadb.PersistentClient] = None
_collection = None
_embed_fn = None

def _init_chroma():
    global _chroma, _collection, _embed_fn
    if _collection is not None:
        return  # already initialised
    try:
        _embed_fn   = OpenAIEmbeddingFunction(api_key=OPENAI_API_KEY, model_name=EMBEDDING_MODEL)
        _chroma     = chromadb.PersistentClient(path=CHROMA_PATH)
        _collection = _chroma.get_collection(CHROMA_COLLECTION, embedding_function=_embed_fn)
        logger.info("HybridRetriever: ChromaDB loaded (%d docs)", _collection.count())
    except Exception as exc:
        logger.error("ChromaDB init failed in hybrid_retriever: %s", exc)
        _collection = None


# ── BM25 index (built once from ChromaDB corpus) ───────────────────────────────
_bm25:        Optional[object] = None
_corpus:      list[str]        = []
_corpus_meta: list[dict]       = []

def _init_bm25():
    """Build BM25 index from all ChromaDB documents. Called once at first use."""
    global _bm25, _corpus, _corpus_meta
    if not _BM25_AVAILABLE or _bm25 is not None:
        return
    if _collection is None:
        return
    try:
        result        = _collection.get(include=["documents", "metadatas"])
        _corpus       = result.get("documents", [])
        _corpus_meta  = result.get("metadatas", []) or [{}] * len(_corpus)
        tokenized     = [doc.lower().split() for doc in _corpus]
        _bm25         = _BM25Okapi(tokenized)
        logger.info("BM25 index built: %d documents", len(_corpus))
    except Exception as exc:
        logger.error("BM25 index build failed: %s", exc)


# ── Cross-Encoder reranker ─────────────────────────────────────────────────────
_reranker: Optional[object] = None

def _init_reranker():
    global _reranker
    if not _RERANKER_AVAILABLE or _reranker is not None:
        return
    try:
        _reranker = _CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        logger.info("Cross-encoder reranker loaded.")
    except Exception as exc:
        logger.error("Cross-encoder load failed: %s", exc)


# ── Public API ─────────────────────────────────────────────────────────────────

def hybrid_search(
    query: str,
    top_k: int = None,
    final_k: int = None,
) -> list[dict]:
    """
    Hybrid BM25 + ChromaDB search with cross-encoder reranking.

    Args:
        query:   Natural language or fault-code query string.
        top_k:   Candidates to retrieve from each source before merging.
                 Defaults to TOP_K_DOCS * 3.
        final_k: Documents to return after reranking.
                 Defaults to TOP_K_DOCS.

    Returns:
        List of dicts, sorted by relevance (highest first):
          { "doc": str, "meta": dict, "rerank_score": float }

        Returns [] if ChromaDB is unavailable or query is empty.
    """
    if not query or len(query.strip()) < 3:
        return []

    top_k   = top_k   or TOP_K_DOCS * 3
    final_k = final_k or TOP_K_DOCS

    # Lazy initialisation (heavy models loaded once on first call)
    _init_chroma()
    _init_bm25()
    _init_reranker()

    if _collection is None:
        logger.error("hybrid_search: ChromaDB not available")
        return []

    candidates: list[dict] = []
    seen_docs: set[str]    = set()

    # ── 1. ChromaDB semantic search ────────────────────────────────────────────
    try:
        n_results = min(top_k, _collection.count())
        res = _collection.query(
            query_texts=[query],
            n_results=max(n_results, 1),
            include=["documents", "metadatas", "distances"],
        )
        chroma_docs  = res.get("documents",  [[]])[0]
        chroma_metas = res.get("metadatas",  [[]])[0]
        for doc, meta in zip(chroma_docs, chroma_metas):
            if doc and doc not in seen_docs:
                seen_docs.add(doc)
                candidates.append({"doc": doc, "meta": meta or {}})
    except Exception as exc:
        logger.warning("ChromaDB query failed in hybrid_search: %s", exc)

    # ── 2. BM25 keyword search ─────────────────────────────────────────────────
    if _bm25 is not None and _corpus:
        try:
            tokens     = query.lower().split()
            scores     = _bm25.get_scores(tokens)
            top_indices = sorted(
                range(len(scores)), key=lambda i: scores[i], reverse=True
            )[:top_k]
            for idx in top_indices:
                if scores[idx] < 1e-6:
                    break  # stop at zero-score docs (no keyword overlap)
                doc  = _corpus[idx]
                meta = _corpus_meta[idx] if idx < len(_corpus_meta) else {}
                if doc and doc not in seen_docs:
                    seen_docs.add(doc)
                    candidates.append({"doc": doc, "meta": meta or {}})
        except Exception as exc:
            logger.warning("BM25 search failed: %s", exc)

    if not candidates:
        return []

    # ── 3. Cross-encoder reranking ─────────────────────────────────────────────
    if _reranker is not None:
        try:
            pairs  = [(query, c["doc"]) for c in candidates]
            scores = _reranker.predict(pairs)
            ranked = sorted(
                zip(scores, candidates), key=lambda x: x[0], reverse=True
            )
            return [
                {"doc": c["doc"], "meta": c["meta"], "rerank_score": float(s)}
                for s, c in ranked[:final_k]
            ]
        except Exception as exc:
            logger.warning("Reranker failed — falling back to ChromaDB order: %s", exc)

    # Fallback: return first final_k candidates without reranking
    return [
        {"doc": c["doc"], "meta": c["meta"], "rerank_score": 0.0}
        for c in candidates[:final_k]
    ]


def rebuild_bm25_index() -> None:
    """
    Force-rebuild the BM25 index from the current ChromaDB corpus.
    Call this after adding new documents to the knowledge base.
    """
    global _bm25, _corpus, _corpus_meta
    _bm25 = None
    _init_chroma()
    _init_bm25()
    logger.info("BM25 index rebuilt: %d documents", len(_corpus))
