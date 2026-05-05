"""
Simple RAG Demo - Document Chunking with Nomic Embed
=====================================================
This script demonstrates:
1. Reading a text document
2. Splitting it into meaningful chunks
3. Generating embeddings for each chunk using Nomic Embed (via Ollama)
4. Displaying the chunks and their embedding vectors
5. Saving results to a JSON file for the HTML visualizer
"""

import json
import os
import sys

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

try:
    import ollama
except ImportError:
    print("ERROR: 'ollama' package not installed. Run: pip install ollama")
    sys.exit(1)

try:
    import numpy as np
except ImportError:
    print("ERROR: 'numpy' package not installed. Run: pip install numpy")
    sys.exit(1)


# ─────────────────────────────────────────────
# STEP 1: Read the Document
# ─────────────────────────────────────────────

def read_document(file_path: str) -> str:
    """Read the entire text document."""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


# ─────────────────────────────────────────────
# STEP 2: Chunk the Document
# ─────────────────────────────────────────────

def chunk_by_chapters(text: str) -> list[dict]:
    """
    Split document into chunks based on chapter headings.
    Each chunk contains:
      - chunk_id: sequential ID
      - title: chapter heading
      - text: chapter content
    """
    lines = text.split("\n")
    chunks = []
    current_title = ""
    current_lines = []
    chunk_id = 0

    for line in lines:
        # Detect chapter headings (lines starting with "Chapter")
        if line.strip().startswith("Chapter") and ":" in line:
            # Save the previous chunk if it has content
            if current_lines:
                chunk_text = "\n".join(current_lines).strip()
                if chunk_text:
                    chunks.append({
                        "chunk_id": chunk_id,
                        "title": current_title if current_title else "Introduction",
                        "text": chunk_text,
                        "char_count": len(chunk_text),
                        "word_count": len(chunk_text.split()),
                    })
                    chunk_id += 1
            current_title = line.strip()
            current_lines = []
        else:
            current_lines.append(line)

    # Don't forget the last chunk
    if current_lines:
        chunk_text = "\n".join(current_lines).strip()
        if chunk_text:
            chunks.append({
                "chunk_id": chunk_id,
                "title": current_title if current_title else "Epilogue",
                "text": chunk_text,
                "char_count": len(chunk_text),
                "word_count": len(chunk_text.split()),
            })

    return chunks


def chunk_by_fixed_size(text: str, chunk_size: int = 500, overlap: int = 50) -> list[dict]:
    """
    Split document into fixed-size character chunks with overlap.
    This is another common chunking strategy.
    """
    chunks = []
    start = 0
    chunk_id = 0

    while start < len(text):
        end = start + chunk_size
        chunk_text = text[start:end]

        # Try to break at a sentence boundary
        if end < len(text):
            last_period = chunk_text.rfind(".")
            if last_period > chunk_size * 0.5:
                end = start + last_period + 1
                chunk_text = text[start:end]

        chunks.append({
            "chunk_id": chunk_id,
            "title": f"Fixed Chunk {chunk_id + 1}",
            "text": chunk_text.strip(),
            "char_count": len(chunk_text.strip()),
            "word_count": len(chunk_text.strip().split()),
        })
        chunk_id += 1
        start = end - overlap  # overlap for context continuity

    return chunks


# ─────────────────────────────────────────────
# STEP 3: Generate Embeddings using Nomic Embed
# ─────────────────────────────────────────────

def generate_embeddings(chunks: list[dict], model: str = "nomic-embed-text") -> list[dict]:
    """
    Generate embeddings for each chunk using Ollama's Nomic Embed model.
    Each chunk gets an embedding vector (768 dimensions).
    """
    print(f"\n{'='*60}")
    print(f"  Generating Embeddings with '{model}'")
    print(f"{'='*60}\n")

    for i, chunk in enumerate(chunks):
        print(f"  Embedding chunk {i+1}/{len(chunks)}: {chunk['title'][:50]}...")

        # Call Ollama embedding API
        response = ollama.embed(
            model=model,
            input=chunk["text"]
        )

        # Extract the embedding vector
        embedding = response["embeddings"][0]
        chunk["embedding"] = embedding
        chunk["embedding_dim"] = len(embedding)

        print(f"    [OK] Generated {len(embedding)}-dimensional vector")

    return chunks


# ─────────────────────────────────────────────
# STEP 4: Compute Similarity Between Chunks
# ─────────────────────────────────────────────

def cosine_similarity(vec_a: list, vec_b: list) -> float:
    """Compute cosine similarity between two vectors."""
    a = np.array(vec_a)
    b = np.array(vec_b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def compute_similarity_matrix(chunks: list[dict]) -> list[list[float]]:
    """Compute pairwise cosine similarity between all chunks."""
    n = len(chunks)
    matrix = [[0.0] * n for _ in range(n)]

    for i in range(n):
        for j in range(n):
            if i == j:
                matrix[i][j] = 1.0
            elif j > i:
                sim = cosine_similarity(chunks[i]["embedding"], chunks[j]["embedding"])
                matrix[i][j] = sim
                matrix[j][i] = sim

    return matrix


# ─────────────────────────────────────────────
# STEP 5: Display Results
# ─────────────────────────────────────────────

def display_chunks(chunks: list[dict]):
    """Pretty-print the chunk information."""
    print(f"\n{'='*60}")
    print(f"  DOCUMENT CHUNKING RESULTS")
    print(f"{'='*60}")
    print(f"  Total Chunks: {len(chunks)}")
    print(f"{'='*60}\n")

    for chunk in chunks:
        print(f"+{'-'*58}+")
        print(f"|  Chunk #{chunk['chunk_id']}:  {chunk['title'][:45]:<45} |")
        print(f"+{'-'*58}+")
        print(f"|  Characters: {chunk['char_count']:<10}  Words: {chunk['word_count']:<10}       |")

        if "embedding_dim" in chunk:
            emb = chunk["embedding"]
            preview = ", ".join(f"{v:.4f}" for v in emb[:5])
            print(f"|  Embedding Dim: {chunk['embedding_dim']:<40} |")
            print(f"|  First 5 values: [{preview}, ...]  |")

        print(f"├{'─'*58}┤")

        # Show first 200 chars of text
        preview_text = chunk["text"][:200].replace("\n", " ")
        # Wrap text to fit in box
        for k in range(0, len(preview_text), 56):
            line = preview_text[k:k+56]
            print(f"|  {line:<56} |")

        print(f"|  {'...' if len(chunk['text']) > 200 else '':<56} |")
        print(f"+{'-'*58}+\n")


def display_similarity_matrix(chunks: list[dict], matrix: list[list[float]]):
    """Display similarity matrix between chunks."""
    print(f"\n{'='*60}")
    print(f"  COSINE SIMILARITY MATRIX")
    print(f"{'='*60}\n")

    # Header
    header = "         " + "  ".join(f"Ch{i:<4}" for i in range(len(chunks)))
    print(header)
    print("  " + "-" * (len(chunks) * 7 + 5))

    for i, row in enumerate(matrix):
        values = "  ".join(f"{v:.3f}" for v in row)
        print(f"  Ch{i:<3} │ {values}")

    print()

    # Find most similar pair (excluding self)
    max_sim = -1
    pair = (0, 0)
    for i in range(len(matrix)):
        for j in range(i + 1, len(matrix)):
            if matrix[i][j] > max_sim:
                max_sim = matrix[i][j]
                pair = (i, j)

    print(f"  [LINK] Most Similar Pair: Chunk {pair[0]} <-> Chunk {pair[1]}")
    print(f"     Similarity Score: {max_sim:.4f}")
    print(f"     '{chunks[pair[0]]['title']}' <-> '{chunks[pair[1]]['title']}'")
    print()


# ─────────────────────────────────────────────
# STEP 6: Save Results for HTML Visualizer
# ─────────────────────────────────────────────

def save_results_for_html(chunks: list[dict], similarity_matrix: list[list[float]], output_path: str):
    """Save chunk data and similarity matrix as JSON for the HTML visualizer."""

    # Prepare data (truncate embeddings for display)
    export_chunks = []
    for chunk in chunks:
        export_chunks.append({
            "chunk_id": chunk["chunk_id"],
            "title": chunk["title"],
            "text": chunk["text"],
            "char_count": chunk["char_count"],
            "word_count": chunk["word_count"],
            "embedding_dim": chunk.get("embedding_dim", 0),
            "embedding_preview": chunk.get("embedding", [])[:20],  # first 20 values
            "embedding_full": chunk.get("embedding", []),  # full embedding
        })

    data = {
        "total_chunks": len(chunks),
        "embedding_model": "nomic-embed-text",
        "chunks": export_chunks,
        "similarity_matrix": similarity_matrix,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"\n  [SAVED] Results saved to: {output_path}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    # File paths - use script location or current working directory
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        script_dir = os.getcwd()
    doc_path = os.path.join(script_dir, "story.txt")
    output_path = os.path.join(script_dir, "chunk_data.json")

    print("\n" + "=" * 60)
    print("  [RAG] Simple RAG Demo - Document Chunking & Embedding")
    print("  [DOC] Document: story.txt")
    print("  [MODEL] Embedding Model: nomic-embed-text (via Ollama)")
    print("=" * 60)

    # Step 1: Read document
    print("\n[1] Step 1: Reading document...")
    text = read_document(doc_path)
    print(f"   Document loaded: {len(text)} characters, {len(text.split())} words")

    # Step 2: Chunk the document (by chapters)
    print("\n[2] Step 2: Chunking document by chapters...")
    chunks = chunk_by_chapters(text)
    print(f"   Created {len(chunks)} chunks")

    # Display chunks BEFORE embedding
    display_chunks(chunks)

    # Step 3: Generate embeddings
    print("\n[3] Step 3: Generating embeddings with Nomic Embed...")
    print("   (Make sure Ollama is running: 'ollama serve')")
    print("   (Make sure model is pulled: 'ollama pull nomic-embed-text')\n")

    try:
        chunks = generate_embeddings(chunks)
    except Exception as e:
        print(f"\n  [ERROR] Error generating embeddings: {e}")
        print("  Make sure Ollama is running and nomic-embed-text model is pulled.")
        print("  Run: ollama pull nomic-embed-text")
        print("\n  Saving chunks without embeddings for HTML preview...\n")

        # Save without embeddings so HTML still works
        data = {
            "total_chunks": len(chunks),
            "embedding_model": "nomic-embed-text (not connected)",
            "chunks": [{
                "chunk_id": c["chunk_id"],
                "title": c["title"],
                "text": c["text"],
                "char_count": c["char_count"],
                "word_count": c["word_count"],
                "embedding_dim": 0,
                "embedding_preview": [],
                "embedding_full": [],
            } for c in chunks],
            "similarity_matrix": [],
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"  [SAVED] Partial results saved to: {output_path}")
        return

    # Display chunks WITH embeddings
    display_chunks(chunks)

    # Step 4: Compute similarity
    print("\n[4] Step 4: Computing chunk similarities...")
    sim_matrix = compute_similarity_matrix(chunks)
    display_similarity_matrix(chunks, sim_matrix)

    # Step 5: Save for HTML
    print("\n[5] Step 5: Saving results for HTML visualizer...")
    save_results_for_html(chunks, sim_matrix, output_path)

    print("\n" + "=" * 60)
    print("  [DONE] RAG Chunking Demo Complete!")
    print("  Open 'index.html' in your browser to visualize the results.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
