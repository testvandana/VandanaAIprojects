"""
RAG Query Server
================
Flask API that:
  GET  /chunks        — returns all chunks from ChromaDB
  GET  /db_stats      — returns ChromaDB collection metadata
  POST /query         — embeds query → retrieves top-K chunks → calls Groq → returns answer
  GET  /health        — health check
"""

import os
import sys
import json
import time

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── Imports ────────────────────────────────────────────────────────────────────
try:
    from flask import Flask, request, jsonify
    from flask_cors import CORS
except ImportError:
    print("ERROR: flask/flask-cors not installed. Run: python -m pip install flask flask-cors")
    sys.exit(1)

try:
    import chromadb
except ImportError:
    print("ERROR: chromadb not installed. Run: python -m pip install chromadb")
    sys.exit(1)

try:
    import ollama
except ImportError:
    print("ERROR: ollama not installed. Run: python -m pip install ollama")
    sys.exit(1)

try:
    from groq import Groq
except ImportError:
    print("ERROR: groq not installed. Run: python -m pip install groq")
    sys.exit(1)

from dotenv import load_dotenv
load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR      = os.path.dirname(os.path.abspath(__file__))
DB_PATH         = os.path.join(SCRIPT_DIR, "chroma_db")
COLLECTION_NAME = "vwo_prd"
EMBED_MODEL     = "nomic-embed-text"
GROQ_API_KEY    = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL      = "llama-3.1-8b-instant"   # Fast, free-tier Groq model
TOP_K           = 5                          # Number of chunks to retrieve
PORT            = 5001

# ── Init ───────────────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)

# ChromaDB
chroma_client = chromadb.PersistentClient(path=DB_PATH)

def get_collection():
    try:
        return chroma_client.get_collection(name=COLLECTION_NAME)
    except Exception:
        return None

# Groq client
groq_client = Groq(api_key=GROQ_API_KEY)


# ── Helpers ────────────────────────────────────────────────────────────────────
def embed_query(text: str) -> list[float] | None:
    """Embed a query string using Nomic Embed via Ollama."""
    try:
        resp = ollama.embed(model=EMBED_MODEL, input=text)
        return resp["embeddings"][0]
    except Exception as e:
        print(f"[EMBED ERROR] {e}")
        return None


def retrieve_chunks(query_embedding: list[float], top_k: int = TOP_K) -> list[dict]:
    """Query ChromaDB for the most similar chunks."""
    collection = get_collection()
    if not collection:
        return []

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances", "embeddings"]
    )

    chunks = []
    ids       = results.get("ids", [[]])[0]
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    embeddings_list = results.get("embeddings")
    embeddings= embeddings_list[0] if embeddings_list is not None else [[]] * len(ids)

    for i, doc_id in enumerate(ids):
        similarity = 1 - distances[i]  # cosine distance → similarity
        emb = embeddings[i] if i < len(embeddings) else []
        metadata_clean = {}
        if metadatas[i]:
            for k, v in metadatas[i].items():
                metadata_clean[k] = int(v) if type(v).__name__.startswith('int') else (float(v) if type(v).__name__.startswith('float') else v)
        
        chunks.append({
            "id": str(doc_id),
            "text": str(documents[i]),
            "metadata": metadata_clean,
            "similarity": round(float(similarity), 4),
            "rank": int(i + 1),
            "embedding_preview": [float(x) for x in emb[:8]] if emb is not None and len(emb) > 0 else [],
        })

    return chunks


def call_groq(question: str, context_chunks: list[dict]) -> dict:
    """Send question + retrieved context to Groq LLM."""
    context = "\n\n---\n\n".join(
        f"[Chunk {c['rank']}] {c['text']}" for c in context_chunks
    )

    system_prompt = (
        "You are a knowledgeable QA assistant helping testers understand product requirements. "
        "Answer questions using ONLY the provided context from the VWO Product Requirements Document. "
        "Be concise, accurate, and cite which chunks you used. "
        "If the context doesn't contain the answer, say so clearly."
    )

    user_prompt = f"""Context from VWO PRD:
{context}

Question: {question}

Please answer based on the context above. Mention which parts of the document support your answer."""

    start_time = time.time()
    try:
        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=1024,
        )
        elapsed = round(time.time() - start_time, 2)
        answer = response.choices[0].message.content
        tokens_used = response.usage.total_tokens if response.usage else 0
        return {
            "answer": answer,
            "model": GROQ_MODEL,
            "tokens_used": tokens_used,
            "response_time_sec": elapsed,
            "error": None,
        }
    except Exception as e:
        print(f"⚠️ Groq API Error: {e}. Attempting local fallback to Ollama (gemma3:4b)...")
        try:
            # Local fallback using Ollama
            import ollama
            fallback_start = time.time()
            res = ollama.chat(
                model="gemma3:4b",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                options={"temperature": 0.3}
            )
            elapsed = round(time.time() - start_time, 2)
            return {
                "answer": res['message']['content'],
                "model": "gemma3:4b (Ollama Fallback)",
                "tokens_used": 0,
                "response_time_sec": elapsed,
                "error": None,
            }
        except Exception as ollama_e:
            elapsed = round(time.time() - start_time, 2)
            return {
                "answer": f"[Groq API Error] {str(e)}\n\n[Ollama Fallback Error] {str(ollama_e)}",
                "model": GROQ_MODEL,
                "tokens_used": 0,
                "response_time_sec": elapsed,
                "error": str(e),
            }


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    collection = get_collection()
    return jsonify({
        "status": "ok",
        "chromadb": "connected" if collection else "collection not found (run ingest_pdf.py first)",
        "collection": COLLECTION_NAME,
        "doc_count": collection.count() if collection else 0,
        "groq_model": GROQ_MODEL,
        "embed_model": EMBED_MODEL,
    })


@app.route("/db_stats", methods=["GET"])
def db_stats():
    try:
        collection = get_collection()
        if not collection:
            return jsonify({"error": "Collection not found. Run ingest_pdf.py first."}), 404

        # Get a sample of all chunks for DB viewer (max 200)
        count = collection.count()
        sample_results = collection.get(
            limit=min(200, count),
            include=["documents", "metadatas", "embeddings"]
        )

        rows = []
        ids       = sample_results.get("ids", [])
        documents = sample_results.get("documents", [])
        metadatas = sample_results.get("metadatas", [])
        embeddings_res = sample_results.get("embeddings")
        embeddings= embeddings_res if embeddings_res is not None else []

        for i, doc_id in enumerate(ids):
            emb = embeddings[i] if i < len(embeddings) else []
            rows.append({
                "id": str(doc_id),
                "chunk_id": int(metadatas[i].get("chunk_id", i)),
                "text_preview": str(documents[i][:150]) + ("..." if len(documents[i]) > 150 else ""),
                "char_count": int(metadatas[i].get("char_count", 0)),
                "word_count": int(metadatas[i].get("word_count", 0)),
                "embedding_dim": int(len(emb) if emb is not None else 0),
                "embedding_preview": [float(x) for x in emb[:6]] if emb is not None and len(emb) > 0 else [],
            })

        # Sort by chunk_id
        rows.sort(key=lambda x: x["chunk_id"])

        return jsonify({
            "collection_name": COLLECTION_NAME,
            "total_documents": int(count),
            "embedding_model": EMBED_MODEL,
            "db_path": DB_PATH,
            "documents": rows,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/chunks", methods=["GET"])
def get_chunks():
    """Return chunks from the JSON file (faster than querying ChromaDB for display)."""
    json_path = os.path.join(SCRIPT_DIR, "chunk_data.json")
    if not os.path.exists(json_path):
        return jsonify({"error": "chunk_data.json not found. Run ingest_pdf.py first."}), 404

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return jsonify(data)


@app.route("/query", methods=["POST"])
def query():
    """
    POST /query  { "question": "...", "top_k": 5 }
    Returns: { answer, retrieved_chunks, groq_info, query_embedding_preview }
    """
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    top_k    = int(body.get("top_k", TOP_K))

    if not question:
        return jsonify({"error": "Missing 'question' field"}), 400

    print(f"\n[QUERY] '{question}'")

    # 1. Embed query
    print("  → Embedding query ...")
    query_embedding = embed_query(question)
    if query_embedding is None:
        # Ollama not available — return error
        return jsonify({
            "error": "Failed to embed query. Is Ollama running? (ollama serve)",
            "question": question,
        }), 503

    # 2. Retrieve from ChromaDB
    print("  → Querying ChromaDB ...")
    retrieved_chunks = retrieve_chunks(query_embedding, top_k=top_k)
    if not retrieved_chunks:
        return jsonify({
            "error": "No chunks found. Run ingest_pdf.py to populate ChromaDB.",
            "question": question,
        }), 404

    print(f"  → Retrieved {len(retrieved_chunks)} chunks")

    # 3. Call Groq
    print("  → Calling Groq LLM ...")
    groq_result = call_groq(question, retrieved_chunks)
    print(f"  → Groq response received ({groq_result['response_time_sec']}s)")

    return jsonify({
        "question": question,
        "answer": groq_result["answer"],
        "retrieved_chunks": retrieved_chunks,
        "groq_info": {
            "model": groq_result["model"],
            "tokens_used": groq_result["tokens_used"],
            "response_time_sec": groq_result["response_time_sec"],
        },
        "query_embedding_preview": query_embedding[:8],
        "top_k": top_k,
        "error": groq_result.get("error"),
    })


# ── Run ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "="*60)
    print("  🚀  RAG Server Starting")
    print(f"     Port       : {PORT}")
    print(f"     ChromaDB   : {DB_PATH}")
    print(f"     Collection : {COLLECTION_NAME}")
    print(f"     Groq Model : {GROQ_MODEL}")
    print(f"     Embed Model: {EMBED_MODEL}")
    print("="*60)
    print(f"\n  ✅  Server running at http://localhost:{PORT}")
    print("  📄  Open index.html in your browser\n")

    app.run(host="0.0.0.0", port=PORT, debug=False)
