"""Simple character-based chunking strategy"""


from .base import Chunk, ChunkingStrategy


class CharacterChunkingStrategy(ChunkingStrategy):
    """
    Simple character-based chunking

    Splits text at fixed character intervals with overlap.
    Tries to split at word boundaries when possible.
    """

    def chunk(
        self,
        text: str,
        chunk_size: int = 2000,
        chunk_overlap: int = 200,
        **kwargs
    ) -> list[Chunk]:
        """Split text by character count"""
        chunks = []
        start = 0
        chunk_index = 0

        while start < len(text):
            end = start + chunk_size

            # Don't split in the middle of a word
            if end < len(text):
                # Find last space before end
                space_index = text.rfind(' ', start, end)
                if space_index > start:
                    end = space_index

            chunk_text = text[start:end].strip()

            if chunk_text:
                chunks.append(
                    Chunk(
                        text=chunk_text,
                        index=chunk_index,
                        metadata={
                            'strategy': 'character',
                            'start': start,
                            'end': end,
                            'chunk_size': len(chunk_text)
                        }
                    )
                )
                chunk_index += 1

            # Move start position (with overlap)
            start = end - chunk_overlap if end < len(text) else end

        return chunks
