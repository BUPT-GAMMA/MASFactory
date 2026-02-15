from __future__ import annotations

import csv
import html
import io
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

import requests


_DEFAULT_MAX_TEXT_CHARS = 20_000
_DEFAULT_TIMEOUT_S = 30


def _find_repo_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError(f"Cannot locate repo root from: {start}")


_REPO_ROOT = _find_repo_root(Path(__file__).resolve())


def _is_path_safe(path: Path) -> bool:
    """Best-effort guardrails for tool-driven file reads."""
    parts = {p.lower() for p in path.parts}
    if ".git" in parts:
        return False
    if ".venv" in parts or "venv" in parts:
        return False
    if ".uv-cache" in parts:
        return False
    # Avoid common secret file patterns.
    name = path.name.lower()
    if name == ".env" or name.startswith(".env."):
        return False
    if name in {"api_keys.yaml", "secrets.json"}:
        return False
    return True


def _limit_text(text: str, max_chars: int) -> str:
    max_chars = max(1, int(max_chars))
    if len(text) <= max_chars:
        return text
    head = text[: max_chars // 2]
    tail = text[-max_chars // 2 :]
    return head + "\n...\n" + tail


def python_interpreter(code: str, timeout_s: int = _DEFAULT_TIMEOUT_S) -> str:
    """Run a Python snippet and return stdout/stderr.

    Args:
        code: Python code to execute.
        timeout_s: Timeout in seconds.

    Returns:
        A text report with exit code, stdout, and stderr.
    """
    timeout_s = max(1, int(timeout_s))
    env = os.environ.copy()
    # Do not expose API keys to the executed snippet.
    for k in list(env.keys()):
        if "API_KEY" in k or k in {"OPENAI_API_KEY", "TOOL_OPENAI_API_KEY"}:
            env.pop(k, None)

    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(_REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        out = (
            f"EXIT_CODE: {proc.returncode}\n"
            f"STDOUT:\n{_limit_text(stdout, _DEFAULT_MAX_TEXT_CHARS)}\n"
            f"STDERR:\n{_limit_text(stderr, _DEFAULT_MAX_TEXT_CHARS)}"
        )
        return out.strip()
    except subprocess.TimeoutExpired:
        return f"ERROR: Timeout after {timeout_s}s"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:  # noqa: D401
        if data and data.strip():
            self._chunks.append(data.strip())

    def get_text(self) -> str:
        return "\n".join(self._chunks)


def web_fetch(url: str, max_chars: int = _DEFAULT_MAX_TEXT_CHARS) -> str:
    """Fetch a URL and return extracted text.

    Args:
        url: HTTP/HTTPS URL to fetch.
        max_chars: Max characters returned.

    Returns:
        A text summary of the fetched content.
    """
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return "ERROR: Only http/https URLs are supported."

        resp = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": "MASFactory-AgentVerse/1.0 (+https://github.com/OpenBMB/AgentVerse)"},
        )
        ctype = (resp.headers.get("content-type") or "").lower()
        content = resp.content[: 2 * _DEFAULT_MAX_TEXT_CHARS]  # hard cap bytes

        text = ""
        if "text/html" in ctype or content.lstrip().startswith(b"<!DOCTYPE") or b"<html" in content[:2048].lower():
            extractor = _HTMLTextExtractor()
            extractor.feed(content.decode(resp.encoding or "utf-8", errors="replace"))
            text = extractor.get_text()
        else:
            text = content.decode(resp.encoding or "utf-8", errors="replace")

        text = html.unescape(text)
        text = _limit_text(text, int(max_chars))
        return f"STATUS: {resp.status_code}\nURL: {url}\n\n{text}".strip()
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


def web_search(query: str, max_results: int = 5) -> str:
    """Search the web and return top results.

    Args:
        query: Search query.
        max_results: Maximum number of results.

    Returns:
        A plain-text list of results (title + URL).
    """
    max_results = max(1, min(int(max_results), 10))
    try:
        # DuckDuckGo HTML endpoint (no API key).
        resp = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": query},
            timeout=20,
            headers={"User-Agent": "MASFactory-AgentVerse/1.0"},
        )
        html_text = resp.text
        # Result links look like: /l/?kh=-1&uddg=<encoded_url>
        matches = re.findall(r'class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html_text)
        results: list[tuple[str, str]] = []
        for href, title_html in matches:
            title = re.sub(r"<[^>]+>", "", title_html)
            title = html.unescape(title).strip()
            url = href
            if href.startswith("/l/?"):
                q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                if "uddg" in q and q["uddg"]:
                    url = urllib.parse.unquote(q["uddg"][0])
                    # Some results may be missing scheme; skip those.
            if url.startswith("//"):
                url = "https:" + url
            if not url.startswith("http"):
                continue
            results.append((title or "(no title)", url))
            if len(results) >= max_results:
                break
        if not results:
            return "No results."
        lines = [f"{i+1}. {t}\n   {u}" for i, (t, u) in enumerate(results)]
        return "\n".join(lines)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


def ocr_image(
    path: str,
    lang: str = "eng",
    psm: int = 3,
    max_chars: int = _DEFAULT_MAX_TEXT_CHARS,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
) -> str:
    """OCR an image file to text (best-effort).

    Args:
        path: Image path (relative to repo root or absolute).
        lang: Tesseract language code (default: eng).
        psm: Tesseract page segmentation mode (default: 3).
        max_chars: Max characters returned.
        timeout_s: Timeout in seconds.

    Returns:
        OCR text or an error message if OCR is unavailable.
    """
    timeout_s = max(1, int(timeout_s))
    max_chars = max(1, int(max_chars))
    img_path = Path(path).expanduser()
    if not img_path.is_absolute():
        img_path = (_REPO_ROOT / img_path).resolve()

    try:
        img_path.relative_to(_REPO_ROOT)
    except Exception:
        return "ERROR: Path is outside repo root."

    if not _is_path_safe(img_path):
        return "ERROR: Path is not allowed."

    if not img_path.exists() or not img_path.is_file():
        return f"ERROR: File not found: {img_path}"

    tesseract = shutil.which("tesseract")
    if not tesseract:
        return "ERROR: OCR is unavailable (tesseract not installed)."

    try:
        proc = subprocess.run(
            [tesseract, str(img_path), "stdout", "-l", str(lang), "--psm", str(int(psm))],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        text = (proc.stdout or "").strip()
        if proc.returncode != 0 and not text:
            err = (proc.stderr or "").strip()
            return f"ERROR: tesseract failed (code {proc.returncode}): {err[:500]}"
        return _limit_text(text, max_chars)
    except subprocess.TimeoutExpired:
        return f"ERROR: OCR timeout after {timeout_s}s"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


@dataclass(frozen=True)
class _DocxText:
    paragraphs: list[str]

    def to_text(self) -> str:
        return "\n".join(p.strip() for p in self.paragraphs if p and p.strip())


def _extract_docx_text(docx_path: Path) -> _DocxText:
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(docx_path, "r") as zf:
        xml_bytes = zf.read("word/document.xml")

    root = ET.fromstring(xml_bytes)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

    paragraphs: list[str] = []
    for p in root.findall(".//w:p", ns):
        texts = [t.text for t in p.findall(".//w:t", ns) if t.text]
        if texts:
            paragraphs.append("".join(texts))
    return _DocxText(paragraphs=paragraphs)


def _extract_pptx_text(pptx_path: Path) -> str:
    import xml.etree.ElementTree as ET

    texts: list[str] = []
    with zipfile.ZipFile(pptx_path, "r") as zf:
        slide_names = sorted([n for n in zf.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")])
        for name in slide_names:
            try:
                xml_bytes = zf.read(name)
            except KeyError:
                continue
            root = ET.fromstring(xml_bytes)
            for node in root.iter():
                if node.tag.endswith("}t") and node.text:
                    texts.append(node.text)
    return "\n".join(t.strip() for t in texts if t and t.strip())


def _col_to_index(col: str) -> int:
    idx = 0
    for ch in col.upper():
        if not ("A" <= ch <= "Z"):
            break
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx


def _parse_cell_ref(cell_ref: str) -> tuple[int, int]:
    m = re.match(r"^([A-Za-z]+)(\d+)$", cell_ref)
    if not m:
        return 0, 0
    col_s, row_s = m.group(1), m.group(2)
    return int(row_s), _col_to_index(col_s)


def _extract_xlsx_text(xlsx_path: Path, *, max_rows: int = 50, max_cols: int = 20) -> str:
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(xlsx_path, "r") as zf:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            ss_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in ss_root.iter():
                if si.tag.endswith("}t") and si.text is not None:
                    shared_strings.append(si.text)

        sheet_xml = None
        for candidate in ("xl/worksheets/sheet1.xml",):
            if candidate in zf.namelist():
                sheet_xml = candidate
                break
        if sheet_xml is None:
            sheets = sorted([n for n in zf.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")])
            if sheets:
                sheet_xml = sheets[0]
        if sheet_xml is None:
            return "ERROR: No worksheets found in .xlsx"

        ws_root = ET.fromstring(zf.read(sheet_xml))

        cells: dict[tuple[int, int], str] = {}
        for c in ws_root.iter():
            if not c.tag.endswith("}c"):
                continue
            ref = c.attrib.get("r") or ""
            r_i, c_i = _parse_cell_ref(ref)
            if r_i <= 0 or c_i <= 0:
                continue
            if r_i > max_rows or c_i > max_cols:
                continue
            cell_type = c.attrib.get("t") or ""
            v = None
            for child in c:
                if child.tag.endswith("}v") and child.text is not None:
                    v = child.text
                    break
                if cell_type == "inlineStr" and child.tag.endswith("}is"):
                    # Inline string: find first <t>.
                    for tnode in child.iter():
                        if tnode.tag.endswith("}t") and tnode.text is not None:
                            v = tnode.text
                            break
            if v is None:
                continue
            if cell_type == "s":
                try:
                    v = shared_strings[int(v)]
                except Exception:
                    pass
            cells[(r_i, c_i)] = str(v)

        if not cells:
            return "No cell data found."

        max_r = max(r for r, _c in cells.keys())
        max_c = max(c for _r, c in cells.keys())
        max_r = min(max_r, max_rows)
        max_c = min(max_c, max_cols)

        lines: list[str] = []
        for r in range(1, max_r + 1):
            row = []
            for c in range(1, max_c + 1):
                row.append(cells.get((r, c), ""))
            lines.append("\t".join(row).rstrip())
        return "\n".join(lines).strip()


def read_file(path: str, max_bytes: int = 200_000) -> str:
    """Read a local file (best-effort extraction).

    Args:
        path: File path (relative to repo root or absolute).
        max_bytes: Max bytes to read from raw files.

    Returns:
        Extracted text, or an error message.
    """
    max_bytes = max(1, int(max_bytes))
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = (_REPO_ROOT / p).resolve()
    try:
        p.relative_to(_REPO_ROOT)
    except Exception:
        return "ERROR: Path is outside repo root."

    if not _is_path_safe(p):
        return "ERROR: Path is not allowed."

    if not p.exists():
        return f"ERROR: File not found: {p}"

    if p.is_dir():
        entries = sorted([x.name for x in p.iterdir()])[:200]
        return "DIRECTORY:\n" + "\n".join(entries)

    suffix = p.suffix.lower()
    try:
        if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"}:
            return ocr_image(str(p.relative_to(_REPO_ROOT)))

        if suffix == ".pdf":
            pdftotext = shutil.which("pdftotext")
            if not pdftotext:
                return "ERROR: PDF text extraction unavailable (pdftotext not installed)."
            proc = subprocess.run(
                [pdftotext, "-layout", "-nopgbrk", str(p), "-"],
                cwd=str(_REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0:
                err = (proc.stderr or "").strip()
                return f"ERROR: pdftotext failed (code {proc.returncode}): {err[:500]}"
            return _limit_text(proc.stdout or "", _DEFAULT_MAX_TEXT_CHARS)

        if suffix == ".docx":
            doc = _extract_docx_text(p)
            return _limit_text(doc.to_text(), _DEFAULT_MAX_TEXT_CHARS)

        if suffix == ".pptx":
            text = _extract_pptx_text(p)
            return _limit_text(text, _DEFAULT_MAX_TEXT_CHARS)

        if suffix == ".xlsx":
            text = _extract_xlsx_text(p)
            return _limit_text(text, _DEFAULT_MAX_TEXT_CHARS)

        if suffix == ".zip":
            with zipfile.ZipFile(p, "r") as zf:
                names = zf.namelist()
            preview = "\n".join(names[:200])
            return "ZIP CONTENTS:\n" + preview

        # Lightweight structured formats.
        if suffix in {".json", ".jsonl"}:
            raw = p.read_text(encoding="utf-8", errors="replace")
            if suffix == ".jsonl":
                lines = raw.splitlines()
                shown = "\n".join(lines[:200])
                return _limit_text(shown, _DEFAULT_MAX_TEXT_CHARS)
            obj = json.loads(raw)
            return _limit_text(json.dumps(obj, ensure_ascii=False, indent=2)[: _DEFAULT_MAX_TEXT_CHARS], _DEFAULT_MAX_TEXT_CHARS)

        if suffix == ".csv":
            with p.open("r", encoding="utf-8", errors="replace", newline="") as f:
                reader = csv.reader(f)
                rows = []
                for i, row in enumerate(reader):
                    rows.append(row)
                    if i >= 50:
                        break
            out = io.StringIO()
            w = csv.writer(out)
            w.writerows(rows)
            return _limit_text(out.getvalue(), _DEFAULT_MAX_TEXT_CHARS)

        # Default: raw text preview.
        data = p.read_bytes()[:max_bytes]
        text = data.decode("utf-8", errors="replace")
        return _limit_text(text, _DEFAULT_MAX_TEXT_CHARS)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


def gaia_tool_functions() -> list:
    """Return the tool function list for the GAIA Executor agent."""
    return [
        python_interpreter,
        read_file,
        ocr_image,
        web_search,
        web_fetch,
    ]
