"""Content hashing utilities for document deduplication."""
import hashlib
import asyncio
from typing import BinaryIO


def compute_hash_sync(content: bytes | str) -> str:
    """Compute SHA-256 hash synchronously."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


async def compute_hash_async(content: bytes | str) -> str:
    """Compute SHA-256 hash, offloading to thread pool for large content."""
    if isinstance(content, str):
        content = content.encode("utf-8")

    # For content >1MB, use thread pool to avoid blocking event loop
    if len(content) > 1_000_000:
        return await asyncio.to_thread(compute_hash_sync, content)

    return compute_hash_sync(content)


def compute_file_hash_streaming(file_obj: BinaryIO, chunk_size: int = 8192) -> str:
    """Compute hash using streaming for large files (memory-efficient)."""
    hasher = hashlib.sha256()
    while chunk := file_obj.read(chunk_size):
        hasher.update(chunk)
    return hasher.hexdigest()
