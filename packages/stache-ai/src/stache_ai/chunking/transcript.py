"""Transcript chunking strategy for VTT/SRT files"""

import re

from .base import Chunk, ChunkingStrategy


class TranscriptChunkingStrategy(ChunkingStrategy):
    """
    Transcript chunking strategy optimized for VTT/SRT files

    Features:
    - Preserves timestamps
    - Respects cue boundaries
    - Groups by time windows or semantic breaks
    - Maintains speaker context if available
    """

    def chunk(
        self,
        text: str,
        chunk_size: int = 2000,
        chunk_overlap: int = 200,
        **kwargs
    ) -> list[Chunk]:
        """Split transcript at natural cue boundaries"""

        # Detect format (VTT or SRT)
        is_vtt = text.strip().startswith('WEBVTT')

        if is_vtt:
            cues = self._parse_vtt(text)
        else:
            # Try SRT format or plain text with timestamps
            cues = self._parse_srt_or_plain(text)

        if not cues:
            # Fallback to line-based chunking if no timestamps found
            return self._fallback_chunk(text, chunk_size, chunk_overlap)

        # Group cues into chunks
        chunks = []
        current_chunk = []
        current_length = 0
        chunk_index = 0

        for cue in cues:
            cue_text = cue['text']
            cue_length = len(cue_text)

            # If adding this cue would exceed chunk size
            if current_length + cue_length > chunk_size and current_chunk:
                # Save current chunk
                chunk_text = self._format_chunk(current_chunk, is_vtt)
                chunks.append(
                    Chunk(
                        text=chunk_text,
                        index=chunk_index,
                        metadata={
                            'strategy': 'transcript',
                            'cues': len(current_chunk),
                            'start_time': current_chunk[0]['start'],
                            'end_time': current_chunk[-1]['end'],
                            'duration': current_chunk[-1]['end'] - current_chunk[0]['start']
                        }
                    )
                )
                chunk_index += 1

                # Start new chunk with overlap (last cue for context)
                if chunk_overlap > 0 and current_chunk:
                    current_chunk = [current_chunk[-1], cue]
                    current_length = len(current_chunk[-1]['text']) + cue_length
                else:
                    current_chunk = [cue]
                    current_length = cue_length
            else:
                current_chunk.append(cue)
                current_length += cue_length

        # Add final chunk
        if current_chunk:
            chunk_text = self._format_chunk(current_chunk, is_vtt)
            chunks.append(
                Chunk(
                    text=chunk_text,
                    index=chunk_index,
                    metadata={
                        'strategy': 'transcript',
                        'cues': len(current_chunk),
                        'start_time': current_chunk[0]['start'],
                        'end_time': current_chunk[-1]['end'],
                        'duration': current_chunk[-1]['end'] - current_chunk[0]['start']
                    }
                )
            )

        return chunks

    def _parse_vtt(self, text: str) -> list[dict]:
        """Parse VTT format"""
        cues = []

        # Split by double newline to get cues
        blocks = re.split(r'\n\n+', text)

        for block in blocks:
            block = block.strip()
            if not block or block.startswith('WEBVTT') or block.startswith('NOTE'):
                continue

            lines = block.split('\n')

            # Find timestamp line (format: 00:00:00.000 --> 00:00:05.000)
            timestamp_pattern = r'(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})'

            for i, line in enumerate(lines):
                match = re.search(timestamp_pattern, line)
                if match:
                    start_str, end_str = match.groups()
                    start_time = self._parse_timestamp(start_str)
                    end_time = self._parse_timestamp(end_str)

                    # Extract speaker if present (e.g., <v Speaker Name>)
                    speaker_match = re.search(r'<v\s+([^>]+)>', line)
                    speaker = speaker_match.group(1) if speaker_match else None

                    # Get text (everything after timestamp line)
                    cue_text = '\n'.join(lines[i+1:]).strip()

                    # Remove VTT tags like <v Speaker>
                    cue_text = re.sub(r'<v\s+[^>]+>', '', cue_text)
                    cue_text = re.sub(r'</?[^>]+>', '', cue_text)

                    if cue_text:
                        cues.append({
                            'start': start_time,
                            'end': end_time,
                            'text': cue_text,
                            'speaker': speaker
                        })
                    break

        return cues

    def _parse_srt_or_plain(self, text: str) -> list[dict]:
        """Parse SRT format or plain text with timestamps"""
        cues = []

        # Split by double newline
        blocks = re.split(r'\n\n+', text)

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            lines = block.split('\n')

            # SRT format: number, timestamp, text
            # Format: 00:00:00,000 --> 00:00:05,000
            timestamp_pattern = r'(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})'

            for i, line in enumerate(lines):
                match = re.search(timestamp_pattern, line)
                if match:
                    start_str, end_str = match.groups()
                    # Normalize comma to dot
                    start_str = start_str.replace(',', '.')
                    end_str = end_str.replace(',', '.')

                    start_time = self._parse_timestamp(start_str)
                    end_time = self._parse_timestamp(end_str)

                    # Get text (everything after timestamp line)
                    cue_text = '\n'.join(lines[i+1:]).strip()

                    if cue_text:
                        cues.append({
                            'start': start_time,
                            'end': end_time,
                            'text': cue_text,
                            'speaker': None
                        })
                    break

        return cues

    def _parse_timestamp(self, timestamp_str: str) -> float:
        """Convert timestamp string to seconds (float)"""
        # Format: HH:MM:SS.mmm
        parts = timestamp_str.split(':')
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])

        return hours * 3600 + minutes * 60 + seconds

    def _format_timestamp(self, seconds: float) -> str:
        """Format seconds as HH:MM:SS"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def _format_chunk(self, cues: list[dict], is_vtt: bool) -> str:
        """Format cues into readable chunk text"""
        lines = []

        # Add header with time range
        start_time = self._format_timestamp(cues[0]['start'])
        end_time = self._format_timestamp(cues[-1]['end'])
        lines.append(f"[{start_time} - {end_time}]")
        lines.append("")

        # Add each cue
        for cue in cues:
            timestamp = self._format_timestamp(cue['start'])

            if cue.get('speaker'):
                lines.append(f"[{timestamp}] {cue['speaker']}: {cue['text']}")
            else:
                lines.append(f"[{timestamp}] {cue['text']}")

        return '\n'.join(lines)

    def _fallback_chunk(self, text: str, chunk_size: int, chunk_overlap: int) -> list[Chunk]:
        """Fallback to simple line-based chunking"""
        lines = text.split('\n')

        chunks = []
        current_chunk = []
        current_length = 0
        chunk_index = 0

        for line in lines:
            line = line.strip()
            if not line:
                continue

            line_length = len(line)

            if current_length + line_length > chunk_size and current_chunk:
                chunk_text = '\n'.join(current_chunk)
                chunks.append(
                    Chunk(
                        text=chunk_text,
                        index=chunk_index,
                        metadata={'strategy': 'transcript_fallback'}
                    )
                )
                chunk_index += 1

                # Overlap
                if chunk_overlap > 0:
                    current_chunk = [current_chunk[-1], line]
                    current_length = len(current_chunk[-1]) + line_length
                else:
                    current_chunk = [line]
                    current_length = line_length
            else:
                current_chunk.append(line)
                current_length += line_length

        if current_chunk:
            chunk_text = '\n'.join(current_chunk)
            chunks.append(
                Chunk(
                    text=chunk_text,
                    index=chunk_index,
                    metadata={'strategy': 'transcript_fallback'}
                )
            )

        return chunks
