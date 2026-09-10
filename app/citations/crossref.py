"""Crossref enrichment with explicit entity-resolution rules."""
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from html import unescape
import re
import httpx

def normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", value.casefold())

def first(value) -> str:
    return str(value[0]) if isinstance(value,list) and value else str(value or "")

def published_parts(item: dict) -> list[int]:
    value=item.get("published") or item.get("published-print") or item.get("published-online") or {}
    parts=value.get("date-parts") or [[]]
    return parts[0] if parts else []

def match_score(candidate: dict,item: dict) -> float:
    if candidate.get("doi") and candidate["doi"].casefold()==str(item.get("DOI","")).casefold(): return 1.0
    left,right=normalize_title(candidate.get("title","")),normalize_title(first(item.get("title")))
    if not left or not right: return 0.0
    score=SequenceMatcher(None,left,right).ratio()
    parts=published_parts(item); remote_year=parts[0] if parts else None; local_year=candidate.get("year")
    if local_year and remote_year: score += 0.08 if int(local_year)==int(remote_year) else -0.12
    return max(0.0,min(1.0,score))

def crossref_metadata(item: dict,score: float,exact_doi: bool=False) -> dict:
    parts=published_parts(item)
    abstract=re.sub(r"\s+"," ",unescape(re.sub(r"<[^>]+>"," ",str(item.get("abstract",""))))).strip()
    authors=[]
    for author in item.get("author",[])[:30]:
        name=" ".join(x for x in (author.get("given",""),author.get("family","")) if x).strip()
        if name: authors.append(name)
    event=item.get("event") if isinstance(item.get("event"),dict) else {}
    return {"title":first(item.get("title")),"abstract":abstract,"authors":authors,
        "venue":first(item.get("container-title")) or first(event.get("name")),
        "publication_date":"-".join(str(x).zfill(2) if i else str(x) for i,x in enumerate(parts)),
        "year":parts[0] if parts else None,"doi":str(item.get("DOI","")).casefold(),
        "metadata_provider":"crossref","match_status":"doi_exact" if exact_doi else "matched",
        "match_score":round(score,4)}

class CrossrefEnricher:
    def __init__(self,timeout: int=20):
        self.timeout=timeout; self.headers={"User-Agent":"ResearchMate/0.3 (scholarly citation graph)"}
    def enrich_one(self,candidate: dict):
        with httpx.Client(timeout=self.timeout,headers=self.headers,follow_redirects=True) as client:
            if candidate.get("doi"):
                response=client.get("https://api.crossref.org/works/"+candidate["doi"]); response.raise_for_status()
                return crossref_metadata(response.json().get("message",{}),1.0,True),1.0
            query=candidate.get("title") or candidate.get("raw_reference","")
            response=client.get("https://api.crossref.org/works",params={"query.bibliographic":query[:500],"rows":3}); response.raise_for_status()
            scored=[(match_score(candidate,item),item) for item in response.json().get("message",{}).get("items",[])]
            if not scored: return None,0.0
            score,item=max(scored,key=lambda pair:pair[0])
            return (crossref_metadata(item,score) if score>=0.78 else None),score
    def enrich_many(self,candidates: list[dict]):
        def run(candidate):
            try:
                metadata,score=self.enrich_one(candidate); return candidate,metadata,score,""
            except (httpx.HTTPError,ValueError,KeyError,TypeError) as error:
                return candidate,None,0.0,type(error).__name__
        with ThreadPoolExecutor(max_workers=min(4,max(1,len(candidates)))) as pool:
            return list(pool.map(run,candidates))
