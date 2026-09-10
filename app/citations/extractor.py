"""Conservative reference-list extraction for scholarly documents.

The parser deliberately keeps the original reference string.  Locally inferred
fields are candidates, not verified bibliographic facts.
"""

from dataclasses import asdict, dataclass
from pathlib import Path
import re
import unicodedata

from app.rag.loaders import load_document


@dataclass(frozen=True)
class ExtractedReference:
    reference_number: int | None
    raw_reference: str
    title: str
    year: int | None
    doi: str
    page: int
    extraction_method: str
    authors: list[str]
    venue: str
    needs_enrichment: bool

    def to_dict(self) -> dict:
        return asdict(self)


HEADING = re.compile(r"(?im)^\s*(references|bibliography|参考文献)\s*$")
NUMBERED = re.compile(r"(?m)(?:^|\s)\[(\d{1,3})\]\s+")
DOI = re.compile(r"(?i)\b10\.\d{4,9}/[-._;()/:A-Z0-9]+")
YEAR = re.compile(r"\b((?:19|20)\d{2})[a-z]?\b")


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _title(raw: str, year: int | None) -> str:
    text = re.sub(r"^\[\d+\]\s*", "", raw).strip()
    if year:
        match = re.search(rf"\b{year}[a-z]?\b[.,:]?\s*", text)
        if match:
            text = text[match.end():]
    # Most computer-science reference styles place title after year and before
    # the next sentence/venue. Keep a useful query even when punctuation is poor.
    candidate = re.split(r"\.\s+(?=[A-Z][A-Za-z]*(?:\s|,|:))", text, maxsplit=1)[0]
    candidate = re.sub(r"https?://\S+", "", candidate).strip(" .,:;\"")
    return candidate[:500] if len(candidate) >= 4 else ""


def _local_fields(raw: str, year: int | None) -> tuple[str,list[str],str,bool]:
    """Extract locally stated fields without claiming external verification."""
    text=re.sub(r"^\[\d+\]\s*","",raw).strip()
    title=_title(raw,year)
    position=text.casefold().find(title.casefold()) if title else -1
    authors_text=text[:position] if position>0 else ""
    authors_text=YEAR.sub("",authors_text).strip(" .,:;")
    authors=[x.strip(" .") for x in re.split(r"\s*;\s*|\s+and\s+",authors_text) if x.strip(" .")][:30]
    venue=""
    if position>=0:
        venue=text[position+len(title):]
        venue=DOI.sub("",venue)
        venue=re.sub(r"(?i)https?://\S+|\bdoi\s*:?","",venue)
        venue=YEAR.sub("",venue).strip(" .,:;")[:500]
    suspicious=(bool(YEAR.search(title)) or "references" in venue.casefold()
                or "参考文献" in venue)
    # Missing abstract/venue alone does not justify one network request per
    # reference. Online resolution is reserved for unusable core identities.
    needs_enrichment=len(normalize_title(title))<8 or year is None or suspicious
    return title,authors,venue,needs_enrichment


def normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+","",value.casefold())


def _page_for(raw: str, pages) -> int:
    needle = raw[:50].strip()
    for page in pages:
        if needle and needle in _clean(page.page_content):
            return int(page.metadata.get("page", 1))
    return int(pages[-1].metadata.get("page", len(pages)))


def extract_references(path: str | Path) -> list[ExtractedReference]:
    pages = load_document(path)
    full = "\n".join(page.page_content for page in pages)
    heading = list(HEADING.finditer(full))
    section = full[heading[-1].end():] if heading else full
    markers = list(NUMBERED.finditer(section))
    results: list[ExtractedReference] = []

    if markers:
        for index, marker in enumerate(markers):
            end = markers[index + 1].start() if index + 1 < len(markers) else len(section)
            raw = _clean(section[marker.start():end])
            # A very long item usually means the parser crossed out of references.
            if len(raw) < 12 or len(raw) > 2500:
                continue
            year_match = YEAR.search(raw)
            doi_match = DOI.search(raw)
            year = int(year_match.group(1)) if year_match else None
            title,authors,venue,needs_enrichment=_local_fields(raw,year)
            results.append(ExtractedReference(
                int(marker.group(1)), raw, title, year,
                doi_match.group(0).rstrip(".,;)").lower() if doi_match else "",
                _page_for(raw, pages), "numbered_reference_list",
                authors,venue,needs_enrichment,
            ))
    else:
        # Author-year styles are less structurally explicit.  Split only on a
        # strong boundary (sentence end + author name + nearby year) to reduce
        # false citation edges.
        compact = _clean(section)
        starts = [m.start(1) for m in re.finditer(
            r"(?:^|\.\s+)([A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+,\s+.{1,220}?\b(?:19|20)\d{2}[a-z]?\.)",
            compact,
        )]
        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else len(compact)
            raw = compact[start:end].strip()
            if not 20 <= len(raw) <= 2500:
                continue
            year_match, doi_match = YEAR.search(raw), DOI.search(raw)
            year = int(year_match.group(1)) if year_match else None
            title,authors,venue,needs_enrichment=_local_fields(raw,year)
            results.append(ExtractedReference(
                None, raw, title, year,
                doi_match.group(0).rstrip(".,;)").lower() if doi_match else "",
                _page_for(raw, pages), "author_year_reference_list",
                authors,venue,needs_enrichment,
            ))

    # Bound pathological documents and remove extraction duplicates.
    unique = {}
    for item in results:
        key = item.doi or re.sub(r"\W+", "", item.raw_reference.casefold())[:300]
        unique.setdefault(key, item)
    return list(unique.values())[:300]
