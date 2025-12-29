"""Recursive chunking strategy"""


from .base import Chunk, ChunkingStrategy


def find_best_boundary(text: str, position: int, search_range: int = 200) -> int:
    """
    Find the best boundary (paragraph, sentence, or word) near a position.

    Searches backward from position to find, in order of preference:
    1. Paragraph break (double newline)
    2. Sentence end (. ! ? followed by space/newline)
    3. Word boundary (space)

    Args:
        text: The text to search in
        position: Starting position (approximate boundary)
        search_range: How far back to search for a good boundary

    Returns:
        Position of the best boundary found
    """
    if position <= 0:
        return 0
    if position >= len(text):
        return len(text)

    search_start = max(0, position - search_range)
    search_text = text[search_start:position]

    # Try to find paragraph break (double newline)
    para_break = search_text.rfind('\n\n')
    if para_break != -1:
        return search_start + para_break + 2  # After the double newline

    # Try to find sentence end (. ! ? followed by space or newline)
    best_sentence = -1
    for i in range(len(search_text) - 1, 0, -1):
        if search_text[i - 1] in '.!?' and search_text[i] in ' \n':
            best_sentence = i
            break
    if best_sentence != -1:
        return search_start + best_sentence + 1  # After the space/newline

    # Fall back to word boundary
    space_pos = search_text.rfind(' ')
    if space_pos != -1:
        return search_start + space_pos + 1  # After the space

    newline_pos = search_text.rfind('\n')
    if newline_pos != -1:
        return search_start + newline_pos + 1  # After the newline

    # No good boundary found, return original position
    return position


class RecursiveChunkingStrategy(ChunkingStrategy):
    """
    Recursive chunking using multiple separators

    Tries to split on paragraphs first, then sentences, then words.
    Similar to LangChain's RecursiveCharacterTextSplitter.
    """

    def chunk(
        self,
        text: str,
        chunk_size: int = 2000,
        chunk_overlap: int = 200,
        **kwargs
    ) -> list[Chunk]:
        """Split text recursively"""
        separators = kwargs.get('separators', ['\n\n', '\n', '. ', ' ', ''])

        chunks = self._split_text(text, chunk_size, chunk_overlap, separators)

        return [
            Chunk(
                text=chunk_text,
                index=i,
                metadata={
                    'strategy': 'recursive',
                    'chunk_size': len(chunk_text),
                    'separators': separators
                }
            )
            for i, chunk_text in enumerate(chunks)
        ]

    def _split_text(
        self,
        text: str,
        chunk_size: int,
        chunk_overlap: int,
        separators: list[str]
    ) -> list[str]:
        """Recursively split text"""
        final_chunks = []

        # Start with the first separator
        separator = separators[0] if separators else ''
        new_separators = separators[1:] if len(separators) > 1 else []

        # Split by current separator
        splits = text.split(separator) if separator else [text]

        # Process splits
        current_chunk = []
        current_length = 0

        for split in splits:
            split_len = len(split)

            if current_length + split_len > chunk_size and current_chunk:
                # Current chunk is full, save it
                chunk_text = separator.join(current_chunk)
                final_chunks.append(chunk_text)

                # Start new chunk with overlap at best boundary (paragraph > sentence > word)
                if chunk_overlap > 0:
                    overlap_start = max(0, len(chunk_text) - chunk_overlap)
                    overlap_start = find_best_boundary(chunk_text, overlap_start)
                    overlap_text = chunk_text[overlap_start:]
                    current_chunk = [overlap_text, split]
                    current_length = len(overlap_text) + split_len
                else:
                    current_chunk = [split]
                    current_length = split_len
            else:
                current_chunk.append(split)
                current_length += split_len

        # Add remaining chunk
        if current_chunk:
            final_chunks.append(separator.join(current_chunk))

        # If any chunk is still too large and we have more separators, recurse
        if new_separators:
            processed_chunks = []
            for chunk in final_chunks:
                if len(chunk) > chunk_size:
                    processed_chunks.extend(
                        self._split_text(chunk, chunk_size, chunk_overlap, new_separators)
                    )
                else:
                    processed_chunks.append(chunk)
            return processed_chunks

        return final_chunks
