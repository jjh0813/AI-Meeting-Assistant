import re


DEFAULT_MAX_CHARS = 800
DEFAULT_OVERLAP_CHARS = 150


def split_text(
    text: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[str]:
    """Split text near sentence boundaries while retaining a small overlap."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be between 0 and max_chars")

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]

    chunks: list[str] = []
    start = 0
    text_length = len(normalized)
    minimum_boundary = int(max_chars * 0.6)

    while start < text_length:
        hard_end = min(start + max_chars, text_length)
        end = hard_end
        if hard_end < text_length:
            search_start = start + minimum_boundary
            boundary_candidates = [
                normalized.rfind(separator, search_start, hard_end)
                for separator in ("\n\n", "\n", ". ", "? ", "! ", "。", "？", "！")
            ]
            boundary = max(boundary_candidates)
            if boundary >= search_start:
                end = boundary + 1
            else:
                word_boundary = normalized.rfind(" ", search_start, hard_end)
                if word_boundary >= search_start:
                    end = word_boundary

        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= text_length:
            break

        next_start = max(end - overlap_chars, start + 1)
        nearby_space = normalized.find(" ", next_start, min(end, next_start + 40))
        if nearby_space != -1:
            next_start = nearby_space + 1
        start = next_start

    return chunks
