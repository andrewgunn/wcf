"""Pull the main content out of each crawled wcf.co.uk page and clean it.

Writes one JSON file (content.json) keyed by original URL path, holding the
page title, h1, category (blog only) and cleaned body HTML. Asset URLs are
left absolute here; build.py downloads them and rewrites to local paths.
"""
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup, Comment, NavigableString

SRC = Path(__file__).parent / "source"
BASE = "https://www.wcf.co.uk"

KEEP_ATTRS = {"a": ["href"], "img": ["src", "alt"], "iframe": ["src"], "td": ["colspan", "rowspan"], "th": ["colspan", "rowspan"]}
UNWRAP = {"div", "span", "font", "section", "article", "center", "u", "grammarly-extension", "o:p", "label"}
DROP = {"script", "style", "noscript", "form", "input", "button", "select", "textarea", "svg", "link", "meta"}


def path_for(fname):
    stem = fname[:-5]
    return "/" if stem == "home" else "/" + stem.replace("__", "/")


def absolute(url):
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return BASE + url
    if url.startswith("http://www.wcf.co.uk") or url.startswith("http://wcf.co.uk"):
        return "https://www.wcf.co.uk" + url.split("wcf.co.uk", 1)[1]
    return url


def clean(node):
    for c in node.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    for t in node.find_all(DROP):
        t.decompose()
    # background-image divs (blog thumbnails) become real images
    for d in node.find_all(style=re.compile(r"background-image")):
        m = re.search(r"url\(['\"]?(.*?)['\"]?\)", d["style"])
        if m:
            img = node.new_tag("img", src=m.group(1), alt="")
            d.replace_with(img)
    for t in node.find_all(True):
        name = t.name.lower()
        if name in ("b",):
            t.name = "strong"
        if name in ("i",) and not t.get_text(strip=True):
            t.decompose()
            continue
        if name == "i":
            t.name = "em"
        if name == "em" and "fa" in " ".join(t.get("class", [])):
            t.decompose()
            continue
        keep = KEEP_ATTRS.get(t.name, [])
        t.attrs = {k: v for k, v in t.attrs.items() if k in keep}
        if t.name in ("a", "img", "iframe"):
            for k in ("href", "src"):
                if k in t.attrs:
                    t[k] = absolute(t[k])
    for t in node.find_all(UNWRAP):
        t.unwrap()
    for t in node.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        if t.name in ("h5", "h6"):
            t.name = "h4"
    html = str(node)
    html = html.replace("\xa0", " ").replace("&nbsp;", " ")
    html = re.sub(r"<br\s*/?>\s*(?=</(p|li|h\d)>)", "", html)
    html = re.sub(r"<p>\s*(<br\s*/?>\s*)*</p>", "", html)
    html = re.sub(r"(<br\s*/?>\s*){2,}", "<br>", html)
    html = re.sub(r"<(strong|em|a)>\s*</\1>", "", html)
    html = re.sub(r"[ \t\r\f\v]+", " ", html)
    html = re.sub(r"\n\s*\n+", "\n", html)
    return html.strip()


def extract(fname):
    raw = (SRC / fname).read_text()
    soup = BeautifulSoup(raw, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    meta = soup.find("meta", attrs={"name": "description"})
    desc = meta["content"].strip() if meta and meta.get("content") else ""
    header = soup.find("header")
    footer = soup.find("footer")
    # everything between header and footer
    parts = []
    for sib in header.next_siblings:
        if sib is footer:
            break
        parts.append(str(sib))
    body = BeautifulSoup("<div>" + "".join(parts) + "</div>", "html.parser").div
    for back in body.find_all("a", string=re.compile("Back To Articles", re.I)):
        back.decompose()
    for t in body.select("#newsletter-popup, .modal"):
        t.decompose()
    category = ""
    cat = body.select_one(".blog-inner-btn")
    if cat:
        category = cat.get_text(" ", strip=True)
        cat.decompose()
    h1 = body.find("h1")
    h1_text = h1.get_text(" ", strip=True) if h1 else ""
    if h1:
        h1.decompose()
    return {
        "path": path_for(fname),
        "title": title,
        "description": desc,
        "h1": h1_text,
        "category": category,
        "html": clean(body),
    }


if __name__ == "__main__":
    out = {}
    for f in sorted(SRC.glob("*.html")):
        d = extract(f.name)
        out[d["path"]] = d
    (Path(__file__).parent / "content.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(len(out), "pages")
