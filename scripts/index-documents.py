#!/usr/bin/env python3
"""
index-documents.py — Массовая индексация документов в Qdrant через Giga-Embeddings.

Использование:
  python3 scripts/index-documents.py \
    --input-dir /data/documents/ \
    --collection regulations \
    --chunk-size 512 \
    --chunk-overlap 77 \
    --embedder-url http://localhost:8003

Поддерживаемые форматы: .txt, .md, .docx, .pdf (требует pymupdf)
"""

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Generator

import requests


# ─── Chunking ────────────────────────────────────────────────────────────────

def recursive_split(
    text: str,
    chunk_size: int = 512,
    chunk_overlap: int = 77,
    separators: list[str] = None,
) -> list[str]:
    """Рекурсивный сплит текста по иерархии разделителей."""
    if separators is None:
        separators = ["\n\n", "\n", ". ", " "]

    chunks = []
    current_sep = separators[0] if separators else ""
    parts = text.split(current_sep) if current_sep else [text]

    current_chunk = ""
    for part in parts:
        candidate = current_chunk + current_sep + part if current_chunk else part
        # Грубая оценка токенов: ~1 токен на 3.5 символов для русского
        if len(candidate) / 3.5 > chunk_size and current_chunk:
            chunks.append(current_chunk.strip())
            # Overlap: берём конец предыдущего чанка
            overlap_chars = int(chunk_overlap * 3.5)
            current_chunk = current_chunk[-overlap_chars:] + current_sep + part if overlap_chars else part
        else:
            current_chunk = candidate

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    # Если чанки всё ещё слишком большие — рекурсия с более мелким разделителем
    if len(separators) > 1:
        refined = []
        for chunk in chunks:
            if len(chunk) / 3.5 > chunk_size * 1.5:
                refined.extend(recursive_split(chunk, chunk_size, chunk_overlap, separators[1:]))
            else:
                refined.append(chunk)
        return refined

    return chunks


# ─── File readers ────────────────────────────────────────────────────────────

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def read_docx(path: Path) -> str:
    try:
        from docx import Document
        doc = Document(str(path))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except ImportError:
        print("  ⚠ python-docx не установлен, пропускаем .docx файлы (pip install python-docx)")
        return ""


def read_pdf(path: Path) -> str:
    try:
        import fitz  # pymupdf
        doc = fitz.open(str(path))
        text = "\n\n".join(page.get_text() for page in doc)
        doc.close()
        return text
    except ImportError:
        print("  ⚠ pymupdf не установлен, пропускаем .pdf файлы (pip install pymupdf)")
        return ""


READERS = {
    ".txt": read_text,
    ".md": read_text,
    ".docx": read_docx,
    ".pdf": read_pdf,
}


# ─── Embedding ───────────────────────────────────────────────────────────────

def embed_texts(texts: list[str], embedder_url: str, batch_size: int = 32) -> list[list[float]]:
    """Получить эмбеддинги через Giga-Embeddings API."""
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = requests.post(
            f"{embedder_url}/embed",
            json={"texts": batch},
            timeout=120,
        )
        resp.raise_for_status()
        all_embeddings.extend(resp.json()["embeddings"])
    return all_embeddings


# ─── Qdrant ──────────────────────────────────────────────────────────────────

def upsert_to_qdrant(
    qdrant_url: str,
    collection: str,
    points: list[dict],
    api_key: str = None,
):
    """Загрузить точки в Qdrant."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["api-key"] = api_key

    resp = requests.put(
        f"{qdrant_url}/collections/{collection}/points",
        json={"points": points},
        headers=headers,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Индексация документов в Qdrant")
    parser.add_argument("--input-dir", required=True, help="Папка с документами")
    parser.add_argument("--collection", default="regulations", help="Имя коллекции в Qdrant")
    parser.add_argument("--chunk-size", type=int, default=512, help="Размер чанка (токены)")
    parser.add_argument("--chunk-overlap", type=int, default=77, help="Overlap (токены, ~15%%)")
    parser.add_argument("--embedder-url", default="http://localhost:8003", help="URL Giga-Embeddings")
    parser.add_argument("--qdrant-url", default="http://localhost:6333", help="URL Qdrant")
    parser.add_argument("--qdrant-api-key", default=None, help="Qdrant API key")
    parser.add_argument("--batch-size", type=int, default=32, help="Размер батча для embedding")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    if not input_dir.exists():
        print(f"Ошибка: папка {input_dir} не найдена")
        sys.exit(1)

    # Собираем файлы
    files = [f for f in input_dir.rglob("*") if f.suffix.lower() in READERS]
    print(f"Найдено файлов: {len(files)}")

    total_chunks = 0
    total_points = 0

    for file_path in files:
        reader = READERS.get(file_path.suffix.lower())
        if not reader:
            continue

        print(f"\n📄 {file_path.name}")
        text = reader(file_path)
        if not text.strip():
            print("  ⏭ Пустой файл, пропускаем")
            continue

        # Чанкинг
        chunks = recursive_split(text, args.chunk_size, args.chunk_overlap)
        print(f"  → {len(chunks)} чанков")
        total_chunks += len(chunks)

        if not chunks:
            continue

        # Эмбеддинг
        embeddings = embed_texts(chunks, args.embedder_url, args.batch_size)
        print(f"  → {len(embeddings)} эмбеддингов (dim={len(embeddings[0])})")

        # Формирование точек для Qdrant
        points = []
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            point = {
                "id": str(uuid.uuid4()),
                "vector": embedding,
                "payload": {
                    "text": chunk,
                    "source": file_path.name,
                    "source_path": str(file_path.relative_to(input_dir)),
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                },
            }
            points.append(point)

        # Загрузка в Qdrant батчами
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            upsert_to_qdrant(args.qdrant_url, args.collection, batch, args.qdrant_api_key)

        total_points += len(points)
        print(f"  ✓ Загружено в Qdrant: {len(points)} точек")

    print(f"\n{'━' * 50}")
    print(f"  Файлов обработано: {len(files)}")
    print(f"  Чанков создано:    {total_chunks}")
    print(f"  Точек в Qdrant:    {total_points}")
    print(f"  Коллекция:         {args.collection}")
    print(f"{'━' * 50}")


if __name__ == "__main__":
    main()
