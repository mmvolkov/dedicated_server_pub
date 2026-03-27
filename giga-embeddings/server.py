#!/usr/bin/env python3
"""
Giga-Embeddings FastAPI server - /embed, /embed_query, /health
Model: ai-sage/Giga-Embeddings-instruct (2048 dim)
"""

import os
from contextlib import asynccontextmanager

import torch
from fastapi import FastAPI
from pydantic import BaseModel

MODEL_NAME = os.environ.get("MODEL_NAME", "ai-sage/Giga-Embeddings-instruct")
MAX_BATCH_SIZE = int(os.environ.get("MAX_BATCH_SIZE", "32"))
DEFAULT_QUERY_PROMPT = (
    "Instruct: Дан вопрос, необходимо найти абзац текста с ответом\nQuery: "
)

model = None
tokenizer = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global model, tokenizer
    from transformers import AutoModel, AutoTokenizer

    print(f"Loading {MODEL_NAME}...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
    model = AutoModel.from_pretrained(
        MODEL_NAME,
        # "eager" is slower than flash-attn, but it was the stable option
        # for this model/runtime combination on the target server.
        attn_implementation="eager",
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
    )
    model.eval()
    model.cuda()
    print("Model loaded.")
    yield
    model = None
    tokenizer = None


app = FastAPI(title="Giga-Embeddings", lifespan=lifespan)


class EmbedRequest(BaseModel):
    texts: list[str]


class EmbedQueryRequest(BaseModel):
    query: str
    task: str | None = None


def _embed(texts: list[str], prompt_prefix: str | None = None) -> list[list[float]]:
    if prompt_prefix:
        texts = [f"{prompt_prefix}{t}" for t in texts]
    batch_dict = tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=4096,
        return_tensors="pt",
    )
    batch_dict = {k: v.to(model.device) for k, v in batch_dict.items()}
    with torch.no_grad():
        embeddings = model(**batch_dict, return_embeddings=True)

    # Mean pooling over non-padding tokens.
    attention_mask = batch_dict["attention_mask"]
    mask_expanded = attention_mask.unsqueeze(-1).expand(embeddings.size()).float()
    sum_embeddings = torch.sum(embeddings * mask_expanded, 1)
    sum_mask = torch.clamp(mask_expanded.sum(1), min=1e-9)
    embeddings = (sum_embeddings / sum_mask).float().cpu().tolist()
    return embeddings


@app.post("/embed")
def embed(req: EmbedRequest):
    """Эмбеддинг документов без дополнительной инструкции."""
    texts = req.texts[:MAX_BATCH_SIZE]
    embeddings = _embed(texts)
    return {"embeddings": embeddings}


@app.post("/embed_query")
def embed_query(req: EmbedQueryRequest):
    """Эмбеддинг поискового запроса с инструкцией."""
    prompt = req.task or DEFAULT_QUERY_PROMPT
    embeddings = _embed([req.query], prompt_prefix=prompt)
    return {"embeddings": embeddings}


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_NAME}
