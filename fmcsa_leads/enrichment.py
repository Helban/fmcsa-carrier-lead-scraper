"""Best-effort email enrichment: find a carrier's website, then scrape an email.

The FMCSA census carries no email, so this fills the gap from outside sources: a
web search to locate the carrier's website, then a scrape of that site for a
contact address. Coverage is partial by design. Many small carriers have no
website, and some that do hide their address behind a contact form.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import replace
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .leads import CarrierLead

logger = logging.getLogger(__name__)

DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/"
REQUEST_TIMEOUT_SECONDS = 20.0
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Search hits on these hosts are directories or social pages, not the carrier's
# own site, so they never count as the company website.
_NON_COMPANY_HOSTS = (
    "facebook.com", "linkedin.com", "instagram.com", "twitter.com", "x.com",
    "yelp.com", "yellowpages.com", "bbb.org", "indeed.com", "glassdoor.com",
    "fmcsa.dot.gov", "dot.gov", "youtube.com", "mapquest.com", "wikipedia.org",
)

# Carrier sites usually surface a contact address on the homepage or one of these.
_CONTACT_PATHS = ("/contact", "/contact-us")

_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Addresses injected by site builders / tracking that are never a real contact.
_EMAIL_NOISE = ("example.com", "sentry", "wixpress.com", "@2x", ".png", ".jpg", ".gif")


def enrich_leads(
    leads: list[CarrierLead],
    limit: int | None = None,
    request_delay_seconds: float = 1.0,
) -> list[CarrierLead]:
    """Return leads with website/email filled where found, up to ``limit`` carriers.

    Enrichment is sequential and paced by ``request_delay_seconds`` to stay polite
    to the search engine and the carrier sites. Leads beyond ``limit`` are returned
    unchanged with empty website/email.
    """
    enriched_leads: list[CarrierLead] = []
    attempted = 0
    emails_found = 0
    request_headers = {"User-Agent": _BROWSER_USER_AGENT}
    with httpx.Client(
        timeout=REQUEST_TIMEOUT_SECONDS, headers=request_headers, follow_redirects=True
    ) as client:
        for lead in leads:
            if limit is not None and attempted >= limit:
                enriched_leads.append(lead)
                continue
            attempted += 1
            website = find_carrier_website(lead.legal_name, lead.state, client) or ""
            email = extract_email_from_site(website, client) if website else None
            if email:
                emails_found += 1
            enriched_leads.append(replace(lead, website=website, email=email or ""))
            logger.info(
                "Enriched %s: website=%s email=%s",
                lead.legal_name,
                website or "(none)",
                email or "(none)",
            )
            time.sleep(request_delay_seconds)
    logger.info("Email enrichment: %d attempted, %d emails found", attempted, emails_found)
    return enriched_leads


def find_carrier_website(
    company_name: str, state: str, client: httpx.Client
) -> str | None:
    """Return the carrier's own website (name must echo the domain), or None."""
    search_query = f"{company_name} trucking {state}"
    try:
        search_response = client.post(DUCKDUCKGO_HTML_URL, data={"q": search_query})
        search_response.raise_for_status()
    except httpx.HTTPError as search_error:
        logger.warning("Website search failed for %s: %s", company_name, search_error)
        return None
    if search_response.status_code == 202:
        logger.warning("Website search throttled for %s", company_name)
        return None
    return _first_company_result(search_response.text, company_name)


def extract_email_from_site(website: str, client: httpx.Client) -> str | None:
    """Scrape the homepage, then a contact page if needed, for a contact email."""
    homepage_email = _scrape_email(website, client)
    if homepage_email:
        return homepage_email
    for contact_path in _CONTACT_PATHS:
        contact_email = _scrape_email(urljoin(website, contact_path), client)
        if contact_email:
            return contact_email
    return None


def _first_company_result(search_html: str, company_name: str) -> str | None:
    search_page = BeautifulSoup(search_html, "html.parser")
    for result_link in search_page.select("a.result__a"):
        target_url = _decode_ddg_link(result_link.get("href", ""))
        if not target_url or _is_non_company_host(target_url):
            continue
        # Only trust a result whose domain echoes the company name. This rejects
        # trucking directories (otrucking.com, quicktransportsolutions.com) that
        # would otherwise hand back the directory's own contact email.
        if _domain_matches_company(target_url, company_name):
            return target_url
    return None


def _decode_ddg_link(href: str) -> str | None:
    """Unwrap DuckDuckGo's ``/l/?uddg=...`` redirect into the real target URL."""
    if not href:
        return None
    if href.startswith("http"):
        return href
    wrapped_target = parse_qs(urlparse(href).query).get("uddg", [])
    return wrapped_target[0] if wrapped_target else None


def _is_non_company_host(target_url: str) -> bool:
    host = urlparse(target_url).netloc.lower()
    return any(blocked_host in host for blocked_host in _NON_COMPANY_HOSTS)


# A company word shorter than this is too weak to confirm a domain match.
_MIN_TOKEN_LENGTH = 3

# Words too generic to confirm that a domain belongs to a given carrier.
_COMPANY_STOPWORDS = frozenset(
    {
        "inc", "llc", "corp", "corporation", "company", "co", "ltd", "the",
        "transport", "transportation", "trucking", "services", "service",
        "logistics", "freight", "carriers", "carrier", "and", "of",
    }
)


def _domain_matches_company(target_url: str, company_name: str) -> bool:
    """True when the domain echoes a meaningful word from the company name."""
    domain_label = _domain_label(target_url)
    return bool(domain_label) and any(
        token in domain_label for token in _significant_tokens(company_name)
    )


def _domain_label(target_url: str) -> str:
    """Return the second-level label, e.g. 'dixonbrosinc' from dixonbrosinc.com."""
    host = urlparse(target_url).netloc.lower().removeprefix("www.")
    host_parts = host.split(".")
    return host_parts[-2] if len(host_parts) >= 2 else host


def _significant_tokens(company_name: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", company_name.lower())
        if len(token) >= _MIN_TOKEN_LENGTH and token not in _COMPANY_STOPWORDS
    ]


def _scrape_email(page_url: str, client: httpx.Client) -> str | None:
    try:
        page_response = client.get(page_url)
        page_response.raise_for_status()
    except httpx.HTTPError:
        return None
    page = BeautifulSoup(page_response.text, "html.parser")
    for mail_link in page.select('a[href^="mailto:"]'):
        address = mail_link.get("href", "")[len("mailto:") :].split("?")[0].strip()
        if address and not _is_noise_email(address):
            return address.lower()
    for candidate_email in _EMAIL_PATTERN.findall(page.get_text(" ")):
        if not _is_noise_email(candidate_email):
            return candidate_email.lower()
    return None


def _is_noise_email(address: str) -> bool:
    lowered_address = address.lower()
    return any(noise in lowered_address for noise in _EMAIL_NOISE)
