"""ChromaDB persistent vector store for concept-level document retrieval."""

from __future__ import annotations

import chromadb
from chromadb.utils import embedding_functions

_CLIENT: chromadb.PersistentClient | None = None
_DEFAULT_EF = embedding_functions.DefaultEmbeddingFunction()


def _get_client() -> chromadb.PersistentClient:
    """Return (or initialise) the singleton PersistentClient pointed at ./chroma_db."""
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = chromadb.PersistentClient(path=str(Path(__file__).resolve().parent.parent / "chroma_db"))
    return _CLIENT


def _collection_name(domain: str) -> str:
    """Derive a valid ChromaDB collection name from the domain string."""
    return domain.replace(" ", "_").lower()[:63] or "default"


def add_documents(concept_id: str, domain: str, documents: list) -> None:
    """Embed and store educational chunks under a domain collection.

    Args:
        concept_id: Identifier used as document ID prefix.
        domain: Domain name used to select the ChromaDB collection.
        documents: List of text strings to store.
    """
    client = _get_client()
    col = client.get_or_create_collection(
        name=_collection_name(domain),
        embedding_function=_DEFAULT_EF,
    )
    ids = [f"{concept_id}_{i}" for i in range(len(documents))]
    metadatas = [{"concept_id": concept_id} for _ in documents]
    col.add(documents=documents, ids=ids, metadatas=metadatas)


def query_documents(concept_id: str, domain: str, query: str, n_results: int = 2) -> list:
    """Retrieve top-n semantically similar chunks for a concept.

    Args:
        concept_id: Filter results to this concept.
        domain: Collection to query.
        query: Free-text query string.
        n_results: Number of results to return.

    Returns:
        List of document strings.
    """
    client = _get_client()
    col_name = _collection_name(domain)
    try:
        col = client.get_collection(name=col_name, embedding_function=_DEFAULT_EF)
    except Exception:
        return []

    results = col.query(
        query_texts=[query],
        n_results=n_results,
        where={"concept_id": concept_id},
    )
    docs = results.get("documents", [[]])[0]
    return docs


def collection_exists(concept_id: str) -> bool:
    """Return True if at least one document exists for this concept_id.

    Args:
        concept_id: The concept to check.

    Returns:
        True if documents are present, False otherwise.
    """
    client = _get_client()
    collections = client.list_collections()
    for col_obj in collections:
        try:
            col = client.get_collection(
                name=col_obj.name, embedding_function=_DEFAULT_EF
            )
            results = col.get(where={"concept_id": concept_id})
            if results and results.get("ids"):
                return True
        except Exception:
            continue
    return False
