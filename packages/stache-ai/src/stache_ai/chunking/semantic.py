"""Semantic chunking strategy"""

import re

from .base import Chunk, ChunkingStrategy


class SemanticChunkingStrategy(ChunkingStrategy):
    """
    Semantic chunking strategy

    Tries to preserve semantic units:
    - Paragraphs
    - Sentences
    - Code blocks
    - Lists
    """

    def chunk(
        self,
        text: str,
        chunk_size: int = 2000,
        chunk_overlap: int = 200,
        **kwargs
    ) -> list[Chunk]:
        """Split text at semantic boundaries"""

        # Split into semantic units (paragraphs, code blocks, etc.)
        units = self._extract_semantic_units(text)

        chunks = []
        current_chunk = []
        current_length = 0
        chunk_index = 0

        for unit in units:
            unit_length = len(unit['text'])

            # If adding this unit would exceed chunk size
            if current_length + unit_length > chunk_size and current_chunk:
                # Save current chunk
                chunk_text = '\n\n'.join([u['text'] for u in current_chunk])
                chunks.append(
                    Chunk(
                        text=chunk_text,
                        index=chunk_index,
                        metadata={
                            'strategy': 'semantic',
                            'units': len(current_chunk),
                            'chunk_size': len(chunk_text)
                        }
                    )
                )
                chunk_index += 1

                # Start new chunk (with overlap if possible)
                if chunk_overlap > 0 and current_chunk:
                    # Keep last unit for overlap
                    current_chunk = [current_chunk[-1], unit]
                    current_length = len(current_chunk[-1]['text']) + unit_length
                else:
                    current_chunk = [unit]
                    current_length = unit_length
            else:
                current_chunk.append(unit)
                current_length += unit_length

        # Add final chunk
        if current_chunk:
            chunk_text = '\n\n'.join([u['text'] for u in current_chunk])
            chunks.append(
                Chunk(
                    text=chunk_text,
                    index=chunk_index,
                    metadata={
                        'strategy': 'semantic',
                        'units': len(current_chunk),
                        'chunk_size': len(chunk_text)
                    }
                )
            )

        return chunks

    def _extract_semantic_units(self, text: str) -> list[dict]:
        """Extract semantic units from text"""
        units = []

        # Split by double newline (paragraphs)
        paragraphs = re.split(r'\n\n+', text)

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # Detect code blocks
            if para.startswith('```') or para.startswith('    '):
                units.append({'type': 'code', 'text': para})
            # Detect lists
            elif re.match(r'^[\*\-\+]\s', para) or re.match(r'^\d+\.\s', para):
                units.append({'type': 'list', 'text': para})
            # Regular paragraph
            else:
                units.append({'type': 'paragraph', 'text': para})

        return units
