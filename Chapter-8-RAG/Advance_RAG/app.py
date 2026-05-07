from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import os
import uuid
import pandas as pd
import numpy as np
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import chromadb
from chromadb.utils import embedding_functions
from sentence_transformers import SentenceTransformer, CrossEncoder
from groq import Groq
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Models
# Embedding function for ChromaDB
embedding_model_name = "all-MiniLM-L6-v2"
embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=embedding_model_name)

# Reranker Model
reranker_model_name = "cross-encoder/ms-marco-MiniLM-L-6-v2"
reranker_model = CrossEncoder(reranker_model_name)

# ChromaDB Client
db_path = "./advance_rag_db"
chroma_client = chromadb.PersistentClient(path=db_path)
collection_name = "test_cases"

# Groq Client
groq_client = Groq(api_key=GROQ_API_KEY)

class QueryRequest(BaseModel):
    query: str
    top_k: int = 10
    rerank_k: int = 5

def get_collection():
    return chroma_client.get_or_create_collection(
        name=collection_name,
        embedding_function=embedding_function
    )

@app.get("/health")
async def health():
    return {"status": "online", "embedding_model": embedding_model_name, "reranker_model": reranker_model_name}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        # Read file
        extension = file.filename.split(".")[-1].lower()
        if extension == "csv":
            df = pd.read_csv(file.file)
        elif extension in ["xls", "xlsx"]:
            df = pd.read_excel(file.file)
        else:
            raise HTTPException(status_code=400, detail="Invalid file format. Please upload CSV or Excel.")

        # Ingestion logic
        collection = get_collection()
        
        # Clear existing collection for fresh ingestion (optional, but requested for "Stage 1")
        try:
            chroma_client.delete_collection(collection_name)
            collection = get_collection()
        except:
            pass

        documents = []
        metadatas = []
        ids = []
        
        # Process rows as test cases
        # We combine columns into a descriptive string for embedding
        for idx, row in df.iterrows():
            # Create a descriptive text for the test case
            content_parts = []
            metadata = {"row_index": idx}
            
            for col in df.columns:
                val = str(row[col])
                content_parts.append(f"{col}: {val}")
                # Add important columns to metadata
                if len(val) < 200: # Don't bloat metadata
                    metadata[col.lower().replace(" ", "_")] = val
            
            content = "\n".join(content_parts)
            documents.append(content)
            metadatas.append(metadata)
            ids.append(f"tc_{idx}_{uuid.uuid4().hex[:6]}")

        # Batch add to Chroma
        batch_size = 100
        for i in range(0, len(documents), batch_size):
            collection.add(
                documents=documents[i:i+batch_size],
                metadatas=metadatas[i:i+batch_size],
                ids=ids[i:i+batch_size]
            )

        return {
            "status": "success",
            "count": len(documents),
            "columns": list(df.columns),
            "preview": documents[:3] # Return first 3 for UI preview
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/query")
async def query_rag(request: QueryRequest):
    try:
        collection = get_collection()
        
        # Step 1: Initial Retrieval (Vector Search)
        results = collection.query(
            query_texts=[request.query],
            n_results=request.top_k,
            include=["documents", "metadatas", "distances"]
        )
        
        initial_docs = results["documents"][0]
        initial_metadatas = results["metadatas"][0]
        initial_distances = results["distances"][0]
        
        # Format for UI
        raw_results = []
        for doc, meta, dist in zip(initial_docs, initial_metadatas, initial_distances):
            raw_results.append({
                "content": doc,
                "metadata": meta,
                "score": 1 - dist # Approximate similarity
            })

        # Step 2: Reranking
        # We pair the query with each document
        pairs = [[request.query, doc] for doc in initial_docs]
        rerank_scores = reranker_model.predict(pairs)
        
        # Combine and sort by rerank score
        reranked_results = []
        for i, score in enumerate(rerank_scores):
            reranked_results.append({
                "content": initial_docs[i],
                "metadata": initial_metadatas[i],
                "original_score": raw_results[i]["score"],
                "rerank_score": float(score)
            })
        
        # Sort by rerank score descending
        reranked_results.sort(key=lambda x: x["rerank_score"], reverse=True)
        
        # Take top k after reranking
        top_reranked = reranked_results[:request.rerank_k]
        
        # Step 3: LLM Generation (Groq)
        context = "\n\n---\n\n".join([r["content"] for r in top_reranked])
        prompt = f"""
        You are an AI Test Engineering Assistant. Use the provided test cases to answer the user query.
        If the query asks to create a new test case, use the existing ones as a style guide.
        
        Context (Retrieved Test Cases):
        {context}
        
        User Query: {request.query}
        
        Answer professionally and concisely.
        """
        
        chat_completion = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
        )
        
        answer = chat_completion.choices[0].message.content

        return {
            "answer": answer,
            "raw_retrieval": raw_results,
            "reranked_results": reranked_results,
            "top_context": top_reranked,
            "stats": {
                "initial_count": len(initial_docs),
                "rerank_count": len(reranked_results),
                "final_context_count": len(top_reranked)
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def get_index():
    return FileResponse("index.html")

@app.get("/stats")
async def get_stats():
    try:
        collection = get_collection()
        count = collection.count()
        return {"total_chunks": count, "collection_name": collection_name}
    except:
        return {"total_chunks": 0, "collection_name": collection_name}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5002)
