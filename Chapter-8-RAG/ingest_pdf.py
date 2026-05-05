"""
RAG Ingestion Pipeline — VWO PDF → ChromaDB
============================================
Steps:
  1. Extract text from PDF using PyMuPDF
  2. Chunk text with fixed-size + sentence-boundary strategy
  3. Generate embeddings using Nomic Embed (via Ollama)
  4. Store chunks + embeddings in local ChromaDB
  5. Export chunk_data.json for the HTML visualizer
"""

import json
import os
import sys
import time

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── Imports ────────────────────────────────────────────────────────────────────
try:
    import fitz  # PyMuPDF
except ImportError:
    print("ERROR: 'pymupdf' not installed. Run: python -m pip install pymupdf")
    sys.exit(1)

try:
    import chromadb
    from chromadb.config import Settings
except ImportError:
    print("ERROR: 'chromadb' not installed. Run: python -m pip install chromadb")
    sys.exit(1)

try:
    import ollama
except ImportError:
    print("ERROR: 'ollama' not installed. Run: python -m pip install ollama")
    sys.exit(1)

import numpy as np

# ── Constants ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PDF_PATH   = os.path.join(SCRIPT_DIR, "data", "Product Requirements Document_ VWO Login Dashboard.pdf")
DB_PATH    = os.path.join(SCRIPT_DIR, "chroma_db")
COLLECTION_NAME = "vwo_prd"
CHUNK_SIZE  = 600
CHUNK_OVERLAP = 80
EMBED_MODEL = "nomic-embed-text"
OUTPUT_JSON = os.path.join(SCRIPT_DIR, "chunk_data.json")


# ── Step 1: Extract PDF Text ───────────────────────────────────────────────────
def extract_pdf_text(pdf_path: str) -> tuple[str, int, list[dict]]:
    """Extract text from each page of the PDF."""
    print(f"\n[1] Extracting text from PDF: {os.path.basename(pdf_path)}")
    doc = fitz.open(pdf_path)
    full_text = ""
    pages = []
    for page_num, page in enumerate(doc, start=1):
        text = page.get_text("text")
        full_text += text + "\n"
        pages.append({"page": page_num, "text": text, "char_count": len(text)})
        print(f"    Page {page_num}: {len(text)} chars extracted")
    doc.close()
    print(f"   ✓ Total: {len(full_text)} characters across {len(pages)} pages")
    return full_text, len(pages), pages


# ── Step 2: Chunk Text ─────────────────────────────────────────────────────────
def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[dict]:
    """
    Split text into overlapping fixed-size chunks.
    Tries to break at sentence boundaries ('. ') for cleaner chunks.
    """
    print(f"\n[2] Chunking text (size={chunk_size}, overlap={overlap}) ...")
    chunks = []
    start = 0
    chunk_id = 0

    # Clean text
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # Remove excessive blank lines
    while '\n\n\n' in text:
        text = text.replace('\n\n\n', '\n\n')

    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk_text_raw = text[start:end]

        # Try to break at sentence boundary
        if end < len(text):
            # Look for last '. ' or '.\n' within the last 30% of the chunk
            search_start = int(chunk_size * 0.7)
            last_period = -1
            for delim in ['. ', '.\n', '! ', '? ', '!\n', '?\n']:
                idx = chunk_text_raw.rfind(delim, search_start)
                if idx > last_period:
                    last_period = idx + len(delim)
            if last_period > 0:
                end = start + last_period
                chunk_text_raw = text[start:end]

        chunk_clean = chunk_text_raw.strip()
        if len(chunk_clean) > 30:  # skip tiny fragments
            chunks.append({
                "chunk_id": chunk_id,
                "title": f"Chunk {chunk_id + 1}",
                "text": chunk_clean,
                "char_count": len(chunk_clean),
                "word_count": len(chunk_clean.split()),
                "start_char": start,
                "end_char": end,
            })
            chunk_id += 1

        if end >= len(text):
            break

        start = end - overlap

    print(f"   ✓ Created {len(chunks)} chunks")
    return chunks


# ── Step 3: Generate Embeddings ────────────────────────────────────────────────
def generate_embeddings(chunks: list[dict]) -> list[dict]:
    """Generate Nomic Embed embeddings for each chunk via Ollama."""
    print(f"\n[3] Generating embeddings with '{EMBED_MODEL}' via Ollama ...")
    print("    Make sure Ollama is running: 'ollama serve'")
    print("    Make sure model is pulled:   'ollama pull nomic-embed-text'\n")

    failed = False
    for i, chunk in enumerate(chunks):
        try:
            resp = ollama.embed(model=EMBED_MODEL, input=chunk["text"])
            embedding = resp["embeddings"][0]
            chunk["embedding"] = embedding
            chunk["embedding_dim"] = len(embedding)
            chunk["embedding_preview"] = embedding[:10]
            print(f"    [{i+1:03d}/{len(chunks)}] ✓  {chunk['title']} — {len(embedding)}D vector")
        except Exception as e:
            print(f"    [{i+1:03d}/{len(chunks)}] ✗  ERROR: {e}")
            chunk["embedding"] = []
            chunk["embedding_dim"] = 0
            chunk["embedding_preview"] = []
            failed = True

    if failed:
        print("\n    ⚠  Some embeddings failed. Is Ollama running?")
        print("       Run: ollama serve  (in a separate terminal)")
        print("       Then: ollama pull nomic-embed-text\n")

    return chunks


# ── Step 4: Store in ChromaDB ──────────────────────────────────────────────────
def store_in_chromadb(chunks: list[dict]) -> chromadb.Collection:
    """Persist chunks and their embeddings into local ChromaDB."""
    print(f"\n[4] Storing {len(chunks)} chunks into ChromaDB at: {DB_PATH}")

    # Init persistent ChromaDB client
    client = chromadb.PersistentClient(path=DB_PATH)

    # Delete existing collection to allow re-ingestion
    try:
        client.delete_collection(name=COLLECTION_NAME)
        print(f"    ↺  Cleared existing collection '{COLLECTION_NAME}'")
    except Exception:
        pass

    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine", "embedding_model": EMBED_MODEL}
    )

    # Filter chunks that have embeddings
    valid_chunks = [c for c in chunks if c.get("embedding")]
    invalid = len(chunks) - len(valid_chunks)
    if invalid:
        print(f"    ⚠  Skipping {invalid} chunks without embeddings")

    if not valid_chunks:
        print("    ✗  No valid embeddings found. ChromaDB not populated.")
        return collection

    # Batch upsert
    batch_size = 50
    for i in range(0, len(valid_chunks), batch_size):
        batch = valid_chunks[i:i + batch_size]
        collection.add(
            ids=[f"chunk_{c['chunk_id']}" for c in batch],
            embeddings=[c["embedding"] for c in batch],
            documents=[c["text"] for c in batch],
            metadatas=[{
                "chunk_id": c["chunk_id"],
                "title": c["title"],
                "char_count": c["char_count"],
                "word_count": c["word_count"],
                "start_char": c["start_char"],
                "end_char": c["end_char"],
            } for c in batch],
        )
        print(f"    ✓  Stored batch {i//batch_size + 1}: chunks {i}–{min(i+batch_size, len(valid_chunks))-1}")

    count = collection.count()
    print(f"\n    ✓✓ ChromaDB collection '{COLLECTION_NAME}' now has {count} documents")
    return collection


# ── Step 5: Compute Similarity Matrix ─────────────────────────────────────────
def cosine_similarity(a, b):
    a, b = np.array(a), np.array(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-10))


def compute_similarity_matrix(chunks: list[dict]) -> list[list[float]]:
    valid = [c for c in chunks if c.get("embedding")]
    n = len(valid)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                matrix[i][j] = 1.0
            elif j > i:
                sim = cosine_similarity(valid[i]["embedding"], valid[j]["embedding"])
                matrix[i][j] = sim
                matrix[j][i] = sim
    return matrix


# ── Step 6: Export JSON for HTML Visualizer ────────────────────────────────────
def export_json(chunks: list[dict], sim_matrix: list[list[float]], page_count: int, pages: list[dict]):
    """Save all data needed by the HTML UI."""
    export_chunks = []
    for c in chunks:
        export_chunks.append({
            "chunk_id": c["chunk_id"],
            "title": c["title"],
            "text": c["text"],
            "char_count": c["char_count"],
            "word_count": c["word_count"],
            "start_char": c["start_char"],
            "end_char": c["end_char"],
            "embedding_dim": c.get("embedding_dim", 0),
            "embedding_preview": c.get("embedding_preview", []),
            "has_embedding": bool(c.get("embedding")),
        })

    data = {
        "source": "Product Requirements Document_ VWO Login Dashboard.pdf",
        "page_count": page_count,
        "total_chunks": len(chunks),
        "valid_chunks": len([c for c in chunks if c.get("embedding")]),
        "embedding_model": EMBED_MODEL,
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
        "db_path": DB_PATH,
        "collection_name": COLLECTION_NAME,
        "chunks": export_chunks,
        "similarity_matrix": sim_matrix,
        "pages": [{"page": p["page"], "char_count": p["char_count"]} for p in pages],
        "ingested_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\n[6] ✓  Exported visualizer data → {OUTPUT_JSON}")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    print("\n" + "="*65)
    print("  🔍  RAG Ingestion Pipeline — VWO PDF → ChromaDB")
    print("="*65)

    if not os.path.exists(PDF_PATH):
        print(f"\n❌  PDF not found at: {PDF_PATH}")
        print("    Please place the PDF in the 'data/' folder.")
        sys.exit(1)

    # 1. Extract PDF text
    full_text, page_count, pages = extract_pdf_text(PDF_PATH)

    # 2. Chunk
    chunks = chunk_text(full_text)

    # 3. Embed
    chunks = generate_embeddings(chunks)

    # 4. Store in ChromaDB
    store_in_chromadb(chunks)

    # 5. Similarity matrix (use first 30 chunks to keep it manageable)
    print("\n[5] Computing cosine similarity matrix ...")
    sample = [c for c in chunks if c.get("embedding")][:30]
    sim_matrix = compute_similarity_matrix(sample)
    print(f"    ✓  {len(sample)}×{len(sample)} matrix computed")

    # 6. Export JSON
    export_json(chunks, sim_matrix, page_count, pages)

    print("\n" + "="*65)
    print("  ✅  Ingestion Complete!")
    print(f"     PDF pages : {page_count}")
    print(f"     Chunks    : {len(chunks)}")
    print(f"     ChromaDB  : {DB_PATH}")
    print(f"     JSON      : {OUTPUT_JSON}")
    print("\n  Next: python rag_server.py   (then open index.html)")
    print("="*65 + "\n")


if __name__ == "__main__":
    main()
