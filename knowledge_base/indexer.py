"""
knowledge_base/indexer.py

Indexes boiler_guides.py documents into ChromaDB.
Supports four modes:
  --mode=full    Delete everything and rebuild from scratch (safest)
  --mode=add     Add only new documents (by ID, skips existing)
  --mode=update  Update one specific document by ID
  --mode=verify  Check what is currently in ChromaDB without changing it

Usage:
  python -m knowledge_base.indexer                         (defaults to full re-index)
  python -m knowledge_base.indexer --mode=full             (delete all and rebuild)
  python -m knowledge_base.indexer --mode=add              (add documents not yet in DB)
  python -m knowledge_base.indexer --mode=update --id=fault_high_co  (update one doc)
  python -m knowledge_base.indexer --mode=verify           (show what is in ChromaDB)
"""
import argparse
import os
import sys
import chromadb
from chromadb.utils import embedding_functions
import os
from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file

# Allow running as a script from inside knowledge_base/ as well as `-m`
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from knowledge_base.boiler_guide import KNOWLEDGE_DOCUMENTS, validate_documents
from assistant.config import CHROMA_PATH, CHROMA_COLLECTION, EMBEDDING_MODEL

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Load OpenAI embedding model for ChromaDB
print(f"Loading Embedding model: {EMBEDDING_MODEL}...")
embedding_fn = embedding_functions.OpenAIEmbeddingFunction(
    api_key=OPENAI_API_KEY,
    model_name=EMBEDDING_MODEL,
)

# Connect to ChromaDB
print(f"Connecting to ChromaDB at: {CHROMA_PATH}")
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)


def get_or_create_collection():
    """Get existing collection or create new one"""
    try:
        collection = chroma_client.get_collection(
            name=CHROMA_COLLECTION,
            embedding_function=embedding_fn,
        )
        print(f"✅ Found existing collection: {CHROMA_COLLECTION} ({collection.count()} docs)")
        return collection
    except Exception:
        collection = chroma_client.create_collection(
            name=CHROMA_COLLECTION,
            embedding_function=embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )
        print(f"✅ Created new collection: {CHROMA_COLLECTION}")
        return collection


def mode_full():
    """
    DELETE everything and rebuild from scratch.
    """
    print("\n🔄 MODE: FULL RE-INDEX")
    print("  This will DELETE all existing documents and rebuild.")

    errors = validate_documents()
    if errors:
        print("❌ Validation failed. Fix errors before indexing:")
        for e in errors:
            print(f"   {e}")
        return

    try:
        chroma_client.delete_collection(name=CHROMA_COLLECTION)
        print(f"✅ Deleted existing collection: {CHROMA_COLLECTION}")
    except Exception:
        print("No existing collection to delete")

    collection = chroma_client.create_collection(
        name=CHROMA_COLLECTION,
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"},
    )

    docs, ids, metadatas = [], [], []
    for doc in KNOWLEDGE_DOCUMENTS:
        docs.append(doc["content"].strip())
        ids.append(doc["id"])
        metadatas.append({
            "title": doc["title"],
            "category": doc.get("category", "general"),
        })

    collection.add(documents=docs, ids=ids, metadatas=metadatas)

    print(f"\n✅ FULL RE-INDEX COMPLETE")
    print(f"   Total documents indexed: {collection.count()}")
    for doc in KNOWLEDGE_DOCUMENTS:
        print(f"   ✓ {doc['id']} — {doc['title']}")


def mode_add():
    """
    Add only documents that do not already exist in ChromaDB.
    Safe to run multiple times — skips documents already indexed.
    """
    print("\n🔄 MODE: ADD NEW DOCUMENTS ONLY")

    collection = get_or_create_collection()

    existing_ids = set()
    try:
        existing = collection.get()
        existing_ids = set(existing["ids"])
        print(f"✅ Found {len(existing_ids)} existing documents in ChromaDB")
    except Exception as e:
        print(f"could not fetch existing IDs: {e}")

    new_docs = [d for d in KNOWLEDGE_DOCUMENTS if d["id"] not in existing_ids]
    skip_docs = [d for d in KNOWLEDGE_DOCUMENTS if d["id"] in existing_ids]

    if not new_docs:
        print(f"Nothing to add. All {len(KNOWLEDGE_DOCUMENTS)} documents are already indexed.")
        return

    print(f"  Skipping {len(skip_docs)} existing documents")
    print(f"  Adding {len(new_docs)} new documents")

    docs, ids, metas = [], [], []
    for doc in new_docs:
        docs.append(doc["content"].strip())
        ids.append(doc["id"])
        metas.append({
            "title": doc["title"],
            "category": doc.get("category", "general"),
        })

    collection.add(documents=docs, ids=ids, metadatas=metas)

    print(f"\n✅ ADD COMPLETE")
    for doc in new_docs:
        print(f"   ✓ Added: {doc['id']} — {doc['title']}")
    print(f"   Total in collection: {collection.count()}")


def mode_update(doc_id: str):
    """
    Update one specific document by its ID.
    """
    print(f"\n🔄 MODE: UPDATE DOCUMENT — {doc_id}")

    doc = next((d for d in KNOWLEDGE_DOCUMENTS if d["id"] == doc_id), None)
    if doc is None:
        print(f"❌ Document ID '{doc_id}' not found in boiler_guides.py")
        print(f"   Available IDs: {[d['id'] for d in KNOWLEDGE_DOCUMENTS]}")
        return

    collection = get_or_create_collection()

    try:
        existing = collection.get(ids=[doc_id])
        if existing["ids"]:
            collection.update(
                ids=[doc_id],
                documents=[doc["content"].strip()],
                metadatas=[{
                    "title": doc["title"],
                    "category": doc.get("category", "general"),
                }],
            )
            print(f"✅ UPDATED: {doc_id}")
            print(f"   Title: {doc['title']}")
            print(f"   Content length: {len(doc['content'])} characters")
        else:
            collection.add(
                ids=[doc_id],
                documents=[doc["content"].strip()],
                metadatas=[{
                    "title": doc["title"],
                    "category": doc.get("category", "general"),
                }],
            )
            print(f"✅ ADDED (was not in ChromaDB): {doc_id}")
    except Exception as e:
        print(f"❌ Error updating {doc_id}: {e}")


def mode_verify():
    """
    Show what is currently stored in ChromaDB. Does not modify anything.
    """
    print("\n🔍 MODE: VERIFY — showing current ChromaDB contents")

    try:
        collection = chroma_client.get_collection(
            name=CHROMA_COLLECTION,
            embedding_function=embedding_fn,
        )
    except Exception:
        print(f"❌ Collection '{CHROMA_COLLECTION}' does not exist. Run: python -m knowledge_base.indexer --mode=full")
        return

    total = collection.count()
    print(f"✅ Collection '{CHROMA_COLLECTION}' exists with {total} documents.")

    if total == 0:
        print("⚠️  Collection exists but is empty. Run: python -m knowledge_base.indexer --mode=full")
        return

    all_docs = collection.get(include=["metadatas", "documents"])

    print(f"\nIndexed documents:")
    for doc_id, meta, doc_text in zip(
        all_docs["ids"],
        all_docs["metadatas"],
        all_docs["documents"],
    ):
        in_guides = any(d["id"] == doc_id for d in KNOWLEDGE_DOCUMENTS)
        status = "✓" if in_guides else "⚠️  NOT IN boiler_guides.py (orphan)"
        print(f"  {status} {doc_id}")
        print(f"       Title: {meta.get('title', 'N/A')}")
        print(f"       Category: {meta.get('category', 'N/A')}")
        print(f"       Content: {len(doc_text)} characters")

    indexed_ids = set(all_docs["ids"])
    guide_ids = set(d["id"] for d in KNOWLEDGE_DOCUMENTS)
    missing = guide_ids - indexed_ids
    if missing:
        print(f"\n⚠️  In boiler_guides.py but NOT indexed:")
        for mid in missing:
            print(f"  ✗ {mid}")
        print(f"  Run: python -m knowledge_base.indexer --mode=add  to index these")

    print(f"\n🔍 Test query: 'boiler pressure high fault'")
    results = collection.query(
        query_texts=["boiler pressure high fault"],
        n_results=3,
    )
    for meta, dist in zip(results["metadatas"][0], results["distances"][0]):
        similarity = round((1 - dist) * 100, 1)
        print(f"   → {meta['title']} (similarity: {similarity}%)")


# ── CLI entry point ──────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Knowledge Base Indexer")
    parser.add_argument(
        "--mode",
        choices=["full", "add", "update", "verify"],
        default="full",
        help="Operation mode",
    )
    parser.add_argument(
        "--id",
        default=None,
        help="Document ID for update mode",
    )
    args = parser.parse_args()

    if args.mode == "full":
        mode_full()
    elif args.mode == "add":
        mode_add()
    elif args.mode == "update":
        if not args.id:
            print("❌ --id is required for update mode")
            print("   Example: python -m knowledge_base.indexer --mode=update --id=fault_high_co")
            sys.exit(1)
        mode_update(args.id)
    elif args.mode == "verify":
        mode_verify()
