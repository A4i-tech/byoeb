"""
Convert webpages (URLs) to plain text and save under raw_documents.

Reusable for any URL: run the script whenever you have a new URL; each URL
produces one .txt file in data/asha_bot/raw_documents (unique filename from URL).
Use for one URL, multiple URLs, or a file of URLs—same folder every time.

Mirrors the role of convert_pdf_to_txt.py: produce .txt files in the same
raw_documents folder used for PDF-derived text, so they can be loaded by the
legacy KB or uploaded to blob and ingested via kb_app.

Usage:
  - Output folder: repo/data/asha_bot/raw_documents (override with RAW_DOCUMENTS_DIR).
  - Pass one or more URLs as arguments, or use --urls-file <path> (one URL per line).
  - Install: poetry add requests beautifulsoup4 curl_cffi (from byoeb-v1/byoeb)
     or: pip install requests beautifulsoup4 curl_cffi
     (curl_cffi bypasses 403 on protected sites by impersonating Chrome.)

Examples (reusable for any new URL):
  python convert_webpage_to_txt.py https://example.com/page1
  python convert_webpage_to_txt.py https://example.com/page1 https://example.com/page2
  python convert_webpage_to_txt.py --urls-file data/asha_bot/raw_documents/urls.txt
  python convert_webpage_to_txt.py --no-proxy "https://site.org/article"   # if behind proxy
"""
import os
import re
import sys

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Install dependencies: pip install requests beautifulsoup4")
    sys.exit(1)

# Optional: use curl_cffi to bypass 403 on protected sites (impersonates Chrome)
try:
    from curl_cffi import requests as curl_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False


def url_to_safe_filename(url: str, max_length: int = 100) -> str:
    """Produce a safe filename from a URL (e.g. example_com_page)."""
    # Remove protocol and basic sanitization
    name = re.sub(r"^https?://", "", url)
    name = re.sub(r"[^\w\-.]", "_", name)
    name = name.strip("_")
    if len(name) > max_length:
        name = name[:max_length].rstrip("_")
    return name or "page"


_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}


def fetch_html(url: str, timeout: int = 30, no_proxy: bool = False) -> str:
    """Fetch HTML from URL. Uses curl_cffi (Chrome impersonation) when available to bypass 403."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"

    if _HAS_CURL_CFFI:
        # Impersonate Chrome TLS fingerprint; bypasses many 403/bot blocks
        kwargs = {"timeout": timeout, "impersonate": "chrome"}
        if no_proxy:
            kwargs["proxies"] = {"http": None, "https": None}
        resp = curl_requests.get(url, **kwargs)
    else:
        session = requests.Session()
        session.headers.update(_DEFAULT_HEADERS)
        session.headers["Referer"] = referer
        kwargs = {"timeout": timeout}
        if no_proxy:
            session.proxies = {"http": None, "https": None}
        resp = session.get(url, **kwargs)

    resp.raise_for_status()
    resp.encoding = getattr(resp, "encoding", None) or "utf-8"
    return resp.text


def html_to_text(html: str) -> str:
    """Extract main text from HTML; strip scripts, styles, nav."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    # Normalize whitespace
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n\n".join(lines)


def convert_webpage_to_txt(url: str, txt_path: str, timeout: int = 30, no_proxy: bool = False) -> None:
    """Fetch URL, extract text, write to txt_path."""
    html = fetch_html(url, timeout=timeout, no_proxy=no_proxy)
    text = html_to_text(html)
    os.makedirs(os.path.dirname(txt_path) or ".", exist_ok=True)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)


def _default_raw_documents_dir() -> str:
    """Default: repo root / data / asha_bot / raw_documents (script lives in repo/processing/)."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    return os.path.join(repo_root, "data", "asha_bot", "raw_documents")


def main():
    # Default: repo/data/asha_bot/raw_documents. Override with RAW_DOCUMENTS_DIR (for another bot use e.g. RAW_DOCUMENTS_DIR=.../science_bot/raw_documents).
    raw_dir = (os.environ.get("RAW_DOCUMENTS_DIR") or "").strip()
    txt_folder = os.path.abspath(raw_dir) if raw_dir else _default_raw_documents_dir()
    os.makedirs(txt_folder, exist_ok=True)
    print(f"Output folder: {os.path.abspath(txt_folder)}")

    no_proxy = "--no-proxy" in sys.argv
    args = [a for a in sys.argv[1:] if a not in ("--no-proxy",)]
    urls = []
    if "--urls-file" in args:
        idx = args.index("--urls-file")
        if idx + 1 < len(args):
            path = args[idx + 1]
            with open(path, "r", encoding="utf-8") as f:
                urls = [
                    line.strip()
                    for line in f
                    if line.strip() and not line.strip().startswith("#")
                ]
    else:
        urls = [a for a in args if a.startswith("http://") or a.startswith("https://")]

    if not urls:
        print("Usage: python convert_webpage_to_txt.py <URL> [URL ...]")
        print("       python convert_webpage_to_txt.py --urls-file <path>")
        print("Add --no-proxy if requests fail behind a proxy.")
        print("Each URL is scraped and saved as one .txt in the output folder (reusable for any new URL).")
        sys.exit(1)

    for url in urls:
        try:
            base = url_to_safe_filename(url)
            txt_path = os.path.join(txt_folder, base + ".txt")
            convert_webpage_to_txt(url, txt_path, no_proxy=no_proxy)
            print(f"Written: {txt_path}")
        except Exception as e:
            print(f"Error {url}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
