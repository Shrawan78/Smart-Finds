/* base.js — Smart Finds: shared JS for header/footer */

// Category dropdown toggle (also handled inline in header.html,
// this file is a safety fallback and adds keyboard accessibility)
document.addEventListener('DOMContentLoaded', function () {

  // ── Close dropdowns on outside click ──
  document.addEventListener('click', function (e) {
    const catMenu = document.getElementById('catMenu');
    const catDrop = document.getElementById('catDropdown');
    if (catMenu && catDrop && !catDrop.contains(e.target)) {
      catMenu.classList.remove('open');
    }
  });

  // ── Cart count badge: hide if 0 ──
  const badge = document.querySelector('.cart-count');
  if (badge && badge.textContent.trim() === '0') {
    badge.style.display = 'none';
  }

});
