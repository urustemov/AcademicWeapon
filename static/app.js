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

  // --- Student notification bell ---
  const notificationCenter = document.querySelector('[data-notification-center]');
  const notificationToggle = document.querySelector('[data-notification-toggle]');

  const closeNotifications = () => {
    if (!notificationCenter || !notificationToggle) return;
    notificationCenter.classList.remove('open');
    notificationToggle.setAttribute('aria-expanded', 'false');
  };

  if (notificationCenter && notificationToggle) {
    notificationToggle.addEventListener('click', (e) => {
      e.stopPropagation();
      const isOpen = notificationCenter.classList.toggle('open');
      notificationToggle.setAttribute('aria-expanded', String(isOpen));
    });
    notificationCenter.addEventListener('click', (e) => e.stopPropagation());
    document.addEventListener('click', closeNotifications);
  }

  // Close sidebar on escape key
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeSidebar();
      closeNotifications();
    }
  });

  // Close sidebar when navigating via link on mobile
  document.querySelectorAll('.main-nav a').forEach((link) => {
    link.addEventListener('click', closeSidebar);
  });

  // --- Live private and group chats ---
  const chatThread = document.querySelector('[data-chat-thread]');
  const chatForm = document.querySelector('[data-chat-form]');
  const chatInput = document.querySelector('[data-chat-input]');
  const chatCount = document.querySelector('[data-chat-count]');
  const chatLiveUrl = chatThread ? chatThread.dataset.chatLiveUrl : '';
  let chatLastMessageId = chatThread
    ? Math.max(0, ...[...chatThread.querySelectorAll('[data-chat-message-id]')]
      .map((row) => Number(row.dataset.chatMessageId) || 0))
    : 0;
  let chatPolling = false;

  if (chatThread) {
    chatThread.scrollTop = chatThread.scrollHeight;
  }

  const appendChatMessage = (message, forceScroll = false) => {
    if (!chatThread || !message || Number(message.id) <= chatLastMessageId) return;
    const wasNearBottom = chatThread.scrollHeight - chatThread.scrollTop - chatThread.clientHeight < 120;
    const emptyState = chatThread.querySelector('.chat-empty');
    if (emptyState) emptyState.remove();
    const previousLatest = chatThread.querySelector('#latest');
    if (previousLatest) previousLatest.removeAttribute('id');

    const row = document.createElement('div');
    row.className = `chat-message-row ${message.own ? 'own' : 'other'}`;
    row.dataset.chatMessageId = String(message.id);
    row.id = 'latest';

    const meta = document.createElement('div');
    meta.className = 'chat-message-meta';
    const sender = document.createElement('span');
    sender.textContent = message.sender_name;
    const timestamp = document.createElement('time');
    timestamp.dateTime = message.created_at;
    timestamp.textContent = message.created_label;
    meta.append(sender, timestamp);

    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble';
    bubble.textContent = message.body;
    row.append(meta, bubble);
    chatThread.append(row);
    chatLastMessageId = Number(message.id);

    if (wasNearBottom || forceScroll || message.own) {
      chatThread.scrollTop = chatThread.scrollHeight;
    }
  };

  const fetchChatMessages = async (forceScroll = false) => {
    if (!chatLiveUrl || chatPolling || document.hidden) return;
    chatPolling = true;
    try {
      const url = new URL(chatLiveUrl, window.location.origin);
      url.searchParams.set('after', String(chatLastMessageId));
      const response = await fetch(url, {
        credentials: 'same-origin',
        cache: 'no-store',
        headers: { Accept: 'application/json' },
      });
      if (response.status === 401) {
        window.location.assign('/login');
        return;
      }
      if (!response.ok) throw new Error(`Chat update failed: ${response.status}`);
      const payload = await response.json();
      (payload.messages || []).forEach((message) => appendChatMessage(message, forceScroll));
    } catch (error) {
      // A later poll retries automatically; keep the current conversation usable offline.
      console.warn(error);
    } finally {
      chatPolling = false;
    }
  };

  if (chatThread && chatLiveUrl) {
    window.setInterval(() => fetchChatMessages(false), 1500);
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) fetchChatMessages(true);
    });
  }

  if (chatInput && chatCount) {
    const updateChatCount = () => {
      chatCount.textContent = String(chatInput.value.length);
    };
    chatInput.addEventListener('input', updateChatCount);
    chatInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && chatForm) {
        e.preventDefault();
        if (chatInput.reportValidity()) chatForm.requestSubmit();
      }
    });
    updateChatCount();
  }

  if (chatForm && chatInput && chatLiveUrl) {
    chatForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!chatInput.reportValidity()) return;
      const submitButton = chatForm.querySelector('button[type="submit"]');
      if (submitButton) submitButton.disabled = true;
      try {
        const response = await fetch(chatForm.action, {
          method: 'POST',
          body: new FormData(chatForm),
          credentials: 'same-origin',
          headers: { Accept: 'application/json', 'X-Chat-Live': '1' },
        });
        if (response.status === 401) {
          window.location.assign('/login');
          return;
        }
        if (!response.ok) throw new Error(`Message could not be sent: ${response.status}`);
        chatInput.value = '';
        chatInput.dispatchEvent(new Event('input'));
        await fetchChatMessages(true);
        chatInput.focus();
      } catch (error) {
        console.warn(error);
        window.alert('The message could not be sent. Please check your connection and try again.');
      } finally {
        if (submitButton) submitButton.disabled = false;
      }
    });
  }

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

  // --- Semester schedule course modal ---
  const courseModal = document.getElementById('courseModal');
  const courseForm = courseModal ? courseModal.querySelector('form') : null;
  const openCourseModal = () => {
    if (!courseModal) return;
    courseModal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
    const firstField = courseModal.querySelector('input:not([type="hidden"])');
    if (firstField) firstField.focus();
  };
  const closeCourseModal = () => {
    if (!courseModal) return;
    courseModal.style.display = 'none';
    document.body.style.overflow = '';
  };

  document.querySelectorAll('[data-open-course-modal]').forEach((button) => {
    button.addEventListener('click', openCourseModal);
  });
  document.querySelectorAll('[data-close-course-modal]').forEach((button) => {
    button.addEventListener('click', closeCourseModal);
  });
  if (courseModal) {
    courseModal.addEventListener('click', (e) => {
      if (e.target === courseModal) closeCourseModal();
    });
  }
  if (courseForm) {
    courseForm.addEventListener('submit', (e) => {
      const dayInputs = [...courseForm.querySelectorAll('input[name="days"]')];
      if (!dayInputs.some((input) => input.checked)) {
        e.preventDefault();
        dayInputs[0].setCustomValidity('Select at least one day of the week.');
        dayInputs[0].reportValidity();
      }
    });
    courseForm.querySelectorAll('input[name="days"]').forEach((input) => {
      input.addEventListener('change', () => {
        courseForm.querySelectorAll('input[name="days"]').forEach((day) => day.setCustomValidity(''));
      });
    });
  }
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && courseModal && courseModal.style.display !== 'none') {
      closeCourseModal();
    }
  });

  // --- Collapsible message directories and instant local search ---
  document.querySelectorAll('[data-message-directory]').forEach((directory) => {
    const search = directory.querySelector('[data-message-search]');
    const items = [...directory.querySelectorAll('[data-message-item]')];
    const noResults = directory.querySelector('[data-message-no-results]');
    const resultCount = directory.querySelector('[data-message-result-count]');
    if (!search) return;

    const filterDirectory = () => {
      const query = search.value.trim().toLocaleLowerCase();
      let visible = 0;
      items.forEach((item) => {
        const haystack = (item.dataset.searchText || item.textContent).toLocaleLowerCase();
        const matches = !query || haystack.includes(query);
        item.hidden = !matches;
        if (matches) visible += 1;
      });
      if (noResults) noResults.hidden = visible !== 0;
      if (resultCount) resultCount.textContent = `${visible} shown`;
    };

    search.addEventListener('input', filterDirectory);
  });

  // Initial theme setup verification
  applyTheme(document.documentElement.dataset.theme || getPreferredTheme());
})();
