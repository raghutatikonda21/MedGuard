
import re
from collections import defaultdict


def normalize_medication_name(name: str) -> str:
    """Normalize whitespace and capitalization."""
    if not isinstance(name, str):
        raise TypeError("Medication name must be a string.")

    return re.sub(r"\s+", " ", name).strip().casefold()


def find_repeated_entries(names: list[str]) -> list[dict]:
    """Detect repeated medication names, ignoring case and extra spaces."""
    grouped_names = defaultdict(list)

    for name in names:
        normalized = normalize_medication_name(name)
        if normalized:
            grouped_names[normalized].append(name.strip())

    results = []

    for normalized, entries in grouped_names.items():
        if len(entries) > 1:
            results.append({
                "normalized_name": normalized,
                "entries": entries,
                "count": len(entries),
                "review_required": True,
                "message": (
                    "Repeated medication name detected. "
                    "Ask a qualified pharmacist or doctor to review it."
                ),
            })

    return results