from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

CAS_PATTERN = re.compile(r"\b\d{2,7}-\d{2}-\d\b")


class EgressDisabledError(Exception):
    """Raised when a network operation is attempted with egress disabled."""

    pass


class NISTScraper:
    BASE_URL = "https://webbook.nist.gov"

    def _check_egress(self) -> None:
        """Check if egress is enabled before making network calls."""
        from spectra_sherpa.app.core.security import is_egress_enabled

        if not is_egress_enabled():
            raise EgressDisabledError(
                "Network egress is disabled. Enable EGRESS_ENABLED=true or set APP_MODE=hybrid "
                "to allow NIST WebBook downloads."
            )

    async def search(self, query: str) -> list[dict[str, str]]:
        self._check_egress()
        url = f"{self.BASE_URL}/cgi/cbook.cgi"
        params = {"Name": query, "Units": "SI"}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, follow_redirects=True, timeout=30.0)

        if response.status_code >= 400:
            return []

        resolved = str(response.url)
        if "ID=" in resolved:
            result = self._parse_direct_result(response)
            return [result] if result else []
        return self._parse_list_results(response)

    async def download_spectrum(self, cas: str, index: int = 0) -> Optional[bytes]:
        self._check_egress()
        nist_id = f"C{re.sub(r'[^0-9]', '', cas)}"
        url = f"{self.BASE_URL}/cgi/cbook.cgi"
        params = {"JCAMP": nist_id, "Type": "IR"}
        if index:
            params["Index"] = index

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, params=params, timeout=30.0)
                response.raise_for_status()
            except httpx.HTTPError:
                return None

        if response.content.startswith(b"##TITLE"):
            return response.content
        return None

    def _parse_direct_result(self, response: httpx.Response) -> Optional[dict[str, str]]:
        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.find("h1", {"id": "Top"})
        name = title.get_text(strip=True) if title else ""
        cas_match = CAS_PATTERN.search(response.text)
        cas_number = cas_match.group(0) if cas_match else ""
        nist_id = self._extract_id(str(response.url))
        if not nist_id:
            return None
        return {
            "name": name or cas_number or "Unknown",
            "cas_number": cas_number,
            "nist_id": nist_id,
        }

    def _parse_list_results(self, response: httpx.Response) -> list[dict[str, str]]:
        soup = BeautifulSoup(response.text, "html.parser")
        results: list[dict[str, str]] = []
        seen_ids: set[str] = set()

        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "ID=" not in href:
                continue
            nist_id = self._extract_id(urljoin(self.BASE_URL, href))
            if not nist_id or nist_id in seen_ids:
                continue
            name = link.get_text(" ", strip=True)
            if not name:
                continue
            parent_text = link.parent.get_text(" ", strip=True) if link.parent else ""
            cas_match = CAS_PATTERN.search(parent_text)
            cas_number = cas_match.group(0) if cas_match else ""
            results.append({"name": name, "cas_number": cas_number, "nist_id": nist_id})
            seen_ids.add(nist_id)

        return results

    def _extract_id(self, url: str) -> Optional[str]:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        values = query.get("ID")
        return values[0] if values else None
