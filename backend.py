"""
CIE QP-Only Custom Bundler — Backend Logic
Dependencies: pikepdf, reportlab, requests, diskcache
"""

import io
import time
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pikepdf
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

# ── Optional persistent cache ──────────────────────────────────────────────
try:
    import diskcache
    _disk_cache = diskcache.Cache("/tmp/qp_cache")
except ImportError:
    _disk_cache = None

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

SUBJECTS = {
    "Mathematics":       ("9709", "Mathematics-9709"),
    "Accounting":        ("9706", "Accounting-9706"),
    "Economics":         ("9708", "Economics-9708"),
    "Business":          ("9609", "Business-9609"),
    "Physics":           ("9702", "Physics-9702"),
    "Chemistry":         ("9701", "Chemistry-9701"),
    "Biology":           ("9700", "Biology-9700"),
    "Computer Science":  ("9618", "Computer-Science-9618"),
    "English General Paper": ("8021", "General-Paper-8021"),
}

SEASONS = {
    "May/June":   "s",
    "Oct/Nov":    "w",
    "Feb/Mar":    "m",
}

BASE_URL = (
    "https://pastpapers.papacambridge.com/Cambridge%20International%20A%20Level"
    "/{folder}/{year}/{code}_{season}{yy}_qp_{component}.pdf"
)

# ── Data model ─────────────────────────────────────────────────────────────

class SortOrder(Enum):
    YEAR = "year"
    COMPONENT = "component"

@dataclass
class PaperSelection:
    subject_name: str
    year: int
    season: str          # "s", "w", or "m"
    component: str       # e.g. "12", "22", "32"

    @property
    def subject_code(self) -> str:
        return SUBJECTS[self.subject_name][0]

    @property
    def subject_folder(self) -> str:
        return SUBJECTS[self.subject_name][1]

    @property
    def filename(self) -> str:
        yy = str(self.year)[-2:]
        return f"{self.subject_code}_{self.season}{yy}_qp_{self.component}.pdf"

    @property
    def url(self) -> str:
        yy = str(self.year)[-2:]
        return BASE_URL.format(
            folder=self.subject_folder,
            year=self.year,
            code=self.subject_code,
            season=self.season,
            yy=yy,
            component=self.component,
        )

    def __str__(self):
        season_name = {v: k for k, v in SEASONS.items()}.get(self.season, self.season)
        return f"{self.subject_name} · {season_name} {self.year} · Paper {self.component}"

# ── HTTP session with retry + polite delay ─────────────────────────────────

def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    })
    return session

_session = _build_session()

# ── Download with caching ──────────────────────────────────────────────────

def fetch_pdf(url: str, session_cache: dict) -> Optional[io.BytesIO]:
    """
    Returns BytesIO of the PDF, or None if not found (404).
    Checks in-session cache first, then disk cache, then fetches.
    """
    if url in session_cache:
        logger.debug("Session cache hit: %s", url)
        session_cache[url].seek(0)
        return session_cache[url]

    if _disk_cache is not None and url in _disk_cache:
        logger.debug("Disk cache hit: %s", url)
        buf = io.BytesIO(_disk_cache[url])
        session_cache[url] = buf
        return buf

    time.sleep(0.5)  # polite delay — avoids rate-limiting
    try:
        r = _session.get(url, timeout=15)
        r.raise_for_status()
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            logger.warning("404 not found: %s", url)
            return None
        raise
    except requests.RequestException as e:
        logger.error("Network error fetching %s: %s", url, e)
        raise

    data = r.content
    if _disk_cache is not None:
        _disk_cache[url] = data

    buf = io.BytesIO(data)
    session_cache[url] = buf
    return buf

# ── PDF generation helpers ─────────────────────────────────────────────────

def make_blank_page() -> pikepdf.Page:
    """Returns a blank A4 pikepdf page."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.save()
    buf.seek(0)
    blank_pdf = pikepdf.open(buf)
    return blank_pdf.pages[0]

def make_divider_page(label: str, papers: list[PaperSelection]) -> pikepdf.Page:
    """
    Generates a section-divider cover page as a pikepdf Page.
    label: e.g. "2023" or "Paper 12"
    papers: list of PaperSelection objects in this section
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    # Background stripe
    c.setFillColorRGB(0.95, 0.95, 0.95)
    c.rect(0, h - 180, w, 180, fill=1, stroke=0)

    # Section label
    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.setFont("Helvetica-Bold", 36)
    c.drawString(50, h - 100, label)

    # Subject name
    if papers:
        c.setFont("Helvetica", 18)
        c.setFillColorRGB(0.35, 0.35, 0.35)
        c.drawString(50, h - 135, papers[0].subject_name)

    # Paper list
    c.setFont("Helvetica", 12)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    y = h - 210
    for p in papers:
        season_map = {"s": "May/Jun", "w": "Oct/Nov", "m": "Feb/Mar"}
        line = f"  ·  {season_map.get(p.season, p.season)} {p.year}  —  Paper {p.component}"
        c.drawString(50, y, line)
        y -= 20

    c.save()
    buf.seek(0)
    div_pdf = pikepdf.open(buf)
    return div_pdf.pages[0]

def make_placeholder_page(paper: PaperSelection) -> pikepdf.Page:
    """Insert when a paper returns 404."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    c.setFillColorRGB(1.0, 0.95, 0.93)
    c.rect(0, 0, w, h, fill=1, stroke=0)

    c.setFont("Helvetica-Bold", 20)
    c.setFillColorRGB(0.7, 0.2, 0.1)
    c.drawCentredString(w / 2, h / 2 + 30, "FILE NOT FOUND")

    c.setFont("Helvetica", 13)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    c.drawCentredString(w / 2, h / 2 - 10, str(paper))
    c.drawCentredString(w / 2, h / 2 - 35, f"({paper.filename})")
    c.drawCentredString(w / 2, h / 2 - 60, "This paper was not available on PapaCambridge.")

    c.save()
    buf.seek(0)
    ph_pdf = pikepdf.open(buf)
    return ph_pdf.pages[0]

# ── Sorting ────────────────────────────────────────────────────────────────

def sort_papers(papers: list[PaperSelection], order: SortOrder) -> list[PaperSelection]:
    if order == SortOrder.YEAR:
        return sorted(papers, key=lambda p: (p.year, p.season, p.component), reverse=True)
    else:  # COMPONENT
        return sorted(papers, key=lambda p: (p.component, p.year, p.season), reverse=False)

def group_key(paper: PaperSelection, order: SortOrder) -> str:
    if order == SortOrder.YEAR:
        return str(paper.year)
    else:
        return f"Paper {paper.component}"

# ── Main merge function ────────────────────────────────────────────────────

def build_bundle(
    papers: list[PaperSelection],
    sort_order: SortOrder,
    session_cache: dict,
    progress_callback=None,
) -> tuple[io.BytesIO, list[str]]:
    """
    Merges selected QPs into a single PDF.

    Returns:
        (BytesIO of merged PDF, list of warning messages for missing files)
    """
    sorted_papers = sort_papers(papers, sort_order)
    output = pikepdf.Pdf.new()
    warnings: list[str] = []
    current_group = None

    for i, paper in enumerate(sorted_papers):
        if progress_callback:
            progress_callback(i, len(sorted_papers), str(paper))

        gk = group_key(paper, sort_order)

        # Insert section divider when group changes
        if gk != current_group:
            group_papers = [p for p in sorted_papers if group_key(p, sort_order) == gk]
            divider = make_divider_page(gk, group_papers)
            output.pages.append(divider)
            # Divider is always 1 page — add blank to keep even
            output.pages.append(make_blank_page())
            current_group = gk

        # Fetch PDF
        pdf_buf = fetch_pdf(paper.url, session_cache)

        if pdf_buf is None:
            warnings.append(f"Missing: {paper.filename}")
            ph = make_placeholder_page(paper)
            output.pages.append(ph)
            output.pages.append(make_blank_page())  # keep even
            continue

        try:
            src = pikepdf.open(pdf_buf)
        except pikepdf.PdfError as e:
            warnings.append(f"Corrupt PDF skipped: {paper.filename} ({e})")
            continue

        for page in src.pages:
            output.pages.append(output.copy_foreign(page))

        # Odd-page fix for double-sided printing
        if len(src.pages) % 2 != 0:
            output.pages.append(make_blank_page())

    result_buf = io.BytesIO()
    output.save(result_buf)
    result_buf.seek(0)
    return result_buf, warnings
