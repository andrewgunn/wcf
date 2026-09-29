(function () {
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
})();
