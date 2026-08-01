import struct
import math


def pack_embedding(vector: list[float]) -> bytes:
    """Pack a list of floats into a compact binary representation."""
    return struct.pack(f"{len(vector)}f", *vector)


def unpack_embedding(data: bytes) -> list[float]:
    """Unpack binary data back into a list of floats."""
    count = len(data) // 4
    return list(struct.unpack(f"{count}f", data))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
