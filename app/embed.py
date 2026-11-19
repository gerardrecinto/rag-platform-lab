"""Deterministic hashing embeddings. A lab stand-in so tests need no model download or API key.

Swap embed() for a real embedding model in production; the rest of the pipeline only needs a vector of EMBED_DIM floats.
"""
import hashlib
import math
import re

from .config import EMBED_DIM

WORD = re.compile(r"[a-z0-9]+")


def embed(text, dim=EMBED_DIM):
    vec = [0.0] * dim
    for w in WORD.findall(text.lower()):
        h = int.from_bytes(hashlib.blake2b(w.encode(), digest_size=8).digest(), "big")
        vec[h % dim] += 1.0 if (h >> 63) & 1 else -1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]
