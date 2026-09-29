# Building the prototype

The site is generated from a crawl of www.wcf.co.uk.

```sh
cd build
python3 -m venv .venv && .venv/bin/pip install beautifulsoup4 pillow
.venv/bin/python extract.py   # source/*.html -> content.json
.venv/bin/python build.py     # content.json + templates/ -> site in the repo root
```

- `source/` holds the crawled pages.
- `templates/` holds the shared CSS, JS and the homepage markup.
- `build.py` downloads every image and PDF once (cached in `cache/`) and rewrites all links to local relative paths.
