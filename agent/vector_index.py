"""
agent/vector_index.py
─────────────────────
Semantic vector search implementation using ChromaDB and Sentence Transformers.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any, cast


class VectorStore:
    def __init__(self, workdir: str) -> None:
        self.workdir = Path(workdir).resolve()
        
        try:
            import chromadb
            from chromadb.config import Settings
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise ImportError("chromadb or sentence-transformers not installed") from e

        # Initialise ChromaDB with anonymized_telemetry=False
        chroma_dir = self.workdir / ".chromadb"
        self.client = chromadb.PersistentClient(
            path=str(chroma_dir),
            settings=Settings(anonymized_telemetry=False)
        )
        
        # Load the sentence transformer model
        self.model = SentenceTransformer("all-MiniLM-L6-v2")
        
        # Create or get collection
        collection_name = f"devpilot_{hashlib.md5(str(self.workdir).encode()).hexdigest()[:8]}"
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )

    def _get_chunks_python(self, content: str) -> list[tuple[str, str, int]]:
        """Returns list of (chunk_id, text, start_line) for Python AST parsing."""
        chunks = []
        try:
            tree = ast.parse(content)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    segment = ast.get_source_segment(content, node)
                    if segment:
                        chunk_id = f"{node.name}"
                        chunks.append((chunk_id, segment, node.lineno))
        except Exception:
            pass
        return chunks

    def _get_chunks_text(self, content: str) -> list[tuple[str, str, int]]:
        """Returns list of (chunk_id, text, start_line) using 50-line sliding window."""
        lines = content.splitlines()
        chunks = []
        window_size = 50
        step = 25
        for i in range(0, len(lines), step):
            window = lines[i:i + window_size]
            if not window:
                continue
            text = "\n".join(window)
            chunk_id = f"lines_{i+1}_{i+len(window)}"
            chunks.append((chunk_id, text, i + 1))
            if i + window_size >= len(lines):
                break
        return chunks

    def index_file(self, path: Path | str, content: str) -> None:
        path_obj = Path(path)
        if path_obj.is_absolute():
            try:
                rel_path = str(path_obj.relative_to(self.workdir))
            except ValueError:
                rel_path = str(path_obj)
        else:
            rel_path = str(path_obj)
        
        # Remove existing chunks for this file
        try:
            self.collection.delete(where={"path": rel_path})
        except Exception:
            pass

        if path_obj.suffix == ".py":
            chunks = self._get_chunks_python(content)
            # If no functions/classes found, fallback to text chunks
            if not chunks:
                chunks = self._get_chunks_text(content)
        else:
            chunks = self._get_chunks_text(content)

        if not chunks:
            return

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []
        
        for chunk_id, text, start_line in chunks:
            ids.append(f"{rel_path}:{chunk_id}")
            documents.append(text)
            metadatas.append({
                "path": rel_path,
                "chunk_id": chunk_id,
                "start_line": start_line
            })

        # Batch encode with sentence-transformers
        embeddings = self.model.encode(documents, convert_to_numpy=True).tolist()
        
        if ids:
            _meta_cast = cast(
                list[dict[str, "str | int | float | bool | list | None"]],
                metadatas
            )
            self.collection.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=_meta_cast  # type: ignore[arg-type]
            )

    def search(self, query: str, n_results: int = 5) -> list[dict]:
        query_embedding = self.model.encode([query], convert_to_numpy=True).tolist()[0]
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"]
        )
        
        formatted_results = []
        ids = results.get("ids") or []
        metadatas = results.get("metadatas") or []
        documents = results.get("documents") or []
        distances = results.get("distances") or []

        if ids and ids[0]:
            for i in range(len(ids[0])):
                meta = (metadatas[0][i] if metadatas and metadatas[0] else None) or {}
                dist = distances[0][i] if distances and distances[0] else 0.0
                snippet = documents[0][i] if documents and documents[0] else ""
                formatted_results.append({
                    "path": meta.get("path", ""),
                    "chunk_id": meta.get("chunk_id", ""),
                    "snippet": snippet,
                    "distance": dist
                })

        return formatted_results
