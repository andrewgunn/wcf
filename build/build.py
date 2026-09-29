"""Build the WCF prototype site from content.json into the repo root.

    .venv/bin/python extract.py   # once, after re-crawling
    .venv/bin/python build.py

Every internal link, image and PDF is rewritten to a local, relative path so
the site works on GitHub Pages (under /wcf/) and as a multi-file artifact.
"""
import hashlib
import html as htmllib
import io
import json
import os
import re
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag
from PIL import Image

HERE = Path(__file__).parent
SITE = HERE.parent
CACHE = HERE / "cache"
TPL = HERE / "templates"
CACHE.mkdir(exist_ok=True)

C = json.loads((HERE / "content.json").read_text())
for _d in C.values():
    _h = _d["html"].strip()
    if _h.startswith("<div>") and _h.endswith("</div>"):
        _d["html"] = _h[5:-6].strip()

# ---------------------------------------------------------------- routes

def route(path):
    path = urllib.parse.unquote(path).split("?")[0].rstrip("/") or "/"
    low = path.lower()
    if low == "/":
        return "index.html"
    if low.startswith("/blog/article/"):
        return "blog/" + path.split("/")[-1] + ".html"
    if low == "/blog/in-the-press":
        return "in-the-press.html"
    if low.startswith("/our-brands/"):
        return "our-brands/" + low.split("/")[-1] + ".html"
    return low.strip("/") + ".html"


PAGES = {route(p) for p in C}
PAGES.discard("cdn-cgi/l/email-protection.html")


def rel(target, page):
    """Relative URL from the page's folder to a site-root path."""
    if target.startswith(("http", "#", "mailto:", "tel:")):
        return target
    frag = ""
    if "#" in target:
        target, frag = target.split("#", 1)
        frag = "#" + frag
    return os.path.relpath(target, os.path.dirname(page) or ".") + frag

# ---------------------------------------------------------------- assets

ASSET_EXT = re.compile(r"\.(png|jpe?g|gif|webp|pdf)$", re.I)


def slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:60] or "file"


def fetch(url):
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    f = CACHE / key
    if f.exists():
        return f.read_bytes() if f.stat().st_size else None
    q = urllib.parse.quote(url, safe=":/?&=%#")
    try:
        data = urllib.request.urlopen(urllib.request.Request(q, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read()
    except Exception as e:
        print("  ! missing", url, e)
        data = b""
    f.write_bytes(data)
    return data or None


ASSETS = {}


def save_image(data, name, max_w=1600):
    im = Image.open(io.BytesIO(data))
    im.load()
    has_alpha = im.mode in ("RGBA", "LA", "P") and (
        im.mode != "P" or "transparency" in im.info
    )
    if has_alpha:
        im = im.convert("RGBA")
        if im.getextrema()[3][0] == 255:
            has_alpha = False
    if im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    out = SITE / "assets" / "img"
    out.mkdir(parents=True, exist_ok=True)
    if has_alpha:
        dest = f"assets/img/{name}.png"
        im.save(SITE / dest, "PNG", optimize=True)
    else:
        dest = f"assets/img/{name}.jpg"
        im.convert("RGB").save(SITE / dest, "JPEG", quality=80, optimize=True, progressive=True)
    return dest


def asset(url, max_w=1600):
    """Download a remote asset once; return its site-root path (or None)."""
    url = htmllib.unescape(url).strip()
    if url.startswith("//"):
        url = "https:" + url
    if url in ASSETS:
        return ASSETS[url]
    path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
    stem, ext = os.path.splitext(os.path.basename(path))
    data = fetch(url)
    dest = None
    if data:
        if ext.lower() == ".pdf":
            dest = f"assets/docs/{slug(stem)}.pdf"
            (SITE / "assets" / "docs").mkdir(parents=True, exist_ok=True)
            (SITE / dest).write_bytes(data)
        else:
            try:
                dest = save_image(data, f"{slug(stem)}-{hashlib.sha1(url.encode()).hexdigest()[:6]}", max_w)
            except Exception as e:
                print("  ! bad image", url, e)
    ASSETS[url] = dest
    return dest


def local_image(fname, name, max_w=1600):
    return save_image((CACHE / fname).read_bytes(), name, max_w)


def pdf_size(dest):
    n = (SITE / dest).stat().st_size
    return f"{n/1e6:.1f} MB" if n >= 1e6 else f"{max(1, round(n/1e3))} KB"

# ---------------------------------------------------------------- body cleanup

INLINE = {"a", "strong", "em", "br", "small", "sup", "sub", "b", "i"}
DECORATIVE = re.compile(r"icon|pig money|growth graph|pig big", re.I)


def decode_cf(hexstr):
    k = int(hexstr[:2], 16)
    return "".join(chr(int(hexstr[i:i + 2], 16) ^ k) for i in range(2, len(hexstr), 2))


def youtube_id(src):
    m = re.search(r"(?:embed/|v=|youtu\.be/)([\w-]{11})", src)
    return m.group(1) if m else None


PLAY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4.5v15l13-7.5z"/></svg>'


def video_card(soup, vid, page, label="Watch on YouTube"):
    thumb = asset(f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg", 800)
    a = soup.new_tag("a", href=f"https://www.youtube.com/watch?v={vid}", target="_blank", rel="noopener")
    a["class"] = "vid"
    a["aria-label"] = label
    if thumb:
        a.append(soup.new_tag("img", src=rel(thumb, page), alt="", loading="lazy"))
    a.append(BeautifulSoup(f"<span>{PLAY}</span>", "html.parser"))
    return a


def fix_links(root, page):
    for a in list(root.find_all("a")):
        href = htmllib.unescape(a.get("href", "")).strip()
        if "email-protection" in href:
            email = decode_cf(href.split("#", 1)[1]) if "#" in href else ""
            a["href"] = "mailto:" + email
            if "email" in a.get_text() and "protected" in a.get_text():
                a.string = email
            continue
        if href.startswith("mailto:"):
            if "protected" in a.get_text():
                a.string = href[7:]
            continue
        if href.startswith("javascript") or not href or not href.startswith(("http", "/", "#", "tel:")):
            a.unwrap()
            continue
        pr = urllib.parse.urlparse(href)
        if pr.netloc in ("www.wcf.co.uk", "wcf.co.uk"):
            if ASSET_EXT.search(pr.path):
                dest = asset(href)
                if dest:
                    a["href"] = rel(dest, page)
                else:
                    a.unwrap()
                continue
            r = route(pr.path)
            if r in PAGES:
                a["href"] = rel(r, page)
            else:
                a.unwrap()
            continue
        if href.startswith("http"):
            a["target"] = "_blank"
            a["rel"] = "noopener"


def rewrite(html, page, drop_decorative=True):
    soup = BeautifulSoup(f"<div>{html}</div>", "html.parser")
    root = soup.div
    while root.find("div"):
        for d in root.find_all("div"):
            d.unwrap()
    for h in root.find_all("h1"):
        h.decompose()
    fix_links(root, page)
    for img in list(root.find_all("img")):
        if drop_decorative and DECORATIVE.search(img.get("alt", "")):
            img.decompose()
            continue
        dest = asset(img.get("src", ""))
        if not dest:
            img.decompose()
            continue
        img["src"] = rel(dest, page)
        img["loading"] = "lazy"
        img["alt"] = img.get("alt", "")
    for f in list(root.find_all("iframe")):
        vid = youtube_id(f.get("src", ""))
        if vid:
            f.replace_with(video_card(soup, vid, page))
        else:
            f.decompose()
    # headings that are just <strong>
    for h in root.find_all(["h2", "h3", "h4"]):
        for s in h.find_all("strong"):
            s.unwrap()
        for b in h.find_all("br"):
            b.decompose()
        if not h.get_text(strip=True):
            h.decompose()
    # <p> holding only images or a single video -> unwrap
    for p in list(root.find_all("p")):
        kids = [k for k in p.contents if not (isinstance(k, NavigableString) and not k.strip())]
        if kids and all(isinstance(k, Tag) and (k.name == "img" or "vid" in (k.get("class") or [])) for k in kids):
            p.unwrap()
    # wrap loose inline runs in <p>
    run = []

    def flush():
        if not run:
            return
        text = "".join(str(x) for x in run).strip()
        if BeautifulSoup(text, "html.parser").get_text(strip=True):
            p = soup.new_tag("p")
            run[0].insert_before(p)
            for x in run:
                p.append(x.extract())
            while p.contents and isinstance(p.contents[0], Tag) and p.contents[0].name == "br":
                p.contents[0].decompose()
            while p.contents and isinstance(p.contents[-1], Tag) and p.contents[-1].name == "br":
                p.contents[-1].decompose()
        run.clear()

    for k in list(root.contents):
        if isinstance(k, NavigableString) or (isinstance(k, Tag) and k.name in INLINE):
            run.append(k)
        else:
            flush()
    flush()
    # group runs of images / videos
    def group(cls, test):
        kids = [k for k in root.contents if not (isinstance(k, NavigableString) and not k.strip())]
        i = 0
        while i < len(kids):
            j = i
            while j < len(kids) and test(kids[j]):
                j += 1
            if j - i >= 2:
                box = soup.new_tag("div")
                box["class"] = cls
                kids[i].insert_before(box)
                for k in kids[i:j]:
                    box.append(k.extract())
            i = max(j, i + 1)

    group("videos", lambda k: isinstance(k, Tag) and "vid" in (k.get("class") or []))
    group("pics", lambda k: isinstance(k, Tag) and k.name == "img")
    for t in root.find_all("table"):
        if not t.get_text(strip=True):
            t.decompose()
        else:
            w = soup.new_tag("div")
            w["class"] = "table-wrap"
            t.wrap(w)
    out = root.decode_contents()
    out = re.sub(r"<p>\s*</p>", "", out)
    return out.strip()


def text_of(html):
    return re.sub(r"\s+", " ", BeautifulSoup(html, "html.parser").get_text(" ")).strip()


def tidy(s):
    return re.sub(r"\s+", " ", s).strip()

# ---------------------------------------------------------------- chrome

NAV = [
    ("Businesses", "our-businesses.html", "biz"),
    ("Shareholders", "our-shareholders.html", "share"),
    ("Our Legacy", "our-legacy.html", "legacy"),
    ("Guiding Principles", "our-guiding-principles.html", "principles"),
    ("Blog", "blog.html", "blog"),
    ("In the Press", "in-the-press.html", "press"),
]
JOIN = ("Join Our Family", "recruitment.html", "join")

LOGO = None


def header(page, active):
    def item(label, href, key, cls=""):
        cur = ' aria-current="page"' if key == active else ""
        c = f' class="{cls}"' if cls else ""
        return f'<li><a{c} href="{rel(href, page)}"{cur}>{label}</a></li>'

    desktop = "".join(item(*n) for n in NAV) + item(*JOIN, cls="cta")
    mobile = "".join(item(*n) for n in NAV[:4]) + item(*JOIN) + "".join(item(*n) for n in NAV[4:])
    return f"""<div class="ribbon" id="ribbon">
  <div class="wrap">
    <span><b>Prototype.</b> This is a preview of the new WCF website, not the live site.</span>
    <button type="button" id="ribbon-close" aria-label="Hide prototype notice">Hide</button>
  </div>
</div>
<header class="site-header">
  <div class="wrap">
    <a class="logo" href="{rel('index.html', page)}" aria-label="WCF home"><img src="{rel(LOGO, page)}" alt="WCF" width="166" height="72"></a>
    <nav aria-label="Main"><ul class="nav">{desktop}</ul></nav>
    <button class="menu-btn" id="menu-btn" type="button" aria-expanded="false" aria-controls="mobile-nav" aria-label="Open menu">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path id="menu-icon" d="M4 7h16M4 12h16M4 17h16"/></svg>
    </button>
  </div>
  <div class="mobile-nav" id="mobile-nav" hidden><ul class="wrap">{mobile}</ul></div>
</header>"""


LI_SVG = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M4.98 3.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5zM3 9.5h4V21H3zM9.5 9.5h3.8v1.6h.1c.5-1 1.8-2 3.8-2 4 0 4.8 2.6 4.8 6V21h-4v-5.2c0-1.3 0-2.9-1.8-2.9s-2.1 1.4-2.1 2.8V21h-4z"/></svg>'
YT_SVG = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M23 7.2a3 3 0 0 0-2.1-2.1C19 4.6 12 4.6 12 4.6s-7 0-8.9.5A3 3 0 0 0 1 7.2 31 31 0 0 0 .6 12c0 1.6.1 3.2.4 4.8a3 3 0 0 0 2.1 2.1c1.9.5 8.9.5 8.9.5s7 0 8.9-.5a3 3 0 0 0 2.1-2.1c.3-1.6.4-3.2.4-4.8s-.1-3.2-.4-4.8zM9.8 15.1V8.9l5.8 3.1z"/></svg>'


def footer(page):
    L = lambda h: rel(h, page)
    return f"""<footer class="site-footer">
  <div class="wrap">
    <div class="f-grid">
      <div class="f-brand">
        <img src="{L(LOGO)}" alt="WCF" width="166" height="72">
        <address>WCF Ltd, Crawhall, Brampton<br>Cumbria CA8 1TN</address>
        <span>Tel <span class="tel">016977 45050</span></span>
        <div class="social">
          <a href="https://www.linkedin.com/company/78332694/" target="_blank" rel="noopener" aria-label="WCF on LinkedIn">{LI_SVG}</a>
          <a href="https://www.youtube.com/channel/UCbXpWMFx2p4FyB0z9fTUcsA/featured" target="_blank" rel="noopener" aria-label="WCF on YouTube">{YT_SVG}</a>
        </div>
      </div>
      <div>
        <h4>The family</h4>
        <ul>
          <li><a href="{L('our-businesses.html')}">Our businesses</a></li>
          <li><a href="{L('our-legacy.html')}">Our legacy</a></li>
          <li><a href="{L('our-guiding-principles.html')}">Guiding principles</a></li>
          <li><a href="{L('blog.html')}">Blog</a></li>
          <li><a href="{L('in-the-press.html')}">In the press</a></li>
        </ul>
      </div>
      <div>
        <h4>People</h4>
        <ul>
          <li><a href="{L('recruitment-wcf.html')}">Current vacancies</a></li>
          <li><a href="{L('working-for-wcf.html')}">Working for WCF</a></li>
          <li><a href="{L('recruitment-employee-owner.html')}">Being an employee owner</a></li>
          <li><a href="{L('our-shareholders.html')}">Shareholders</a></li>
          <li><a href="{L('our-board.html')}">Our board</a></li>
        </ul>
      </div>
      <div>
        <h4>Policies</h4>
        <ul>
          <li><a href="{L('cookie-policy.html')}">Cookie policy</a></li>
          <li><a href="{L('privacy-policy.html')}">Privacy policy</a></li>
          <li><a href="{L('policy-statements.html')}">Policy statements</a></li>
          <li><a href="{L('tax-strategy-statement.html')}">Tax strategy statement</a></li>
        </ul>
      </div>
    </div>
    <div class="f-base">
      <span>© WCF Ltd. Registered in England, no. 2263148</span>
      <span>An employee-owned company</span>
    </div>
  </div>
</footer>"""


def page(out, title, main, active=None, desc=""):
    doc_title = "WCF | Employee owned since 1911" if out == "index.html" else f"{title} | WCF"
    d = f'<meta name="description" content="{htmllib.escape(desc)}">\n' if desc else ""
    html = f"""<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex">
<title>{htmllib.escape(doc_title)}</title>
{d}<link rel="icon" href="{rel(FAVICON, out)}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@100..125,400..900&family=Figtree:ital,wght@0,400..700;1,400&display=swap">
<link rel="stylesheet" href="{rel('assets/css/site.css', out)}">
</head>
<body>
{header(out, active)}
<main>
{main}
</main>
{footer(out)}
<script src="{rel('assets/js/site.js', out)}"></script>
</body>
</html>
"""
    dest = SITE / out
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(html)
    BUILT.append(out)


def hero(page_out, title, crumbs, lede="", img=None, tag=""):
    cr = "".join(
        f'<li><a href="{rel(h, page_out)}">{htmllib.escape(t)}</a></li>' if h else f"<li>{htmllib.escape(t)}</li>"
        for t, h in [("Home", "index.html")] + crumbs
    )
    parts = f'<nav aria-label="Breadcrumb"><ol class="crumbs">{cr}</ol></nav>'
    if tag:
        parts += f'<span class="tag">{htmllib.escape(tag)}</span>'
    parts += f"<h1>{title}</h1>"
    if lede:
        parts += f'<p class="lede">{lede}</p>'
    if img:
        return f'<section class="page-hero has-img"><div class="wrap"><div class="hero-text">{parts}</div><div class="hero-img"><img src="{rel(img, page_out)}" alt=""></div></div></section>'
    return f'<section class="page-hero"><div class="wrap">{parts}</div></section>'


def aside(title, links, page_out):
    li = "".join(
        f'<li><a href="{rel(h, page_out)}"{" aria-current=\"page\"" if h == page_out else ""}>{htmllib.escape(t)}</a></li>'
        for t, h in links
    )
    return f'<aside class="aside"><h2>{title}</h2><ul>{li}</ul></aside>'


def body_with_aside(inner, side):
    return f'<section class="page-body"><div class="wrap with-aside"><div>{inner}</div>{side}</div></section>'


def body(inner):
    return f'<section class="page-body"><div class="wrap">{inner}</div></section>'


BUILT = []

# ---------------------------------------------------------------- shared data

IMG = {}
BUSINESSES = [
    ("pet-and-equestrian", "Pet & Equestrian", "pets",
     "Feed, equipment, clothing, animal health and toys for pet, equestrian, poultry, smallholder and wild bird customers, from 8 stores across Northern England and Southern Scotland. Our own premium dog and cat feeds include Lakes Heritage, our best-selling grain-free dog food."),
    ("camping-and-glamping", "Leisure", "leisure",
     "Three 5-star, dog-friendly camping and glamping sites: Herding Hill Farm on Hadrian's Wall, Drummohr near Edinburgh and Longnor Wood in the Peak District."),
    ("apparel", "Apparel", "apparel",
     "Mail order since 1989, with 4 clothing brands for the mature market: Country Collection, James Meade, The Classic Boutique and Bella di Notte. Designed in the UK and despatched from Brampton and Malton."),
    ("fuel-distribution", "Fuel Distribution", "fuel",
     "One of the top 10 independent fuel distributors in the UK, operating over 70 tankers from 13 depots through Allan Stobart, Chandlers and Easy Fuels."),
    ("ecommerce-fulfilment", "e-Commerce Fulfilment", "ecom",
     "A1 Lawn and Progreen Weed Control Solutions supply lawn and paddock seed, fertiliser, weedkiller and ground care to gardeners, landscapers and the amenity sector."),
]

SHARE_LINKS = [("Our Shareholders", "our-shareholders.html"), ("WCF Board", "our-board.html"),
               ("Financial statements", "financial-data.html"), ("Share information", "shareholders.html")]
JOIN_LINKS = [("Join Our Family", "recruitment.html"), ("Current vacancies", "recruitment-wcf.html"),
              ("Working for WCF", "working-for-wcf.html"), ("Being an employee owner", "recruitment-employee-owner.html"),
              ("Commitment to our people", "recruitment-commitment.html"), ("Insight to our people", "recruitment-culture.html"),
              ("Colleague testimonials", "recruitment-testimonials.html")]
POLICY_LINKS = [("Cookie policy", "cookie-policy.html"), ("Privacy policy", "privacy-policy.html"),
                ("Policy statements", "policy-statements.html"), ("Tax strategy statement", "tax-strategy-statement.html")]


def blog_posts():
    raw = (HERE / "source" / "blog.html").read_text()
    wrap = raw.split('id="blog-articles-wrapper"', 1)[1]
    seen, posts = set(), []
    for m in re.finditer(r'<a href="/blog/article/([^"]+)" title="([^"]*)">.*?background-image:url\(\'([^\']+)\'\)', wrap, re.S):
        s, title, thumb = m.groups()
        if s in seen:
            continue
        seen.add(s)
        d = C.get("/blog/article/" + s)
        if not d:
            continue
        posts.append({"slug": s, "title": htmllib.unescape(title).strip(), "thumb": thumb, "cat": d["category"] or "Our Employees", "out": f"blog/{s}.html"})
    # the featured banner post sits outside the list; it is the newest
    for path, d in C.items():
        s = path.rsplit("/", 1)[-1]
        if path.startswith("/blog/article/") and s not in seen and (HERE / "source" / f"blog__article__{s}.html").exists():
            m = re.search(r'href="/blog/article/' + re.escape(s) + r'".*?background-image:url\(\'([^\']+)\'\)', raw, re.S)
            posts.insert(0, {"slug": s, "title": d["h1"], "thumb": m.group(1) if m else "", "cat": d["category"] or "Our Employees", "out": f"blog/{s}.html"})
            seen.add(s)
    for p in posts:
        dest = asset(p["thumb"], 1000) if p["thumb"] else None
        if not dest:
            first = re.search(r'src="([^"]+\.(?:png|jpe?g))"', C["/blog/article/" + p["slug"]]["html"], re.I)
            dest = asset(first.group(1), 1000) if first else IMG["leisure"]
        p["img"] = dest
    return posts


def post_cards(posts, page_out, heading="h2"):
    out = []
    for p in posts:
        key = "employees" if p["cat"] == "Our Employees" else "press"
        out.append(
            f'<a class="post" href="{rel(p["out"], page_out)}" data-cat="{key}" data-title="{htmllib.escape(p["title"].lower())}">'
            f'<div class="ph"><img src="{rel(p["img"], page_out)}" alt="" loading="lazy"></div>'
            f'<div class="body"><span class="kind">{p["cat"]}</span><{heading}>{htmllib.escape(p["title"])}</{heading}></div></a>'
        )
    return "".join(out)

# ---------------------------------------------------------------- pages

def build_home(posts):
    out = "index.html"
    main = (TPL / "home-main.html").read_text()
    for k in ("pets", "leisure", "apparel", "fuel", "ecom", "legacy"):
        main = main.replace("{{" + k + "}}", rel(IMG[k], out))
    news = f"""<section class="section biz" id="news">
    <div class="wrap">
      <div class="latest-head"><h2>Latest news</h2><a class="text-link" href="blog.html">All blog posts</a></div>
      <div class="posts">{post_cards(posts[:3], out, "h3")}</div>
    </div>
  </section>"""
    main = main.replace("{{latest_news}}", news)
    soup = BeautifulSoup(main, "html.parser")
    fix_links(soup, out)
    # hero buttons and in-page links now point at real pages
    html = str(soup)
    html = html.replace('href="#businesses"', 'href="our-businesses.html"').replace('href="#join"', 'href="recruitment.html"')
    html = html.replace('<a class="video" href="https://www.youtube.com/watch?v=xKKotw8GHxA" rel="noopener" target="_blank">', '<a class="video" href="https://www.youtube.com/watch?v=xKKotw8GHxA" target="_blank" rel="noopener">')
    page(out, "Home", html, desc=C["/"]["description"])


def build_businesses():
    out = "our-businesses.html"
    rows = "".join(
        f"""<article class="biz-row">
  <div class="biz-photo"><img src="{rel(IMG[img], out)}" alt="" loading="lazy"></div>
  <div class="biz-text"><h2>{htmllib.escape(name)}</h2><p>{htmllib.escape(summary)}</p>
  <a class="text-link" href="{rel('our-brands/' + s + '.html', out)}">More about {htmllib.escape(name)}</a></div>
</article>"""
        for s, name, img, summary in BUSINESSES
    )
    main = hero(out, "Our Businesses", [("Businesses", None)],
                "WCF is an employee owned, private company operating a number of autonomous businesses focused on niche retailing and specialist distribution.")
    main += body(f'<div class="biz-rows">{rows}</div>')
    page(out, "Our Businesses", main, "biz", C["/our-businesses"]["description"])


QUOTE_START = re.compile(r'^\s*["“]')


def build_brand(s, name, img):
    src = C["/our-brands/" + s]
    out = f"our-brands/{s}.html"
    html = rewrite(src["html"], out)
    soup = BeautifulSoup(f"<div>{html}</div>", "html.parser")
    root = soup.div
    logos = []
    for a in list(root.find_all("a")):
        if a.find("img") and a.get("href", "").startswith("http"):
            im = a.find("img")
            logos.append(f'<a href="{a["href"]}" target="_blank" rel="noopener" aria-label="Visit {htmllib.escape(im.get("alt", ""))} website"><img src="{im["src"]}" alt="{htmllib.escape(im.get("alt", ""))}"></a>')
            a.decompose()
    quotes = []
    for p in list(root.find_all("p")):
        if QUOTE_START.match(p.get_text()) and len(p.get_text()) < 200:
            quotes.append(f"<li><p>{htmllib.escape(p.get_text(strip=True).strip('\"“”'))}</p></li>")
            p.decompose()
    awards = []
    for h3 in list(root.find_all("h3")):
        prev = h3.find_previous_sibling()
        nxt = h3.find_next_sibling()
        if prev is not None and (prev.name == "img" or (prev.name == "div" and prev.find("img"))):
            im = prev if prev.name == "img" else prev.find("img")
            awards.append(f'<li><img src="{im["src"]}" alt="{htmllib.escape(im.get("alt", ""))}" loading="lazy"><h3>{h3.get_text(strip=True)}</h3><p>{nxt.get_text(strip=True) if nxt is not None and nxt.name == "p" else ""}</p></li>')
            prev.decompose()
            if nxt is not None and nxt.name == "p":
                nxt.decompose()
            h3.decompose()
    for h in root.find_all("h2"):
        if "Meet Our Brands" in h.get_text():
            h.decompose()
    award_h2 = None
    for h in root.find_all("h2"):
        if "Award" in h.get_text():
            award_h2 = h.get_text(strip=True)
            h.decompose()
    # split long <br>-joined paragraphs
    body_html = re.sub(r"<br/?>", "</p><p>", root.decode_contents())
    body_html = re.sub(r"<p>\s*</p>", "", body_html)
    for pre in ("Click ",):
        body_html = re.sub(r"<p>Click <a[^>]*>HERE</a>[^<]*</p>", "", body_html)
    inner = ""
    if logos:
        inner += f'<div class="logos">{"".join(logos)}</div>'
    inner += f'<div class="prose">{body_html}</div>'
    if awards:
        inner += f'<h2 class="block-title">{award_h2 or "Awards"}</h2><ul class="awards">{"".join(awards)}</ul>'
    if quotes:
        inner += f'<h2 class="block-title">What customers say</h2><ul class="quotes">{"".join(quotes)}</ul>'
    side = aside("Our businesses", [(n, f"our-brands/{x}.html") for x, n, _, _ in BUSINESSES], out)
    main = hero(out, htmllib.escape(src["h1"] or name), [("Businesses", "our-businesses.html"), (name, None)], img=IMG[img])
    main += body_with_aside(inner, side)
    page(out, name, main, "biz", src["description"])


ICONS = {
    "board": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><circle cx="17.5" cy="9" r="2.5"/><path d="M17 14.2a5 5 0 0 1 4.5 4.8"/></svg>',
    "report": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3h9l4 4v14H6z"/><path d="M9 17v-3M12 17v-6M15 17v-4"/></svg>',
    "share": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 3v9l6.4 6.4"/></svg>',
    "search": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg>',
    "work": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 13h18"/></svg>',
    "owner": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21s-7-4.4-9.3-9A5.2 5.2 0 0 1 12 6.6 5.2 5.2 0 0 1 21.3 12C19 16.6 12 21 12 21z"/></svg>',
    "commit": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z"/><path d="M8.5 12.5l2.5 2.5 4.5-5"/></svg>',
    "video": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="14" height="14" rx="2"/><path d="M17 10l4-2v8l-4-2"/></svg>',
    "quote": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 5h16v11H9l-5 4z"/></svg>',
}


def hub(cards, out):
    return '<div class="hub">' + "".join(
        f'<a href="{rel(h, out)}"><span class="ic">{ICONS[i]}</span><h2>{t}</h2><p>{d}</p></a>' for t, h, i, d in cards
    ) + "</div>"


def build_shareholders_hub():
    out = "our-shareholders.html"
    main = hero(out, "Our Shareholders", [("Shareholders", None)],
                "Many employee owners remain shareholders of WCF long after their employment has ceased, supporting our sustainable growth for future generations.")
    main += body(hub([
        ("WCF Board", "our-board.html", "board", "Our executive directors and non-executive chair."),
        ("Financial Statements", "financial-data.html", "report", "Annual reports and financial statements from 2019 onwards."),
        ("Share Information", "shareholders.html", "share", "Dealing days, the current share price, dividend history and how to contact the Share Registrar."),
    ], out))
    page(out, "Our Shareholders", main, "share", C["/our-shareholders"]["description"])


def build_board():
    out = "our-board.html"
    soup = BeautifulSoup(f"<div>{C['/our-board']['html']}</div>", "html.parser")
    fix_links(soup.div, out)
    groups, cur, person = [], None, None
    for node in soup.div.children:
        if isinstance(node, NavigableString):
            if person is not None and node.strip() and not person["role"]:
                person["role"] = tidy(node)
            continue
        if node.name == "h2":
            cur = {"title": node.get_text(strip=True), "people": []}
            groups.append(cur)
        elif node.name == "a" and node.find("img"):
            im = node.find("img")
            person = {"img": asset(im["src"], 600), "li": node.get("href"), "name": "", "role": "", "bio": []}
            cur["people"].append(person)
        elif node.name == "strong" and person is not None:
            person["name"] = tidy(node.get_text())
        elif node.name == "p" and person is not None and node.get_text(strip=True):
            person["bio"].append(tidy(node.get_text()))
    html = ""
    for g in groups:
        cards = ""
        for p in g["people"]:
            bio = "".join(f"<p>{htmllib.escape(b)}</p>" for b in p["bio"])
            role = f'<p class="role">{htmllib.escape(p["role"])}</p>' if p["role"] else ""
            cards += f"""<article class="person"><img src="{rel(p['img'], out)}" alt="{htmllib.escape(p['name'])}" loading="lazy">
<div><h3>{htmllib.escape(p['name'])}</h3>{role}<div class="bio">{bio}</div>
<a class="li" href="{p['li']}" target="_blank" rel="noopener">{htmllib.escape(p['name'])} on LinkedIn</a></div></article>"""
        html += f'<section class="board-group"><h2>{htmllib.escape(g["title"])}</h2><div class="people">{cards}</div></section>'
    main = hero(out, "Our Board", [("Shareholders", "our-shareholders.html"), ("Our Board", None)], htmllib.escape(C["/our-board"]["description"].split("!")[0]) + ".")
    main += body(html)
    page(out, "Our Board", main, "share", C["/our-board"]["description"])


def build_financial():
    out = "financial-data.html"
    soup = BeautifulSoup(f"<div>{C['/financial-data']['html']}</div>", "html.parser")
    items = []
    for h2 in soup.find_all("h2"):
        a = h2.find("a")
        prev = h2.find_previous_sibling("a")
        cover = asset(prev.find("img")["src"], 600) if prev and prev.find("img") else None
        doc = asset(a["href"])
        if not doc:
            continue
        label = tidy(h2.get_text())
        items.append(f'<li><a href="{rel(doc, out)}" target="_blank"><div class="cover">{f"<img src=\"{rel(cover, out)}\" alt=\"\" loading=\"lazy\">" if cover else ""}</div><b>{label}</b><small>PDF, {pdf_size(doc)}</small></a></li>')
    main = hero(out, "Financial Statements", [("Shareholders", "our-shareholders.html"), ("Financial Statements", None)],
                "Our annual reports and financial statements.")
    main += body(f'<ul class="reports">{"".join(items)}</ul>')
    page(out, "Financial Statements", main, "share", C["/financial-data"]["description"])


def build_share_info():
    out = "shareholders.html"
    soup = BeautifulSoup(f"<div>{C['/shareholders']['html']}</div>", "html.parser")
    fix_links(soup.div, out)
    rows = []
    for tr in soup.find_all("tr")[1:]:
        cells = [tidy(td.get_text()) for td in tr.find_all("td")]
        rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    price = re.search(r"£[\d.]+", soup.find(string=re.compile("current share price")).find_parent("p").get_text()).group(0)
    email = "shares@wcf.co.uk"
    for a in soup.find_all("a", href=re.compile("^mailto:")):
        email = a["href"][7:]
        break
    inner = f"""<div class="share-top">
  <div class="panel navy"><h2>Share Price</h2><p class="price">{price}</p><p class="muted">per share</p></div>
  <div class="panel"><h2>Dealing Days</h2><p class="muted">WCF have four quarterly dealing days per year. These are always the:</p>
    <ul><li>Last Friday in January</li><li>Last Friday in April</li><li>Last Friday in July</li><li>Last Friday in November</li></ul>
    <p class="muted">Share dealing instructions must be received 10 days before the dealing day.</p></div>
</div>
<div class="prose">
  <h2>Historic Share Prices &amp; Dividend per Share</h2>
  <p>Our most recent dividend and share price information.</p>
  <div class="table-wrap"><table class="data-table"><thead><tr><th>Financial year</th><th>Share price</th><th>Dividend</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
  <h2>Privacy Policy</h2>
  <p>Our Privacy Policy for Shareholders provides clear information on how we collect, use, handle and protect your personal information. <a href="{rel('privacy-policy.html', out)}">Read our privacy policy</a>.</p>
  <h2>Contact</h2>
  <p>Our Share Registrar can be contacted by email at <a href="mailto:{email}">{email}</a> or by post to Share Dept, WCF Ltd, Crawhall, Brampton CA8 1TN.</p>
  <p>Share Sale Forms are available by automatic return from emailing <a href="mailto:{email}">{email}</a>.</p>
</div>"""
    main = hero(out, "Share Information", [("Shareholders", "our-shareholders.html"), ("Share Information", None)])
    main += body_with_aside(inner, aside("Shareholders", SHARE_LINKS, out))
    page(out, "Share Information", main, "share", C["/shareholders"]["description"])


def build_policies():
    out = "policy-statements.html"
    soup = BeautifulSoup(f"<div>{C['/policy-statements']['html']}</div>", "html.parser")
    items = []
    for a in soup.find_all("a"):
        doc = asset(a["href"])
        if doc:
            items.append(f'<li><a href="{rel(doc, out)}" target="_blank"><span class="pdf">PDF</span><span>{tidy(a.get_text())}</span><small>{pdf_size(doc)}</small></a></li>')
    main = hero(out, "Policy Statements", [("Policy Statements", None)],
                "Our policies, responsibilities and statements.")
    main += body_with_aside(f'<ul class="docs">{"".join(items)}</ul>', aside("Policies", POLICY_LINKS, out))
    page(out, "Policy Statements", main, None, C["/policy-statements"]["description"])


def build_legacy():
    out = "our-legacy.html"
    html = rewrite(C["/our-legacy"]["html"], out)
    soup = BeautifulSoup(f"<div>{html}</div>", "html.parser")
    for img in soup.find_all("img"):
        img.decompose()
    for p in soup.find_all("p"):
        if p.find("small"):
            p.decompose()
    sig = None
    for p in soup.find_all("p"):
        if "Chief Executive Officer" in p.get_text():
            sig = p
    if sig:
        sig.decompose()
    paras = soup.div.decode_contents()
    inner = f"""<div class="legacy-grid">
  <div class="legacy-img"><img src="{rel(IMG['legacy'], out)}" alt="Collage of WCF history: fuel tankers, farm feeds, catalogues and horticulture"></div>
  <div class="prose">{paras}<p><strong>Phil Murray</strong><br>Chief Executive Officer</p></div>
</div>"""
    main = hero(out, "Our Legacy", [("Our Legacy", None)], "Our legacy, your future, today and tomorrow.")
    main += body(inner)
    page(out, "Our Legacy", main, "legacy", C["/our-legacy"]["description"])


def build_principles():
    out = "our-guiding-principles.html"
    home = (TPL / "home-main.html").read_text()
    cs = re.search(r'<ul class="cs">.*?</ul>\s*</li>\s*</ul>', home, re.S).group(0)
    intro = text_of(C["/our-guiding-principles"]["html"].split("<img")[0]).replace("responsibilty", "responsibility")
    main = hero(out, "Our Guiding Principles", [("Guiding Principles", None)], htmllib.escape(intro))
    main += f'<section class="section principles"><div class="wrap">{cs}</div></section>'
    page(out, "Our Guiding Principles", main, "principles", C["/our-guiding-principles"]["description"])


def build_recruitment_hub():
    out = "recruitment.html"
    lw = asset("https://www.wcf.co.uk/Assets/recruitment/LW_logo_LW employer only.png", 400)
    main = hero(out, "Join the WCF Family", [("Join Our Family", None)],
                "Proud to be a Real Living Wage Employer. Every employee owner has a real stake in our success and a role that makes a difference.")
    main += body(hub([
        ("Current Vacancies", "recruitment-wcf.html", "search", "Open roles across Pet &amp; Equestrian, Leisure, Apparel, Fuel Distribution and e-Commerce."),
        ("Working for WCF", "working-for-wcf.html", "work", "Why WCF is a special and unique place to work."),
        ("Being an Employee Owner", "recruitment-employee-owner.html", "owner", "What employee ownership means, and its financial and non-financial benefits."),
        ("Commitment to our People", "recruitment-commitment.html", "commit", "What we commit to as an employer, and what we ask of our employee owners."),
        ("Insight to our People", "recruitment-culture.html", "video", "Films from colleagues in fuel distribution, retail and leisure."),
        ("Colleague Testimonials", "recruitment-testimonials.html", "quote", "Our employee owners on what they love about the WCF family."),
    ], out) + (f'<p style="margin-top:32px"><img src="{rel(lw, out)}" alt="Living Wage Employer" style="height:88px;width:auto;border-radius:8px"></p>' if lw else ""))
    page(out, "Join Our Family", main, "join", C["/recruitment"]["description"])


def build_commitment():
    out = "recruitment-commitment.html"
    soup = BeautifulSoup(f"<div>{C['/recruitment-commitment']['html']}</div>", "html.parser")
    root = soup.div
    ps = []
    for k in root.children:
        if isinstance(k, NavigableString):
            if k.strip():
                ps.append(("p", tidy(k)))
        elif k.name in ("p", "h2"):
            ps.append((k.name, tidy(k.get_text())))
    # intro until the "reach their full potential by:" line
    intro, i = [], 0
    while i < len(ps):
        intro.append(ps[i][1])
        i += 1
        if ps[i - 1][1].endswith(":"):
            break
    first, second, outro, cur = [], [], [], None
    cur = first
    while i < len(ps):
        kind, t = ps[i]
        if kind == "h2":
            second_title = t
            cur = second
            i += 1
            continue
        if i + 1 < len(ps) and ps[i + 1][0] == "p" and len(ps[i + 1][1]) < 30 and len(t) > 30:
            cur.append((ps[i + 1][1], t))
            i += 2
            continue
        outro.append(t)
        i += 1
    card = lambda items: '<ul class="commit">' + "".join(f"<li><h3>{htmllib.escape(a)}</h3><p>{htmllib.escape(b)}</p></li>" for a, b in items) + "</ul>"
    lead = intro[0]
    inner = '<div class="prose">' + "".join(f"<p>{htmllib.escape(t)}</p>" for t in intro[1:]) + "</div>"
    inner += card(first)
    inner += f'<h2 class="block-title" style="margin-top:0">{htmllib.escape(second_title)}</h2>' + card(second)
    inner += '<div class="prose">' + "".join(f"<p>{htmllib.escape(t)}</p>" for t in outro) + "</div>"
    main = hero(out, "Our Commitment to our People", [("Join Our Family", "recruitment.html"), ("Commitment to our People", None)], htmllib.escape(lead) + ".")
    main += body(inner)
    page(out, "Commitment to our People", main, "join", C["/recruitment-commitment"]["description"])


def build_testimonials():
    out = "recruitment-testimonials.html"
    soup = BeautifulSoup(f"<div>{C['/recruitment-testimonials']['html']}</div>", "html.parser")
    ps = [tidy(p.get_text()) for p in soup.find_all("p") if p.get_text(strip=True)]
    items = []
    for i in range(0, len(ps) - 1, 2):
        q, who = ps[i].strip(' "“”'), ps[i + 1]
        items.append(f"<li><p>{htmllib.escape(q)}</p><cite>{htmllib.escape(who)}</cite></li>")
    main = hero(out, "Colleague Testimonials", [("Join Our Family", "recruitment.html"), ("Colleague Testimonials", None)],
                "Our employee owners on what they love most about being part of the WCF family.")
    main += body(f'<ul class="quotes long">{"".join(items)}</ul>')
    page(out, "Colleague Testimonials", main, "join", C["/recruitment-testimonials"]["description"])


def build_generic(path, out, title, crumbs, active, side, lede=""):
    src = C[path]
    html = src["html"]
    m = re.search(r"<h1>(.*?)</h1>", html, re.S)
    if m and not title:
        title = tidy(BeautifulSoup(m.group(1), "html.parser").get_text())
    title = title or src["h1"]
    inner = f'<div class="prose">{rewrite(html, out)}</div>'
    main = hero(out, htmllib.escape(title), crumbs + [(title, None)], lede)
    main += body_with_aside(inner, side) if side else body(inner)
    page(out, title, main, active, src["description"])


def strip_article_nav(html):
    """Drop the old 'Back To Articles' link and the trailing 'Next Article' teaser."""
    soup = BeautifulSoup(f"<div>{html}</div>", "html.parser")
    for a in soup.find_all("a"):
        if re.search(r"back to articles", a.get_text(), re.I):
            a.decompose()
    nxt = soup.find(string=re.compile(r"Next Article", re.I))
    if nxt:
        el = nxt
        while el.parent is not None and el.parent is not soup.div and el.parent.name not in ("div",):
            el = el.parent
        for sib in list(el.next_siblings):
            sib.extract()
        el.extract()
    return soup.div.decode_contents()


def build_blog(posts):
    out = "blog.html"
    filters = f"""<div class="filters" role="toolbar" aria-label="Filter posts">
  <button class="chip" type="button" data-filter="all" aria-pressed="true">All</button>
  <button class="chip" type="button" data-filter="employees" aria-pressed="false">Our Employees</button>
  <button class="chip" type="button" data-filter="press" aria-pressed="false">In the Press</button>
  <label class="search">{ICONS['search']}<input id="blog-search" type="search" placeholder="Search posts" aria-label="Search posts"></label>
</div>"""
    grid = f'<div class="posts featured" id="posts">{post_cards(posts, out)}</div><p class="empty" id="no-posts" hidden>No posts match your search.</p>'
    main = hero(out, "Blog", [("Blog", None)], "News and stories from across the WCF family.")
    main += body(filters + grid)
    page(out, "Blog", main, "blog", C["/blog"]["description"])

    out = "in-the-press.html"
    press = [p for p in posts if p["cat"] == "In the Press"]
    main = hero(out, "In the Press", [("Blog", "blog.html"), ("In the Press", None)], "WCF and our businesses in the news.")
    main += body(f'<div class="posts featured">{post_cards(press, out)}</div>')
    page(out, "In the Press", main, "press", C["/blog/in-the-press"]["description"])

    for i, p in enumerate(posts):
        out = p["out"]
        src = C["/blog/article/" + p["slug"]]
        art = strip_article_nav(src["html"])
        inner = f'<div class="prose">{rewrite(art, out, drop_decorative=False)}</div>'
        inner += f'<a class="back text-link" href="{rel("blog.html", out)}">Back to all posts</a>'
        others = [q for q in posts if q is not p][:6]
        side = aside("More stories", [(q["title"], q["out"]) for q in others], out)
        active = "press" if p["cat"] == "In the Press" else "blog"
        crumbs = [("Blog", "blog.html")] + ([("In the Press", "in-the-press.html")] if active == "press" else []) + [(p["title"], None)]
        main = hero(out, htmllib.escape(p["title"]), crumbs, tag=p["cat"])
        main += body_with_aside(inner, side)
        page(out, p["title"], main, active, src["description"])

# ---------------------------------------------------------------- run

def main():
    global LOGO, FAVICON
    for d in ("assets/img", "assets/docs", "blog", "our-brands"):
        shutil.rmtree(SITE / d, ignore_errors=True)
    (SITE / "assets" / "css").mkdir(parents=True, exist_ok=True)
    (SITE / "assets" / "js").mkdir(parents=True, exist_ok=True)
    (SITE / "assets/css/site.css").write_text((TPL / "home.css").read_text() + "\n" + (TPL / "inner.css").read_text())
    shutil.copy(TPL / "site.js", SITE / "assets/js/site.js")

    (SITE / "assets" / "img").mkdir(parents=True, exist_ok=True)
    shutil.copy(CACHE / "logo.png", SITE / "assets/img/logo.png")
    LOGO = FAVICON = "assets/img/logo.png"
    IMG.update({
        "pets": local_image("pets.jpg", "business-pet-equestrian"),
        "leisure": local_image("leisure.jpg", "business-leisure"),
        "apparel": local_image("apparel.jpg", "business-apparel"),
        "fuel": local_image("fuel.jpg", "business-fuel"),
        "ecom": local_image("ecom.jpg", "business-ecommerce"),
        "legacy": local_image("legacy.png", "legacy-collage", 900),
    })

    posts = blog_posts()
    build_home(posts)
    build_businesses()
    for s, name, img, _ in BUSINESSES:
        build_brand(s, name, img)
    build_shareholders_hub()
    build_board()
    build_financial()
    build_share_info()
    build_policies()
    build_legacy()
    build_principles()
    build_recruitment_hub()
    build_commitment()
    build_testimonials()
    for path, out, title in [
        ("/recruitment-wcf", "recruitment-wcf.html", "Current Vacancies"),
        ("/working-for-wcf", "working-for-wcf.html", ""),
        ("/recruitment-employee-owner", "recruitment-employee-owner.html", "Being an Employee Owner"),
        ("/recruitment-culture", "recruitment-culture.html", "An Insight to our Culture"),
    ]:
        build_generic(path, out, title, [("Join Our Family", "recruitment.html")], "join", aside("Join our family", JOIN_LINKS, out))
    for path, out, title in [
        ("/cookie-policy", "cookie-policy.html", "Cookie Policy"),
        ("/privacy-policy", "privacy-policy.html", "Privacy Policy"),
        ("/tax-strategy-statement", "tax-strategy-statement.html", "Tax Strategy Statement"),
    ]:
        build_generic(path, out, title, [], None, aside("Policies", POLICY_LINKS, out))
    build_blog(posts)

    missing = sorted(PAGES - set(BUILT))
    print(len(BUILT), "pages built;", "missing:", missing)


if __name__ == "__main__":
    main()
