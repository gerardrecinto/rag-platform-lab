def chunk(text, size=60, overlap=10):
    """Split on words into overlapping windows. size and overlap are word counts."""
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")
    words = text.split()
    out, step = [], size - overlap
    for start in range(0, max(len(words), 1), step):
        piece = words[start:start + size]
        if piece:
            out.append(" ".join(piece))
        if start + size >= len(words):
            break
    return out
