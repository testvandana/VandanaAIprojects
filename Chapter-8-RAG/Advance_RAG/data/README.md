# Advanced RAG System - Data Layer

This directory contains the source data and configuration for the Advanced Retrieval-Augmented Generation (RAG) system.

## 🏗️ Architecture Stack (Open Source)

| Component | Recommendation | Description |
| :--- | :--- | :--- |
| **Embedding Model** | [BGE-M3](https://huggingface.co/BAAI/bge-m3) | Multi-lingual, multi-functional (Dense & Sparse) |
| **Reranker** | [BGE-Reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) | High-precision re-ordering of retrieved chunks |
| **Vector Database** | [Qdrant](https://qdrant.tech/) | High-performance, Rust-based, supports Hybrid Search |
| **LLM** | [Llama 3 (8B)](https://llama.meta.com/llama3/) | State-of-the-art open weights model for reasoning |

## 📂 Directory Structure

- `data/`: Place your PDF, TXT, or JSON source files here.
- `data/processed/`: (Placeholder) For cleaned or chunked data.
- `data/README.md`: This file.

## 🚀 Workflow Highlights

1. **Hybrid Ingestion**: Using BGE-M3 to store both semantic (vector) and keyword (sparse) indices.
2. **Two-Stage Retrieval**:
   - **Stage 1**: Retrieve top-k candidates using Qdrant Hybrid Search.
   - **Stage 2**: Refine candidates using the BGE Reranker to maximize relevance.
3. **Contextual Generation**: Feeding refined context into Llama 3 for the final response.
