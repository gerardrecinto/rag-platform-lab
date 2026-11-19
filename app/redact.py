"""Replace common identifiers before text is stored or sent to a model.

Pattern based, so it misses names and free-text identifiers. Treat it as one layer, not a guarantee.
"""
import re

PATTERNS = [
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+?1[ -.]?)?\(?\d{3}\)?[ -.]\d{3}[ -.]\d{4}(?!\d)")),
    ("MRN", re.compile(r"\bMRN[:# ]*\d{5,10}\b", re.I)),
    ("DOB", re.compile(r"\b(?:DOB|born)[:\s]+\d{1,2}/\d{1,2}/\d{2,4}\b", re.I)),
]


def redact(text):
    """Return (clean_text, number_of_replacements)."""
    total = 0
    for label, pattern in PATTERNS:
        text, n = pattern.subn(f"[{label}]", text)
        total += n
    return text, total
