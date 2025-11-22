# ingest/ingest.py
# Usage: python ingest.py --input_dir ../docs --index_out faiss.index --meta_out docs_meta.json
import os, json, argparse
from sentence_transformers import SentenceTransformer
import faiss
from pathlib import Path
from tqdm import tqdm

MODEL = "all-MiniLM-L6-v2"
CHUNK_SIZE = 400
CHUNK_OVERLAP = 100

def read_text_files(input_dir):
    docs = []
    for p in Path(input_dir).rglob("*"):
        if p.suffix.lower() in [".txt", ".md"]:
            text = p.read_text(encoding="utf8")
            docs.append({"source": str(p.name), "text": text})
    return docs

def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i:i+chunk_size])
        chunks.append(chunk)
        i += chunk_size - overlap
    return chunks

def main(input_dir, index_out, meta_out):
    model = SentenceTransformer(MODEL)
    docs = read_text_files(input_dir)
    all_chunks = []
    meta = {}
    idx = 0
    for d in docs:
        chunks = chunk_text(d["text"])
        for c in chunks:
            meta[str(idx)] = {"source": d["source"], "chunk": c}
            all_chunks.append(c)
            idx += 1

    print("Embedding", len(all_chunks), "chunks...")
    embeddings = model.encode(all_chunks, convert_to_numpy=True, show_progress_bar=True)
    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)  # inner product; we will normalize
    faiss.normalize_L2(embeddings)
    index.add(embeddings)
    faiss.write_index(index, index_out)
    with open(meta_out, "w", encoding="utf8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print("Saved index and metadata")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_dir", required=True)
    parser.add_argument("--index_out", default="faiss.index")
    parser.add_argument("--meta_out", default="docs_meta.json")
    args = parser.parse_args()
    main(args.input_dir, args.index_out, args.meta_out)
