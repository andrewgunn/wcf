(function () {
  document.documentElement.classList.add('js');
  var still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var btn = document.getElementById('menu-btn'), nav = document.getElementById('mobile-nav'), icon = document.getElementById('menu-icon');
  if (btn && nav) {
    var set = function (open) {
      nav.hidden = !open;
      btn.setAttribute('aria-expanded', open);
      btn.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
      icon.setAttribute('d', open ? 'M6 6l12 12M18 6L6 18' : 'M4 7h16M4 12h16M4 17h16');
    };
    btn.addEventListener('click', function () { set(nav.hidden); });
    nav.addEventListener('click', function (e) { if (e.target.closest('a')) set(false); });
  }

  var rib = document.getElementById('ribbon');
  if (rib) {
    try { if (sessionStorage.getItem('wcf-ribbon') === 'hidden') rib.hidden = true; } catch (e) {}
    document.getElementById('ribbon-close').addEventListener('click', function () {
      rib.hidden = true;
      try { sessionStorage.setItem('wcf-ribbon', 'hidden'); } catch (e) {}
    });
  }

  // blog filters and search
  var grid = document.getElementById('posts');
  if (grid) {
    var chips = document.querySelectorAll('[data-filter]'), search = document.getElementById('blog-search'),
        empty = document.getElementById('no-posts'), filter = 'all';
    if (location.hash === '#employees' || location.hash === '#press') filter = location.hash.slice(1);
    var apply = function () {
      var q = (search.value || '').trim().toLowerCase(), shown = 0;
      grid.classList.toggle('featured', filter === 'all' && !q);
      grid.querySelectorAll('.post').forEach(function (p) {
        var ok = (filter === 'all' || p.dataset.cat === filter) && (!q || p.dataset.title.indexOf(q) !== -1);
        p.hidden = !ok;
        if (ok) shown++;
      });
      empty.hidden = shown > 0;
      chips.forEach(function (c) { c.setAttribute('aria-pressed', c.dataset.filter === filter); });
    };
    chips.forEach(function (c) { c.addEventListener('click', function () { filter = c.dataset.filter; apply(); }); });
    search.addEventListener('input', apply);
    apply();
  }
  // header goes solid once the hero has scrolled away
  var head = document.querySelector('.site-header.over'), stage = document.querySelector('.stage');
  if (head && stage) {
    var solid = function () { head.classList.toggle('solid', stage.getBoundingClientRect().bottom < head.offsetHeight + 8); };
    addEventListener('scroll', solid, { passive: true });
    solid();
  }

  // hero slideshow
  if (stage) {
    var slides = stage.querySelectorAll('.slide'), ticks = stage.querySelectorAll('.ticks i'),
        cap = document.getElementById('stage-cap'), pause = document.getElementById('stage-pause'),
        icon2 = document.getElementById('pause-icon'), MS = 6500, cur = 0, timer = null, paused = still;
    stage.style.setProperty('--slide-ms', MS + 'ms');
    var show = function (n) {
      cur = (n + slides.length) % slides.length;
      slides.forEach(function (s, i) { s.classList.toggle('is-on', i === cur); });
      ticks.forEach(function (t, i) { t.classList.remove('is-on'); t.classList.toggle('done', i < cur); });
      void stage.offsetWidth;
      if (ticks[cur]) ticks[cur].classList.add('is-on');
      cap.textContent = slides[cur].dataset.cap;
    };
    var run = function () { clearInterval(timer); if (!paused) timer = setInterval(function () { show(cur + 1); }, MS); };
    var setPaused = function (p) {
      paused = p;
      stage.classList.toggle('paused', p);
      pause.setAttribute('aria-pressed', p);
      pause.setAttribute('aria-label', p ? 'Play slideshow' : 'Pause slideshow');
      icon2.setAttribute('d', p ? 'M8 5v14l11-7z' : 'M7 5h3.5v14H7zM13.5 5H17v14h-3.5z');
      if (!p) show(cur);
      run();
    };
    pause.addEventListener('click', function () { setPaused(!paused); });
    document.addEventListener('visibilitychange', function () { if (document.hidden) clearInterval(timer); else run(); });
    setPaused(paused);
  }

  // business index: hover or focus a business to swap the picture
  var bix = document.getElementById('bix');
  if (bix) {
    var items = bix.querySelectorAll('.bix-item'), pics = bix.querySelectorAll('.bix-view img'), desc = document.getElementById('bix-desc');
    var pick = function (li) {
      var n = +li.dataset.img;
      items.forEach(function (x) { x.classList.toggle('is-on', x === li); });
      pics.forEach(function (x, i) { x.classList.toggle('is-on', i === n); });
      desc.textContent = li.querySelector('.bix-more p').textContent;
    };
    items.forEach(function (li) {
      li.addEventListener('mouseenter', function () { pick(li); });
      li.addEventListener('focusin', function () { pick(li); });
    });
  }

  // film: swap the poster for the YouTube player
  var play = document.getElementById('film-play');
  if (play) play.addEventListener('click', function () {
    var f = document.createElement('iframe');
    f.src = 'https://www.youtube-nocookie.com/embed/' + play.dataset.yt + '?autoplay=1&rel=0';
    f.title = 'WCF film';
    f.allow = 'autoplay; encrypted-media; picture-in-picture; fullscreen';
    f.allowFullscreen = true;
    play.parentNode.appendChild(f);
    play.remove();
    f.focus();
  });

  // gentle reveal as sections scroll into view
  var rev = document.querySelectorAll('.reveal');
  if (!still && 'IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } });
    }, { rootMargin: '0px 0px -8% 0px' });
    rev.forEach(function (r) { io.observe(r); });
  } else rev.forEach(function (r) { r.classList.add('in'); });
})();
