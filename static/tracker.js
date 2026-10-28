(() => {
  const root = document.querySelector('[data-tracker-root]');
  if (!root) return;

  const csrf = root.dataset.csrf || '';
  const configured = root.dataset.configured === '1';
  const connection = root.querySelector('[data-tracker-connection]');
  const alertBox = root.querySelector('[data-tracker-alert]');
  const toastBox = root.querySelector('[data-tracker-toast]');
  let bootstrap = null;
  let selectedStudent = null;
  let followupBucket = 'all';

  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  })[char]);

  const emptyRow = (columns, message) => `<tr><td colspan="${columns}" class="tracker-empty">${esc(message)}</td></tr>`;
  const statusClass = value => /resolved|closed/i.test(String(value || '')) ? 'closed' : 'open';
  const statusPill = value => `<span class="tracker-status ${statusClass(value)}">${esc(value || 'Open')}</span>`;

  function showAlert(message) {
    alertBox.textContent = message;
    alertBox.hidden = !message;
  }

  function toast(message, error = false) {
    toastBox.textContent = message;
    toastBox.classList.toggle('error', error);
    toastBox.hidden = false;
    window.clearTimeout(toastBox._timer);
    toastBox._timer = window.setTimeout(() => { toastBox.hidden = true; }, 3200);
  }

  function setLoading(loading) {
    root.classList.toggle('tracker-loading', loading);
  }

  async function api(path, options = {}) {
    const headers = {'Accept':'application/json', ...(options.headers || {})};
    if (options.body) {
      headers['Content-Type'] = 'application/json';
      headers['X-CSRF-Token'] = csrf;
    }
    const response = await fetch(path, {...options, headers, credentials:'same-origin'});
    let data = null;
    try { data = await response.json(); } catch (_) {}
    if (!response.ok) {
      throw new Error((data && data.detail) || 'AAC Tracker could not complete the request.');
    }
    return data;
  }

  function fillSelect(select, values, selected = '') {
    select.innerHTML = values.map(value => `<option value="${esc(value)}">${esc(value)}</option>`).join('');
    if (selected && values.includes(selected)) select.value = selected;
  }

  function renderBars(container, rows) {
    const data = Array.isArray(rows) ? rows : [];
    if (!data.length) {
      container.innerHTML = '<p class="tracker-empty">No data for this selection.</p>';
      return;
    }
    const max = Math.max(1, ...data.map(row => Number(row.value) || 0));
    container.innerHTML = data.map(row => {
      const value = Number(row.value) || 0;
      const height = Math.max(5, Math.round(value / max * 145));
      return `<div class="tracker-bar-item"><strong>${value}</strong><i style="height:${height}px"></i><span>${esc(row.label)}</span></div>`;
    }).join('');
  }

  function renderRanked(container, rows) {
    const data = Array.isArray(rows) ? rows : [];
    container.innerHTML = data.length ? data.map(row =>
      `<div><span>${esc(row.label)}</span><strong>${Number(row.value) || 0}</strong></div>`
    ).join('') : '<p class="tracker-empty">No data for this selection.</p>';
  }

  function renderDashboard(dashboard) {
    const data = dashboard || {};
    root.querySelectorAll('[data-metric]').forEach(element => {
      element.textContent = data[element.dataset.metric] ?? 0;
    });
    renderBars(root.querySelector('[data-advisor-bars]'), (data.byAdvisor || []).slice(0, 8));
    renderRanked(root.querySelector('[data-topic-list]'), (data.byTopic || []).slice(0, 8));
    const body = root.querySelector('[data-recent-visits]');
    const recent = data.recent || [];
    body.innerHTML = recent.length ? recent.map(visit => `<tr>
      <td>${esc(visit.date)}</td><td><strong>${esc(visit.studentName)}</strong><small>${esc(visit.studentId)}</small></td>
      <td>${esc(visit.program)}</td><td>${esc(visit.topic)}</td><td>${statusPill(visit.status)}</td>
    </tr>`).join('') : emptyRow(5, 'No advising visits recorded yet.');
  }

  function renderTopicOptions(topics) {
    root.querySelector('[data-topic-options]').innerHTML = topics.map((topic, index) =>
      `<label><input type="checkbox" name="topics" value="${esc(topic)}"><span>${esc(topic)}</span></label>`
    ).join('');
  }

  function showTab(name) {
    root.querySelectorAll('[data-tracker-tab]').forEach(button => button.classList.toggle('active', button.dataset.trackerTab === name));
    root.querySelectorAll('[data-tracker-view]').forEach(view => view.classList.toggle('active', view.dataset.trackerView === name));
    if (name === 'followups') loadFollowups();
    if (name === 'reports') loadReport();
  }

  root.querySelectorAll('[data-tracker-tab]').forEach(button => {
    button.addEventListener('click', () => showTab(button.dataset.trackerTab));
  });

  function studentResultButton(student, index) {
    return `<button type="button" data-student-index="${index}"><strong>${esc(student.name)}</strong><span>${esc(student.id)} · ${esc(student.program)} · Year ${esc(student.year)} · GPA ${esc(student.gpa || '—')}</span></button>`;
  }

  function bindStudentSearch(kind, onChoose) {
    const input = root.querySelector(`[data-student-search="${kind}"]`);
    const results = root.querySelector(`[data-search-results="${kind}"]`);
    let timer = null;
    input.addEventListener('input', () => {
      window.clearTimeout(timer);
      const query = input.value.trim();
      if (!query) { results.hidden = true; results.innerHTML = ''; return; }
      timer = window.setTimeout(async () => {
        try {
          const rows = await api(`/aac/tracker/api/students?q=${encodeURIComponent(query)}`);
          results.innerHTML = rows.length ? rows.map(studentResultButton).join('') : '<p class="tracker-empty">No students found.</p>';
          results.hidden = false;
          results.querySelectorAll('[data-student-index]').forEach(button => {
            button.addEventListener('click', () => {
              const student = rows[Number(button.dataset.studentIndex)];
              results.hidden = true;
              input.value = student.id;
              onChoose(student);
            });
          });
        } catch (error) { toast(error.message, true); }
      }, 220);
    });
  }

  function chooseVisitStudent(student) {
    selectedStudent = student;
    const card = root.querySelector('[data-selected-student]');
    card.innerHTML = `<span class="profile-avatar">${esc((student.name || '').split(/\s+/).slice(0,2).map(x => x[0]).join(''))}</span><div><strong>${esc(student.name)}</strong><span>${esc(student.id)} · ${esc(student.email)}</span><small>${esc(student.program)} · Year ${esc(student.year)} · GPA ${esc(student.gpa || '—')}</small></div>`;
    card.hidden = false;
  }

  async function loadProfile(studentId) {
    try {
      setLoading(true);
      const profile = await api(`/aac/tracker/api/student/${encodeURIComponent(studentId)}`);
      if (!profile.student) throw new Error('Student was not found.');
      const student = profile.student;
      const profileArea = root.querySelector('[data-student-profile]');
      root.querySelector('[data-profile-summary]').innerHTML = `<div><span class="section-overline">STUDENT PROFILE</span><h2>${esc(student.name)}</h2><p>${esc(student.id)} · ${esc(student.email)}</p></div><div class="tracker-profile-facts"><span><small>Program</small><strong>${esc(student.program)}</strong></span><span><small>Year</small><strong>${esc(student.year)}</strong></span><span><small>Current GPA</small><strong>${esc(student.gpa || '—')}</strong></span></div>`;
      root.querySelector('[data-profile-count]').textContent = profile.visits.length;
      root.querySelector('[data-profile-visits]').innerHTML = profile.visits.length ? profile.visits.map(visit => `<tr><td>${esc(visit.date)}</td><td>${esc(visit.advisor)}</td><td>${esc(visit.gpa || '—')}</td><td>${esc(visit.topic)}</td><td>${esc(visit.question)}</td><td>${esc(visit.action)}</td><td>${esc(visit.followUpDate || '—')}</td><td>${statusPill(visit.status)}</td></tr>`).join('') : emptyRow(8, 'No advising visits recorded for this student.');
      profileArea.hidden = false;
    } catch (error) { toast(error.message, true); }
    finally { setLoading(false); }
  }

  bindStudentSearch('visit', chooseVisitStudent);
  bindStudentSearch('profile', student => loadProfile(student.id));

  const followSelect = root.querySelector('[data-followup-select]');
  const followDate = root.querySelector('[data-followup-date]');
  followSelect.addEventListener('change', () => {
    followDate.disabled = followSelect.value !== 'Yes';
    followDate.required = followSelect.value === 'Yes';
    if (followDate.disabled) followDate.value = '';
  });

  const visitForm = root.querySelector('[data-visit-form]');
  visitForm.addEventListener('reset', () => {
    window.setTimeout(() => {
      selectedStudent = null;
      root.querySelector('[data-student-search="visit"]').value = '';
      root.querySelector('[data-selected-student]').hidden = true;
      followDate.disabled = true;
    }, 0);
  });
  visitForm.addEventListener('submit', async event => {
    event.preventDefault();
    if (!selectedStudent) { toast('Select a student first.', true); return; }
    const data = new FormData(visitForm);
    const payload = {
      advisor:data.get('advisor'), studentId:selectedStudent.id,
      topics:data.getAll('topics'), question:data.get('question'), action:data.get('action'),
      followUp:data.get('followUp'), followUpDate:data.get('followUpDate'),
      status:data.get('status'), notes:data.get('notes'),
    };
    try {
      setLoading(true);
      const result = await api('/aac/tracker/api/visit', {method:'POST', body:JSON.stringify(payload)});
      toast(`Visit saved to spreadsheet row ${result.row}.`);
      visitForm.reset();
      await refreshBootstrap();
      showTab('dashboard');
    } catch (error) { toast(error.message, true); }
    finally { setLoading(false); }
  });

  root.querySelectorAll('[data-followup-tabs] [data-bucket]').forEach(button => {
    button.addEventListener('click', () => {
      followupBucket = button.dataset.bucket;
      root.querySelectorAll('[data-followup-tabs] [data-bucket]').forEach(item => item.classList.toggle('active', item === button));
      loadFollowups();
    });
  });
  root.querySelector('[data-followup-advisor]').addEventListener('change', loadFollowups);

  async function loadFollowups() {
    if (!bootstrap) return;
    const advisor = root.querySelector('[data-followup-advisor]').value;
    const body = root.querySelector('[data-followup-body]');
    try {
      setLoading(true);
      const rows = await api(`/aac/tracker/api/followups?advisor=${encodeURIComponent(advisor)}&bucket=${encodeURIComponent(followupBucket)}`);
      body.innerHTML = rows.length ? rows.map(visit => `<tr><td>${esc(visit.followUpDate || '—')}</td><td><strong>${esc(visit.studentName)}</strong><small>${esc(visit.studentId)}</small></td><td>${esc(visit.program)}</td><td>${esc(visit.topic)}</td><td>${esc(visit.advisor)}</td><td>${statusPill(visit.status)}</td><td>${!['Closed','Resolved'].includes(visit.status) ? `<button class="mini-btn" type="button" data-resolve-row="${Number(visit.row)}">Resolve</button>` : ''}</td></tr>`).join('') : emptyRow(7, 'No follow-ups in this category.');
      body.querySelectorAll('[data-resolve-row]').forEach(button => button.addEventListener('click', () => resolveVisit(Number(button.dataset.resolveRow))));
    } catch (error) { body.innerHTML = emptyRow(7, error.message); }
    finally { setLoading(false); }
  }

  async function resolveVisit(row) {
    try {
      setLoading(true);
      await api(`/aac/tracker/api/visit/${row}/status`, {method:'POST', body:JSON.stringify({status:'Resolved'})});
      toast('Follow-up marked as resolved.');
      await Promise.all([loadFollowups(), refreshBootstrap()]);
    } catch (error) { toast(error.message, true); }
    finally { setLoading(false); }
  }

  const reportForm = root.querySelector('[data-report-form]');
  reportForm.addEventListener('submit', event => { event.preventDefault(); loadReport(); });
  async function loadReport() {
    if (!bootstrap) return;
    const params = new URLSearchParams(new FormData(reportForm));
    try {
      setLoading(true);
      const report = await api(`/aac/tracker/api/report?${params.toString()}`);
      root.querySelector('[data-report-total]').textContent = report.total ?? 0;
      root.querySelector('[data-report-unique]').textContent = report.uniqueStudents ?? 0;
      renderBars(root.querySelector('[data-report-program-bars]'), report.byProgram || []);
      renderBars(root.querySelector('[data-report-unique-program-bars]'), report.uniqueByProgram || []);
      renderBars(root.querySelector('[data-report-year-bars]'), report.byYear || []);
      renderRanked(root.querySelector('[data-report-gpa]'), report.gpaBands || []);
    } catch (error) { toast(error.message, true); }
    finally { setLoading(false); }
  }

  async function refreshBootstrap() {
    bootstrap = await api('/aac/tracker/api/bootstrap');
    renderDashboard(bootstrap.dashboard);
  }

  async function init() {
    if (!configured) {
      connection.textContent = 'Connection setup required';
      showAlert('The secure Google Sheets connection has not been configured yet.');
      return;
    }
    try {
      setLoading(true);
      await refreshBootstrap();
      const advisors = bootstrap.advisors || [];
      const statuses = bootstrap.statuses || [];
      fillSelect(root.querySelector('[data-visit-advisor]'), advisors, bootstrap.currentUser.advisor);
      fillSelect(root.querySelector('[data-visit-status]'), statuses, 'Resolved');
      fillSelect(root.querySelector('[data-followup-advisor]'), ['All Advisors', ...advisors], bootstrap.currentUser.advisor);
      fillSelect(root.querySelector('[data-report-advisor]'), ['All Advisors', ...advisors], 'All Advisors');
      fillSelect(root.querySelector('[data-report-program]'), ['All Programs', ...(bootstrap.programs || [])], 'All Programs');
      fillSelect(root.querySelector('[data-report-status]'), ['All Statuses', ...statuses], 'All Statuses');
      renderTopicOptions(bootstrap.topics || []);
      connection.textContent = 'Live spreadsheet connected';
      showAlert('');
    } catch (error) {
      connection.textContent = 'Connection unavailable';
      showAlert(error.message);
    } finally { setLoading(false); }
  }

  init();
})();
