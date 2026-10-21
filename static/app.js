/**
 * Academic Weapon — Modern Interactive UI Behaviors
 * AUCA Academic Advising Center (AAC)
 */
(() => {
  'use strict';

  // --- Theme Management ---
  const getPreferredTheme = () => {
    try {
      const saved = localStorage.getItem('apss_theme');
      if (saved) return saved;
    } catch (e) {}
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light';
  };

  const applyTheme = (theme) => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem('apss_theme', theme);
    } catch (e) {}

    // Update aria attributes on theme buttons
    document.querySelectorAll('[data-theme-toggle], #themeToggle').forEach((btn) => {
      btn.setAttribute('aria-label', `Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`);
      btn.setAttribute('title', `Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`);
    });
  };

  // Bind all theme toggles (topbar and login screen)
  document.addEventListener('click', (e) => {
    const toggleBtn = e.target.closest('#themeToggle, [data-theme-toggle]');
    if (!toggleBtn) return;
    const current = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
    const next = current === 'dark' ? 'light' : 'dark';
    applyTheme(next);
  });

  // --- Mobile Sidebar Navigation Drawer ---
  const aside = document.getElementById('sidebar');
  const screen = document.getElementById('mobileScreen');
  const menuBtn = document.getElementById('menuBtn');

  const closeSidebar = () => {
    if (aside) aside.classList.remove('mobile-open');
    if (screen) screen.classList.remove('show');
  };

  const toggleSidebar = () => {
    if (!aside) return;
    const isOpen = aside.classList.toggle('mobile-open');
    if (screen) screen.classList.toggle('show', isOpen);
  };

  if (menuBtn) {
    menuBtn.addEventListener('click', toggleSidebar);
  }

  if (screen) {
    screen.addEventListener('click', closeSidebar);
  }

  // Close sidebar on escape key
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeSidebar();
  });

  // Close sidebar when navigating via link on mobile
  document.querySelectorAll('.main-nav a').forEach((link) => {
    link.addEventListener('click', closeSidebar);
  });

  // --- Quick Demo Account Selector (Login Page) ---
  document.querySelectorAll('[data-email][data-password]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const emailField = document.getElementById('email');
      const passField = document.getElementById('password');

      if (emailField) emailField.value = btn.dataset.email;
      if (passField) passField.value = btn.dataset.password;

      document.querySelectorAll('.demo-account').forEach((x) => x.classList.remove('selected'));
      btn.classList.add('selected');

      if (passField) passField.focus();
    });
  });

  // --- Weekly Check-in Advisor Booking Modal ---
  const modal = document.getElementById('advisorModal');
  const callout = document.getElementById('advisorCallout');
  const closeModalBtn = document.getElementById('closeAdvisorModal');

  const openAdvisorModal = () => {
    if (modal) modal.classList.add('open');
    if (callout) callout.style.display = 'flex';
  };

  const closeAdvisorModal = () => {
    if (modal) modal.classList.remove('open');
  };

  document.querySelectorAll('input[name="needs_help"]').forEach((radio) => {
    radio.addEventListener('change', () => {
      if (radio.checked && radio.value === 'yes') {
        openAdvisorModal();
      } else if (radio.checked && radio.value === 'no') {
        if (callout) callout.style.display = 'none';
        closeAdvisorModal();
      }
    });
  });

  if (closeModalBtn) {
    closeModalBtn.addEventListener('click', closeAdvisorModal);
  }

  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) closeAdvisorModal();
    });
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modal && modal.classList.contains('open')) {
      closeAdvisorModal();
    }
  });

  // Initial theme setup verification
  applyTheme(document.documentElement.dataset.theme || getPreferredTheme());
})();
