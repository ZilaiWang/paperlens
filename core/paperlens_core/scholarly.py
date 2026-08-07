"""Compliant, mockable scholarly metadata lookups.

Crossref and arXiv are the core providers.  DOI registration-agency lookup selects
DataCite when appropriate and doi.org CSL content negotiation is the neutral
fallback.  This module intentionally contains no Google Scholar scraper.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from datetime import timezone as _tz  # _tz.utc: Python 3.10 compat (datetime.UTC is 3.11+)
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import httpx

from paperlens_core.models import ReferenceIdentity, ReferenceRecord
from paperlens_core.references import extract_arxiv_id, normalize_arxiv_id, normalize_doi

FORBIDDEN_AUTOMATED_PROVIDERS = frozenset({"google_scholar"})
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
DEFAULT_MIN_INTERVALS = {
    "crossref": 0.34,
    "arxiv": 3.0,
    "datacite": 0.25,
    "doi": 0.25,
}


class ProviderUnavailable(RuntimeError):
    """Raised internally after a provider exhausts bounded retries."""


@dataclass(frozen=True, slots=True)
class ScholarlyMetadata:
    provider: str
    identifier: str
    title: str
    authors: tuple[str, ...]
    year: int | None
    venue: str = ""
    doi: str = ""
    arxiv_id: str = ""
    url: str = ""


@dataclass(frozen=True, slots=True)
class MatchAssessment:
    title_similarity: float
    first_author_match: bool
    year_match: bool
    identifier_match: bool

    @property
    def exact_consistency(self) -> bool:
        return (
            self.identifier_match
            and self.title_similarity >= 0.90
            and self.first_author_match
            and self.year_match
        )


@dataclass(frozen=True, slots=True)
class _CachedResponse:
    status_code: int
    headers: Mapping[str, str]
    content: bytes

    def as_httpx(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            self.status_code,
            headers=dict(self.headers),
            content=self.content,
            request=request,
        )


@dataclass(slots=True)
class MemoryTTLCache:
    """Small injectable response cache suitable for a single-process demo."""

    clock: Callable[[], float] = time.monotonic
    _items: dict[str, tuple[float, _CachedResponse]] = field(default_factory=dict)

    def get(self, key: str) -> _CachedResponse | None:
        item = self._items.get(key)
        if item is None:
            return None
        expires_at, response = item
        if self.clock() >= expires_at:
            self._items.pop(key, None)
            return None
        return response

    def set(self, key: str, response: _CachedResponse, ttl_seconds: float) -> None:
        self._items[key] = (self.clock() + ttl_seconds, response)

    def clear(self) -> None:
        self._items.clear()


def _first_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
    return ""


def _date_parts_year(item: Mapping[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = item.get(key)
        if not isinstance(value, Mapping):
            continue
        parts = value.get("date-parts")
        if isinstance(parts, Sequence) and parts and isinstance(parts[0], Sequence) and parts[0]:
            try:
                return int(parts[0][0])
            except (TypeError, ValueError):
                pass
    return None


def _crossref_metadata(item: Mapping[str, Any]) -> ScholarlyMetadata:
    doi = normalize_doi(str(item.get("DOI", "")))
    authors: list[str] = []
    for author in item.get("author", []) if isinstance(item.get("author"), list) else []:
        if not isinstance(author, Mapping):
            continue
        name_parts = (
            str(author.get("given", "")).strip(),
            str(author.get("family", "")).strip(),
        )
        name = " ".join(part for part in name_parts if part)
        if name:
            authors.append(name)
    year = _date_parts_year(
        item,
        "published-print",
        "published-online",
        "published",
        "issued",
        "created",
    )
    return ScholarlyMetadata(
        provider="crossref",
        identifier=doi,
        title=_first_text(item.get("title")),
        authors=tuple(authors),
        year=year,
        venue=_first_text(item.get("container-title")),
        doi=doi,
        url=str(item.get("URL", "")),
    )


def _datacite_metadata(payload: Mapping[str, Any]) -> ScholarlyMetadata:
    data = payload.get("data")
    attributes = data.get("attributes", {}) if isinstance(data, Mapping) else {}
    if not isinstance(attributes, Mapping):
        attributes = {}
    data_identifier = data.get("id", "") if isinstance(data, Mapping) else ""
    doi = normalize_doi(str(attributes.get("doi") or data_identifier))
    titles = attributes.get("titles", [])
    title = ""
    if isinstance(titles, list):
        for value in titles:
            if isinstance(value, Mapping) and str(value.get("title", "")).strip():
                title = str(value["title"]).strip()
                break
    authors: list[str] = []
    creators = attributes.get("creators", [])
    if isinstance(creators, list):
        for creator in creators:
            if not isinstance(creator, Mapping):
                continue
            name = str(creator.get("name", "")).strip()
            if not name:
                name = " ".join(
                    part
                    for part in (
                        str(creator.get("givenName", "")).strip(),
                        str(creator.get("familyName", "")).strip(),
                    )
                    if part
                )
            if name:
                authors.append(name)
    year_value = attributes.get("publicationYear")
    try:
        year = int(year_value) if year_value is not None else None
    except (TypeError, ValueError):
        year = None
    container = attributes.get("container")
    venue = str(container.get("title", "")).strip() if isinstance(container, Mapping) else ""
    venue = venue or str(attributes.get("publisher", "")).strip()
    return ScholarlyMetadata(
        provider="datacite",
        identifier=doi,
        title=title,
        authors=tuple(authors),
        year=year,
        venue=venue,
        doi=doi,
        url=str(attributes.get("url", "")),
    )


def _csl_metadata(item: Mapping[str, Any]) -> ScholarlyMetadata:
    doi = normalize_doi(str(item.get("DOI", "")))
    authors: list[str] = []
    for author in item.get("author", []) if isinstance(item.get("author"), list) else []:
        if not isinstance(author, Mapping):
            continue
        name_parts = (
            str(author.get("given", "")).strip(),
            str(author.get("family", "")).strip(),
        )
        name = " ".join(part for part in name_parts if part)
        if name:
            authors.append(name)
    year = _date_parts_year(item, "issued", "published-print", "published-online")
    return ScholarlyMetadata(
        provider="doi.org",
        identifier=doi,
        title=_first_text(item.get("title")),
        authors=tuple(authors),
        year=year,
        venue=_first_text(item.get("container-title")),
        doi=doi,
        url=str(item.get("URL", "")),
    )


def _normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    value = "".join(character for character in value if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9]+", value))


def _text_similarity(left: str, right: str) -> float:
    left_norm, right_norm = _normalize_text(left), _normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    sequence = SequenceMatcher(None, left_norm, right_norm).ratio()
    left_tokens, right_tokens = set(left_norm.split()), set(right_norm.split())
    token_score = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)
    return max(sequence, token_score)


def _surname(value: str) -> str:
    normalized = _normalize_text(value)
    if not normalized:
        return ""
    original = value.strip()
    if "," in original:
        return _normalize_text(original.split(",", 1)[0]).split()[-1]
    return normalized.split()[-1]


def _arxiv_core(value: str) -> str:
    """arXiv id without its version suffix ("1607.06450v1" -> "1607.06450")."""
    return re.sub(r"v\d+$", "", value)


def _assessment(
    reference: ReferenceRecord,
    metadata: ScholarlyMetadata,
    *,
    expected_identifier: str,
) -> MatchAssessment:
    local_first = _surname(reference.authors[0]) if reference.authors else ""
    remote_first = _surname(metadata.authors[0]) if metadata.authors else ""
    remote_identifier = metadata.doi or metadata.arxiv_id or metadata.identifier
    if expected_identifier.startswith("10."):
        identifier_match = normalize_doi(remote_identifier) == normalize_doi(expected_identifier)
    else:
        # compare version-less cores: 1607.06450 and 1607.06450v1 are the
        # same paper, and arXiv metadata carries the version in its id
        local_arxiv = _arxiv_core(normalize_arxiv_id(expected_identifier))
        remote_arxiv = _arxiv_core(normalize_arxiv_id(remote_identifier))
        identifier_match = bool(local_arxiv and remote_arxiv and local_arxiv == remote_arxiv)
    return MatchAssessment(
        title_similarity=_text_similarity(reference.parsed_title, metadata.title),
        first_author_match=bool(local_first and remote_first and local_first == remote_first),
        year_match=bool(reference.year is not None and metadata.year == reference.year),
        identifier_match=identifier_match,
    )


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After", "").strip()
    if not value:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=_tz.utc)  # noqa: UP017
            return max((retry_at - datetime.now(_tz.utc)).total_seconds(), 0.0)  # noqa: UP017
        except (TypeError, ValueError):
            return None


class ScholarlyClient:
    """Synchronous provider client with bounded retries and injectable I/O."""

    def __init__(
        self,
        *,
        contact_email: str,
        client: httpx.Client | None = None,
        cache: MemoryTTLCache | None = None,
        cache_ttl_seconds: float = 30 * 24 * 60 * 60,
        max_retries: int = 2,
        respect_rate_limits: bool = True,
        min_intervals: Mapping[str, float] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not contact_email or "@" not in contact_email:
            raise ValueError("contact_email is required for polite scholarly API access")
        self.contact_email = contact_email
        self.user_agent = f"PaperLens/1.0 (scholarly metadata resolver; mailto:{contact_email})"
        self._client = client or httpx.Client(timeout=httpx.Timeout(12.0, connect=5.0))
        self._owns_client = client is None
        # arXiv-only proxy (V3.6): separate client so Crossref/doi.org stay direct
        from .net import arxiv_mounts

        self._arxiv_proxy_client = (
            httpx.Client(timeout=httpx.Timeout(20.0, connect=8.0), mounts=arxiv_mounts())
            if arxiv_mounts()
            else None
        )
        self.cache = cache or MemoryTTLCache(clock=clock)
        self.cache_ttl_seconds = max(cache_ttl_seconds, 0.0)
        self.max_retries = max(max_retries, 0)
        self.respect_rate_limits = respect_rate_limits
        self.min_intervals = dict(DEFAULT_MIN_INTERVALS)
        if min_intervals:
            self.min_intervals.update(min_intervals)
        self._sleeper = sleeper
        self._clock = clock
        self._last_request: dict[str, float] = {}
        self.last_errors: dict[str, str] = {}

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
        if self._arxiv_proxy_client is not None:
            self._arxiv_proxy_client.close()

    def __enter__(self) -> ScholarlyClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _rate_limit(self, provider: str) -> None:
        if not self.respect_rate_limits:
            return
        interval = max(self.min_intervals.get(provider, 0.0), 0.0)
        previous = self._last_request.get(provider)
        now = self._clock()
        if previous is not None and now - previous < interval:
            self._sleeper(interval - (now - previous))
        self._last_request[provider] = self._clock()

    def _cache_key(
        self,
        provider: str,
        url: str,
        params: Mapping[str, Any] | None,
        accept: str,
    ) -> str:
        payload = json.dumps(dict(params or {}), ensure_ascii=True, sort_keys=True, default=str)
        return f"{provider}|{url}|{accept}|{payload}"

    def _request(
        self,
        provider: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        accept: str = "application/json",
    ) -> httpx.Response:
        headers = {"Accept": accept, "User-Agent": self.user_agent}
        request = httpx.Request("GET", url, params=params, headers=headers)
        key = self._cache_key(provider, url, params, accept)
        cached = self.cache.get(key)
        if cached is not None:
            return cached.as_httpx(request)

        client = (
            self._arxiv_proxy_client
            if provider == "arxiv" and self._arxiv_proxy_client is not None
            else self._client
        )
        last_exception: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._rate_limit(provider)
            try:
                response = client.get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    self._sleeper(min(0.5 * (2**attempt), 8.0))
                    continue
                break

            if response.status_code in RETRYABLE_STATUS_CODES:
                if attempt < self.max_retries:
                    delay = _retry_after_seconds(response)
                    self._sleeper(delay if delay is not None else min(0.5 * (2**attempt), 8.0))
                    continue
                last_exception = ProviderUnavailable(
                    f"{provider} returned HTTP {response.status_code}"
                )
                break

            if response.status_code == 404:
                return response
            if response.is_error:
                raise ProviderUnavailable(f"{provider} returned HTTP {response.status_code}")

            self.cache.set(
                key,
                _CachedResponse(
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    content=response.content,
                ),
                self.cache_ttl_seconds,
            )
            return response

        message = str(last_exception or "request failed")
        raise ProviderUnavailable(f"{provider} unavailable after bounded retries: {message}")

    def _safe_request(self, provider: str, url: str, **kwargs: Any) -> httpx.Response | None:
        try:
            response = self._request(provider, url, **kwargs)
        except (ProviderUnavailable, httpx.HTTPError, ValueError) as exc:
            self.last_errors[provider] = str(exc)
            return None
        if response.status_code == 404:
            return None
        return response

    def lookup_doi_registration_agency(self, doi: str) -> str:
        normalized = normalize_doi(doi)
        if not normalized:
            return ""
        url = f"https://doi.org/doiRA/{quote(normalized, safe='/')}"
        response = self._safe_request("doi", url)
        if response is None:
            return ""
        try:
            payload = response.json()
        except ValueError as exc:
            self.last_errors["doi"] = f"invalid DOI RA response: {exc}"
            return ""
        if isinstance(payload, list) and payload and isinstance(payload[0], Mapping):
            return str(payload[0].get("RA", "")).strip()
        return ""

    def lookup_crossref_doi(self, doi: str) -> ScholarlyMetadata | None:
        normalized = normalize_doi(doi)
        if not normalized:
            return None
        url = f"https://api.crossref.org/works/{quote(normalized, safe='/')}"
        response = self._safe_request(
            "crossref",
            url,
            params={"mailto": self.contact_email},
        )
        if response is None:
            return None
        try:
            payload = response.json()
            message = payload.get("message", {})
            return _crossref_metadata(message) if isinstance(message, Mapping) else None
        except (ValueError, TypeError) as exc:
            self.last_errors["crossref"] = f"invalid Crossref response: {exc}"
            return None

    def search_crossref(self, query: str, *, rows: int = 5) -> list[ScholarlyMetadata]:
        if not query.strip():
            return []
        response = self._safe_request(
            "crossref",
            "https://api.crossref.org/works",
            params={
                "query.bibliographic": query.strip(),
                "rows": min(max(rows, 1), 20),
                "mailto": self.contact_email,
            },
        )
        if response is None:
            return []
        try:
            payload = response.json()
            message = payload.get("message", {})
            items = message.get("items", []) if isinstance(message, Mapping) else []
            return [_crossref_metadata(item) for item in items if isinstance(item, Mapping)]
        except (ValueError, TypeError) as exc:
            self.last_errors["crossref"] = f"invalid Crossref search response: {exc}"
            return []

    def lookup_datacite_doi(self, doi: str) -> ScholarlyMetadata | None:
        normalized = normalize_doi(doi)
        if not normalized:
            return None
        url = f"https://api.datacite.org/dois/{quote(normalized, safe='/')}"
        response = self._safe_request("datacite", url)
        if response is None:
            return None
        try:
            payload = response.json()
            return _datacite_metadata(payload) if isinstance(payload, Mapping) else None
        except (ValueError, TypeError) as exc:
            self.last_errors["datacite"] = f"invalid DataCite response: {exc}"
            return None

    def lookup_doi_content_negotiation(self, doi: str) -> ScholarlyMetadata | None:
        normalized = normalize_doi(doi)
        if not normalized:
            return None
        url = f"https://doi.org/{quote(normalized, safe='/')}"
        response = self._safe_request(
            "doi",
            url,
            accept="application/vnd.citationstyles.csl+json",
        )
        if response is None:
            return None
        try:
            payload = response.json()
            return _csl_metadata(payload) if isinstance(payload, Mapping) else None
        except (ValueError, TypeError) as exc:
            self.last_errors["doi"] = f"invalid doi.org CSL response: {exc}"
            return None

    def resolve_doi(self, doi: str) -> ScholarlyMetadata | None:
        """Resolve through the DOI RA, with neutral doi.org fallback."""

        normalized = normalize_doi(doi)
        if not normalized:
            return None
        agency = self.lookup_doi_registration_agency(normalized).casefold()
        lookups: list[Callable[[str], ScholarlyMetadata | None]]
        if "crossref" in agency:
            lookups = [self.lookup_crossref_doi, self.lookup_doi_content_negotiation]
        elif "datacite" in agency:
            lookups = [self.lookup_datacite_doi, self.lookup_doi_content_negotiation]
        else:
            # Other RAs may still support standard DOI content negotiation.  If
            # the RA endpoint itself failed, Crossref/DataCite are bounded fallbacks.
            lookups = [
                self.lookup_doi_content_negotiation,
                self.lookup_crossref_doi,
                self.lookup_datacite_doi,
            ]
        for lookup in lookups:
            metadata = lookup(normalized)
            if metadata is not None and normalize_doi(metadata.doi) == normalized:
                return metadata
        return None

    def _parse_arxiv_entries(self, content: bytes) -> list[ScholarlyMetadata]:
        """Parse one arXiv Atom feed into ScholarlyMetadata entries."""
        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            self.last_errors["arxiv"] = f"invalid arXiv Atom response: {exc}"
            return []
        namespace = {"atom": "http://www.w3.org/2005/Atom"}
        entries: list[ScholarlyMetadata] = []
        for entry in root.findall("atom:entry", namespace):
            title = _first_text(entry.findtext("atom:title", default="", namespaces=namespace))
            authors = tuple(
                _first_text(author.findtext("atom:name", default="", namespaces=namespace))
                for author in entry.findall("atom:author", namespace)
            )
            authors = tuple(author for author in authors if author)
            published = entry.findtext("atom:published", default="", namespaces=namespace)
            year_match = re.match(r"(\d{4})", published)
            year = int(year_match.group(1)) if year_match else None
            entry_url = entry.findtext("atom:id", default="", namespaces=namespace)
            returned_id = normalize_arxiv_id(entry_url)
            venue = entry.findtext(
                "{http://arxiv.org/schemas/atom}journal_ref",
                default="",
            ).strip()
            if not returned_id:
                continue
            entries.append(
                ScholarlyMetadata(
                    provider="arxiv",
                    identifier=returned_id,
                    title=title,
                    authors=authors,
                    year=year,
                    venue=venue,
                    arxiv_id=returned_id,
                    url=entry_url,
                )
            )
        return entries

    def lookup_arxiv(self, arxiv_id: str) -> ScholarlyMetadata | None:
        normalized = normalize_arxiv_id(arxiv_id)
        if not normalized:
            return None
        response = self._safe_request(
            "arxiv",
            "https://export.arxiv.org/api/query",
            params={"id_list": normalized, "max_results": 1},
            accept="application/atom+xml",
        )
        if response is None:
            return None
        entries = self._parse_arxiv_entries(response.content)
        if not entries:
            return None
        returned = entries[0]
        if not returned.arxiv_id:
            returned = returned.model_copy() if hasattr(returned, "model_copy") else returned
        return returned

    def search_arxiv_by_title(self, title: str, max_results: int = 5) -> list[ScholarlyMetadata]:
        """Title search on the arXiv API (改进方案2.md §4.1 Source-first).

        Used by the upload route to discover an HTML-capable version of a
        submitted PDF. Polite-pool rate limiting applies (3s between arXiv
        requests); failures surface as an empty list, never an exception.
        """
        # NFKC turns ligatures/typographic chars into ASCII searchable forms
        # ("Uniﬁed" -> "Unified", curly quotes -> straight) — the arXiv API
        # otherwise returns zero hits for such queries
        cleaned = unicodedata.normalize("NFKC", title)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned or len(cleaned) < 8:
            return []
        response = self._safe_request(
            "arxiv",
            "https://export.arxiv.org/api/query",
            params={
                "search_query": f'ti:"{cleaned}"',
                "max_results": max_results,
                "sortBy": "relevance",
            },
            accept="application/atom+xml",
        )
        if response is None:
            return []
        return self._parse_arxiv_entries(response.content)

    def _provider_evidence(
        self,
        metadata: ScholarlyMetadata,
        assessment: MatchAssessment,
    ) -> dict[str, Any]:
        return {
            "provider": metadata.provider,
            "identifier": metadata.identifier,
            "title": metadata.title,
            "authors": list(metadata.authors),
            "year": metadata.year,
            "venue": metadata.venue,
            "doi": metadata.doi,
            "arxiv_id": metadata.arxiv_id,
            "url": metadata.url,
            "retrieved_at": datetime.now(_tz.utc).isoformat(timespec="seconds"),  # noqa: UP017
            "match": {
                "title_similarity": round(assessment.title_similarity, 4),
                "first_author_match": assessment.first_author_match,
                "year_match": assessment.year_match,
                "identifier_match": assessment.identifier_match,
            },
        }

    def _resolve_exact(
        self,
        reference: ReferenceRecord,
        metadata: ScholarlyMetadata | None,
        *,
        expected_identifier: str,
    ) -> ReferenceRecord:
        if metadata is None:
            return reference.model_copy(update={"identity_status": ReferenceIdentity.UNRESOLVED})
        assessment = _assessment(
            reference,
            metadata,
            expected_identifier=expected_identifier,
        )
        evidence = [*reference.provider_evidence, self._provider_evidence(metadata, assessment)]
        required_local_fields = bool(
            reference.parsed_title and reference.authors and reference.year
        )
        if required_local_fields and assessment.exact_consistency:
            status = ReferenceIdentity.VERIFIED
        elif required_local_fields:
            status = ReferenceIdentity.AMBIGUOUS
        else:
            # 本地解析字段不全（标题/作者/年份缺失或异常）：注册记录经
            # 精确 ID 明确存在，但无法断言与本地条目是同一篇——放宽为
            # PROBABLE 并回填注册元数据，避免"查到了却报查不到"的死锁
            #（修复 2026-08-05；VERIFIED 仍要求全字段一致）
            status = ReferenceIdentity.PROBABLE
        update: dict[str, object] = {
            "identity_status": status,
            "provider_evidence": evidence,
            "doi": reference.doi or metadata.doi,
            "arxiv_id": reference.arxiv_id or metadata.arxiv_id,
        }
        if status is ReferenceIdentity.PROBABLE:
            # 回填注册记录字段（本地解析不完整时）
            if not reference.parsed_title:
                update["parsed_title"] = metadata.title
            if not reference.authors:
                update["authors"] = list(metadata.authors)
            if reference.year is None or reference.year < 1950:
                update["year"] = metadata.year
        return reference.model_copy(update=update)

    def _fuzzy_score(
        self,
        reference: ReferenceRecord,
        metadata: ScholarlyMetadata,
    ) -> float:
        title = _text_similarity(reference.parsed_title, metadata.title)
        author = float(
            bool(
                reference.authors
                and metadata.authors
                and _surname(reference.authors[0]) == _surname(metadata.authors[0])
            )
        )
        if reference.year is None or metadata.year is None:
            year = 0.0
        elif reference.year == metadata.year:
            year = 1.0
        elif abs(reference.year - metadata.year) == 1:
            year = 0.5
        else:
            year = 0.0
        venue = _text_similarity(reference.venue, metadata.venue)
        return 0.55 * title + 0.20 * author + 0.15 * year + 0.10 * venue

    def resolve_reference(self, reference: ReferenceRecord) -> ReferenceRecord:
        """Resolve one reference while reserving VERIFIED for exact IDs."""

        if reference.doi:
            metadata = self.resolve_doi(reference.doi)
            return self._resolve_exact(
                reference,
                metadata,
                expected_identifier=reference.doi,
            )
        if reference.arxiv_id:
            metadata = self.lookup_arxiv(reference.arxiv_id)
            return self._resolve_exact(
                reference,
                metadata,
                expected_identifier=reference.arxiv_id,
            )

        # arXiv preprints carry DataCite DOIs and are absent from Crossref, so
        # an arXiv id inside the raw text takes the exact path (改进方案2.md
        # §11.4) before the fuzzy Crossref search.
        extracted = extract_arxiv_id(reference.raw_text)
        if extracted:
            metadata = self.lookup_arxiv(extracted)
            if metadata is not None:
                return self._resolve_exact(
                    reference.model_copy(update={"arxiv_id": extracted}),
                    metadata,
                    expected_identifier=extracted,
                )

        query_parts = [reference.parsed_title or reference.raw_text]
        if reference.authors:
            query_parts.append(reference.authors[0])
        if reference.year:
            query_parts.append(str(reference.year))
        candidates = self.search_crossref(" ".join(query_parts), rows=5)
        if not candidates:
            return reference.model_copy(update={"identity_status": ReferenceIdentity.UNRESOLVED})
        ranked = sorted(
            ((self._fuzzy_score(reference, candidate), candidate) for candidate in candidates),
            key=lambda item: item[0],
            reverse=True,
        )
        top_score, top = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        pseudo_assessment = MatchAssessment(
            title_similarity=_text_similarity(reference.parsed_title, top.title),
            first_author_match=bool(
                reference.authors
                and top.authors
                and _surname(reference.authors[0]) == _surname(top.authors[0])
            ),
            year_match=bool(reference.year is not None and reference.year == top.year),
            identifier_match=False,
        )
        evidence = self._provider_evidence(top, pseudo_assessment)
        evidence["fuzzy_score"] = round(top_score, 4)
        evidence["runner_up_score"] = round(second_score, 4)

        if top_score >= 0.78 and top_score - second_score < 0.08:
            status = ReferenceIdentity.AMBIGUOUS
        elif top_score >= 0.78:
            # A fuzzy search candidate is never promoted to VERIFIED.
            status = ReferenceIdentity.PROBABLE
        else:
            status = ReferenceIdentity.UNRESOLVED
        return reference.model_copy(
            update={
                "identity_status": status,
                "provider_evidence": [*reference.provider_evidence, evidence],
            }
        )

    def resolve_many(self, references: Sequence[ReferenceRecord]) -> list[ReferenceRecord]:
        return [self.resolve_reference(reference) for reference in references]


ScholarlyResolver = ScholarlyClient


__all__ = [
    "FORBIDDEN_AUTOMATED_PROVIDERS",
    "MatchAssessment",
    "MemoryTTLCache",
    "ProviderUnavailable",
    "ScholarlyClient",
    "ScholarlyMetadata",
    "ScholarlyResolver",
]
