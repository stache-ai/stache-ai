"""Markdown-aware chunking strategy"""

import re

from .base import Chunk, ChunkingStrategy


class MarkdownChunkingStrategy(ChunkingStrategy):
    """
    Markdown-aware chunking strategy

    Respects markdown structure:
    - Headers (h1, h2, h3, etc.)
    - Code blocks
    - Lists
    - Preserves frontmatter
    """

    def chunk(
        self,
        text: str,
        chunk_size: int = 2000,
        chunk_overlap: int = 200,
        **kwargs
    ) -> list[Chunk]:
        """Split markdown text while preserving structure"""

        # Extract sections based on headers
        sections = self._split_by_headers(text)

        chunks = []
        current_chunk = ""
        current_metadata = {}
        chunk_index = 0

        for section in sections:
            section_text = section['text']
            section_header = section.get('header', '')

            # If adding this section would exceed chunk size
            if len(current_chunk) + len(section_text) > chunk_size and current_chunk:
                # Save current chunk
                chunks.append(
                    Chunk(
                        text=current_chunk.strip(),
                        index=chunk_index,
                        metadata={
                            'strategy': 'markdown',
                            'header': current_metadata.get('header', ''),
                            'chunk_size': len(current_chunk)
                        }
                    )
                )
                chunk_index += 1

                # Start new chunk with overlap
                if chunk_overlap > 0:
                    current_chunk = current_chunk[-chunk_overlap:] + '\n\n' + section_text
                else:
                    current_chunk = section_text

                current_metadata = {'header': section_header}
            else:
                # Add to current chunk
                if current_chunk:
                    current_chunk += '\n\n' + section_text
                else:
                    current_chunk = section_text
                    current_metadata = {'header': section_header}

        # Add final chunk
        if current_chunk.strip():
            chunks.append(
                Chunk(
                    text=current_chunk.strip(),
                    index=chunk_index,
                    metadata={
                        'strategy': 'markdown',
                        'header': current_metadata.get('header', ''),
                        'chunk_size': len(current_chunk)
                    }
                )
            )

        return chunks

    def _split_by_headers(self, text: str) -> list[dict]:
        """Split markdown by headers"""
        # Regex to match markdown headers (# Header)
        header_pattern = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)

        sections = []
        last_end = 0

        for match in header_pattern.finditer(text):
            # Text before this header
            if match.start() > last_end:
                sections.append({
                    'text': text[last_end:match.start()].strip(),
                    'header': None
                })

            # Find next header or end of text
            next_match = header_pattern.search(text, match.end())
            section_end = next_match.start() if next_match else len(text)

            # Extract section with header
            section_text = text[match.start():section_end].strip()
            sections.append({
                'text': section_text,
                'header': match.group(2),
                'level': len(match.group(1))
            })

            last_end = section_end

        # Add any remaining text
        if last_end < len(text):
            sections.append({
                'text': text[last_end:].strip(),
                'header': None
            })

        return [s for s in sections if s['text']]
