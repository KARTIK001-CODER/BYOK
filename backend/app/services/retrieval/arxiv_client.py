import xml.etree.ElementTree as ET
import urllib.parse
from typing import List

import httpx

from app.services.retrieval.schemas import ChunkProvenance, RetrievalResult

class ArxivClient:
    """Client to search Arxiv dataset as a fallback when no documents are found."""

    BASE_URL = "https://export.arxiv.org/api/query"

    @classmethod
    async def search(cls, query: str, top_k: int = 3, organization_id: str = "arxiv") -> List[RetrievalResult]:
        """
        Search arXiv for the given query and return results as RetrievalResult objects.
        """
        # Build the arXiv query url
        encoded_query = urllib.parse.quote(query)
        url = f"{cls.BASE_URL}?search_query=all:{encoded_query}&start=0&max_results={top_k}"
        
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                response = await client.get(url, timeout=10.0)
                response.raise_for_status()
                
            return cls._parse_response(response.text, organization_id)
        except Exception as e:
            import logging
            logger = logging.getLogger("app.services.retrieval.arxiv_client")
            logger.warning(f"Failed to fetch from arXiv: {e}")
            return []

    @classmethod
    def _parse_response(cls, xml_data: str, organization_id: str) -> List[RetrievalResult]:
        """Parse the ATOM XML response from arXiv into RetrievalResult objects."""
        results = []
        try:
            root = ET.fromstring(xml_data)
            # arXiv uses atom namespace
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            
            entries = root.findall("atom:entry", ns)
            
            for idx, entry in enumerate(entries, start=1):
                id_el = entry.find("atom:id", ns)
                title_el = entry.find("atom:title", ns)
                summary_el = entry.find("atom:summary", ns)
                
                if id_el is None or title_el is None or summary_el is None:
                    continue
                    
                article_id = id_el.text.split("/")[-1] if id_el.text else f"arxiv_{idx}"
                title = title_el.text.replace("\n", " ").strip() if title_el.text else "Unknown Title"
                summary = summary_el.text.replace("\n", " ").strip() if summary_el.text else ""
                
                content = f"Title: {title}\nAbstract: {summary}"
                
                # Construct mock provenance for the citation engine
                provenance = ChunkProvenance(
                    organization_id=organization_id,
                    knowledge_base_id="arxiv_kb",
                    document_id=f"arxiv_{article_id}",
                    document_version_id="1",
                    chunk_id=f"arxiv_chunk_{article_id}",
                    chunk_index=0,
                    metadata={"document_name": f"arXiv: {title}"}
                )
                
                result = RetrievalResult(
                    chunk_id=f"arxiv_chunk_{article_id}",
                    document_id=f"arxiv_{article_id}",
                    document_version_id="1",
                    knowledge_base_id="arxiv_kb",
                    content=content,
                    score=1.0 - (idx * 0.01),  # mock score
                    rank=idx,
                    source="arxiv",
                    provenance=provenance,
                    metadata={"document_name": f"arXiv: {title}"}
                )
                results.append(result)
                
        except ET.ParseError as e:
            import logging
            logger = logging.getLogger("app.services.retrieval.arxiv_client")
            logger.error(f"Failed to parse arXiv XML: {e}")
            
        return results
