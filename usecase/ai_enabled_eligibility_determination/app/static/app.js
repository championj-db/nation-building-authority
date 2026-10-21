/* Eligibility Review Workbench — client behaviour.
 * Interactions ported from design/eligibility-review-workbench.html (tabs, filters,
 * search, case selection, decision dialog, toast) and wired to the FastAPI backend.
 */
(() => {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const state = {
    queue: [],
    filter: 'all',
    search: '',
    selectedId: null,
    caseData: null,
    policies: null,
    loadingCase: 0,
  };

  // ------------------------------------------------------------------ API
  async function api(path, options = {}) {
    const res = await fetch(path, {
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      ...options,
    });
    let body = null;
    try { body = await res.json(); } catch (_) { /* non-JSON */ }
    if (!res.ok) {
      const detail = body && body.detail;
      const message = Array.isArray(detail) ? detail.map((d) => d.msg).join('; ') : (detail || `Request failed (${res.status})`);
      const err = new Error(message);
      err.status = res.status;
      err.code = body && body.code;
      throw err;
    }
    return body;
  }

  // ------------------------------------------------------------------ Formatting
  const fmtDateTime = (iso) => {
    if (!iso) return '';
    const d = new Date(String(iso).replace(' ', 'T'));
    if (Number.isNaN(d.getTime())) return esc(iso);
    return `${d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })} · ${d.toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit', hour12: false })}`;
  };
  const fmtTime = (iso) => {
    const d = new Date(String(iso || '').replace(' ', 'T'));
    return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit', hour12: false });
  };

  function pillFor(tokens, decision) {
    if (decision) return { cls: 'decided', text: 'Decided' };
    if (tokens.includes('urgent')) return { cls: 'urgent', text: 'Urgent' };
    if (tokens.includes('borderline')) return { cls: '', text: 'Borderline' };
    if (tokens.includes('ready')) return { cls: 'ready', text: 'Ready' };
    if (tokens.includes('declined')) return { cls: 'declined', text: 'Declined' };
    return { cls: '', text: 'Review' };
  }

  function detailPill(c) {
    const latest = c.decisions && c.decisions[0];
    if (latest) return { cls: 'decided', text: `Decided · ${latest.outcome}` };
    if (c.status_tokens.includes('urgent')) return { cls: 'urgent', text: 'Action due today' };
    if (c.status_tokens.includes('borderline')) return { cls: '', text: 'Review required' };
    if (c.status_tokens.includes('ready')) return { cls: 'ready', text: 'Ready for approval' };
    if (c.status_tokens.includes('declined')) return { cls: 'declined', text: 'Rules not met' };
    return { cls: '', text: 'Review' };
  }

  // ------------------------------------------------------------------ Toast & banners
  let toastTimer;
  function toast(message, isError = false) {
    const el = $('#toast');
    el.textContent = message;
    el.classList.toggle('error', isError);
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), 2600);
  }
  function banner(el, message, isError = false) {
    if (!message) { el.hidden = true; return; }
    el.textContent = message;
    el.classList.toggle('error', isError);
    el.hidden = false;
  }

  // ------------------------------------------------------------------ Routing
  function route() {
    const [, view = 'queue', id] = (location.hash || '#/queue').split('/');
    const name = ['queue', 'policies', 'audit'].includes(view) ? view : 'queue';
    $$('.view').forEach((v) => { v.hidden = v.id !== `view-${name}`; });
    $$('.nav-link').forEach((a) => a.classList.toggle('active', a.dataset.view === name));
    $('#mobile-nav').value = name;
    if (name === 'policies') loadPolicies();
    if (name === 'audit') loadAudit();
    if (name === 'queue' && id && id !== state.selectedId) selectCase(decodeURIComponent(id), false);
  }
  window.addEventListener('hashchange', route);
  $('#mobile-nav').addEventListener('change', (e) => { location.hash = `#/${e.target.value}`; });

  // ------------------------------------------------------------------ Identity
  async function loadMe() {
    try {
      const me = await api('/api/me');
      const badge = $('#user-badge');
      badge.textContent = me.initials;
      badge.title = `${me.display_name} · ${me.email}`;
      badge.setAttribute('aria-label', `Signed in as ${me.display_name}`);
      if (me.environment && me.environment !== 'prod') {
        $('#environment').textContent = `Protected · Casework · ${me.environment}`;
      }
    } catch (err) {
      $('#user-badge').title = err.message;
    }
  }

  // ------------------------------------------------------------------ Queue
  async function loadQueue() {
    const list = $('#case-list');
    list.setAttribute('aria-busy', 'true');
    try {
      const data = await api('/api/queue');
      state.queue = data.items;
      banner($('#queue-banner'), data.lakebase_error ? `Decision status is temporarily unavailable (${data.lakebase_error}). Case data is still shown.` : '');
      renderQueue();
      if (!state.selectedId && state.queue.length && !location.hash.split('/')[2]) {
        selectCase(state.queue[0].application_id);
      }
    } catch (err) {
      state.queue = [];
      const notReady = err.code === 'DATA_NOT_READY';
      list.innerHTML = `<div class="state-block"><h3>${notReady ? 'Queue not available yet' : 'Could not load the queue'}</h3><p>${esc(err.message)}</p><button class="btn" type="button" id="retry-queue">Retry</button></div>`;
      $('#retry-queue').addEventListener('click', loadQueue);
      $('#case-count').textContent = '0 cases';
    } finally {
      list.setAttribute('aria-busy', 'false');
    }
  }

  function renderQueue() {
    const list = $('#case-list');
    const q = state.search.trim().toLowerCase();
    const visible = state.queue.filter((c) => {
      const matchesFilter = state.filter === 'all' || c.status_tokens.includes(state.filter);
      const matchesSearch = !q || `${c.full_name} ${c.application_id}`.toLowerCase().includes(q);
      return matchesFilter && matchesSearch;
    });
    $('#case-count').textContent = `${visible.length} ${visible.length === 1 ? 'case' : 'cases'}`;
    if (!visible.length) {
      list.innerHTML = `<div class="state-block"><h3>No matching cases</h3><p>${state.queue.length ? 'Try a different search or filter.' : 'The queue is empty.'}</p></div>`;
      return;
    }
    list.innerHTML = visible.map((c) => {
      const pill = pillFor(c.status_tokens, c.decision);
      return `<button class="case-card${c.application_id === state.selectedId ? ' active' : ''}" type="button" data-id="${esc(c.application_id)}" aria-pressed="${c.application_id === state.selectedId}">
        <span class="case-topline"><span class="case-name">${esc(c.full_name)}</span><span class="pill ${pill.cls}">${esc(pill.text)}</span></span>
        <span class="case-summary">${esc(c.summary)}${c.decision ? ` · ${esc(c.decision.outcome)}` : ''}</span>
      </button>`;
    }).join('');
  }

  $('#case-list').addEventListener('click', (e) => {
    const card = e.target.closest('.case-card[data-id]');
    if (card) selectCase(card.dataset.id);
  });
  $('#case-search').addEventListener('input', (e) => { state.search = e.target.value; renderQueue(); });
  $$('.filter').forEach((f) => f.addEventListener('click', () => {
    state.filter = f.dataset.filter;
    $$('.filter').forEach((x) => x.classList.toggle('active', x === f));
    renderQueue();
  }));
  $('#export-queue').addEventListener('click', () => { window.location.href = '/api/queue/export'; });

  // ------------------------------------------------------------------ Case detail
  function showPanel(name) {
    $$('.tab').forEach((tab) => {
      const active = tab.dataset.panel === name;
      tab.classList.toggle('active', active);
      tab.setAttribute('aria-selected', String(active));
    });
    $$('.panel').forEach((p) => p.classList.toggle('active', p.id === `panel-${name}`));
  }
  $$('.tab').forEach((tab) => tab.addEventListener('click', () => showPanel(tab.dataset.panel)));

  function detailLoading() {
    $('#detail-empty').hidden = true;
    $('#detail-body').hidden = false;
    $('#d-name').innerHTML = '<span class="skeleton w-40" style="height:22px"></span>';
    $('#d-app-id').textContent = 'Loading application';
    $('#d-program').textContent = '';
    $('#d-status').hidden = true;
    ['#d-household', '#d-income', '#d-residence'].forEach((s) => { $(s).innerHTML = '<span class="skeleton w-60"></span>'; });
    $('#d-criteria').innerHTML = '<span class="skeleton w-80"></span><span class="skeleton w-60"></span><span class="skeleton w-80"></span>';
    $('#d-verdict').innerHTML = '<span class="skeleton w-60" style="height:24px"></span>';
    $('#d-reco').textContent = '';
    $('#open-decision').disabled = true;
  }

  async function selectCase(id, pushHash = true) {
    state.selectedId = id;
    renderQueue();
    if (pushHash) history.replaceState(null, '', `#/queue/${encodeURIComponent(id)}`);
    const ticket = ++state.loadingCase;
    detailLoading();
    try {
      const c = await api(`/api/cases/${encodeURIComponent(id)}`);
      if (ticket !== state.loadingCase) return; // a newer selection superseded this one
      state.caseData = c;
      renderCase(c);
    } catch (err) {
      if (ticket !== state.loadingCase) return;
      $('#detail-body').hidden = true;
      const empty = $('#detail-empty');
      empty.hidden = false;
      empty.innerHTML = `<h3>Could not load ${esc(id)}</h3><p>${esc(err.message)}</p><button class="btn" type="button" id="retry-case">Retry</button>`;
      $('#retry-case').addEventListener('click', () => selectCase(id));
    }
  }

  function renderCase(c) {
    $('#detail-empty').hidden = true;
    $('#detail-body').hidden = false;
    $('#d-app-id').textContent = `Application ${c.application_id}`;
    $('#d-name').textContent = c.full_name;
    $('#d-program').textContent = `${c.program_name} · Lodged ${c.lodged_date}`;
    const pill = detailPill(c);
    const statusEl = $('#d-status');
    statusEl.hidden = false;
    statusEl.className = `pill ${pill.cls}`;
    statusEl.textContent = pill.text;
    banner($('#detail-banner'), c.lakebase_error ? `Human decision history is temporarily unavailable (${c.lakebase_error}).` : '', true);

    // Review · summary
    $('#d-refreshed').textContent = c.refreshed_at ? `Applicant 360 refreshed ${fmtTime(c.refreshed_at)}` : '';
    $('#d-household').textContent = c.summary.household;
    $('#d-income').textContent = c.summary.income;
    $('#d-residence').textContent = c.summary.residence;

    // Review · criteria
    $('#d-ruleset').textContent = c.ruleset ? `Ruleset ${c.ruleset}` : '';
    $('#d-criteria').innerHTML = c.criteria.length ? c.criteria.map((r) => {
      const pass = r.result === 'pass';
      const fail = r.result === 'fail';
      const stateCls = pass ? 'pass' : fail ? 'fail' : 'review';
      const stateLabel = pass ? 'Passed' : fail ? 'Not met' : 'Review needed';
      return `<div class="criterion">
        <span class="state ${stateCls}" aria-label="${stateLabel}">${pass ? '✓' : fail ? '✕' : '!'}</span>
        <div><strong>${esc(r.criterion_name)}</strong>${r.note ? `<p class="muted" style="margin-top: var(--space-1);">${esc(r.note)}</p>` : ''}<span class="citation">${esc(r.citation)}</span></div>
        <span class="pill ${pass ? 'ready' : fail ? 'urgent' : ''}">${pass ? 'Passed' : fail ? 'Not met' : 'Review'}</span>
      </div>`;
    }).join('') : '<div class="state-block"><p>No rules evaluated for this application.</p></div>';

    // Review · recommendation
    const reco = c.recommendation;
    const recoEl = $('#d-reco');
    if (reco) {
      $('#d-verdict').textContent = reco.verdict;
      recoEl.textContent = (reco.text || '').replace(/\*\*/g, '').replace(/^#+\s*/gm, '').trim();
      $('#d-reco-meta').textContent = `Generated ${fmtDateTime(reco.generated_at)} · ${reco.model_endpoint || ''}`;
    } else {
      const passed = c.rules_outcome === 'eligible';
      $('#d-verdict').textContent = passed ? 'Rules passed' : c.rules_outcome === 'ineligible' ? 'Rules not met' : 'No recommendation';
      recoEl.textContent = passed
        ? 'All criteria passed deterministically. No agent triage was required.'
        : c.rules_outcome === 'ineligible'
          ? `${c.counts.failed} hard criteria were not met under the current ruleset. Confirm the evidence before recording a decision.`
          : 'No system recommendation is available for this application.';
      $('#d-reco-meta').textContent = c.ruleset ? `Deterministic rules · ${c.ruleset}` : '';
    }
    recoEl.classList.add('clamped');
    const toggle = $('#d-reco-toggle');
    requestAnimationFrame(() => { toggle.hidden = recoEl.scrollHeight <= recoEl.clientHeight + 2; toggle.textContent = 'Show full reasoning'; });
    $('#open-decision').disabled = false;

    // Latest human decision
    const latest = c.decisions && c.decisions[0];
    $('#d-decision-card').hidden = !latest;
    if (latest) {
      $('#d-decision-outcome').textContent = latest.outcome;
      $('#d-decision-rationale').textContent = latest.rationale;
      $('#d-decision-meta').textContent = `${latest.caseworker_name || latest.caseworker_email} · ${fmtDateTime(latest.decided_at)} · ${latest.decision_id}`;
      $('#open-decision').textContent = 'Record new decision';
    } else {
      $('#open-decision').textContent = 'Record decision';
    }

    // Checklist
    $$('[data-check]').forEach((box) => { box.checked = !!(c.checklist && c.checklist[box.dataset.check]); box.disabled = !!c.lakebase_error; });

    // Applicant 360
    $('#d-360').innerHTML = c.applicant_360.length
      ? c.applicant_360.map((r) => `<tr><td>${esc(r.domain)}</td><td>${esc(r.record)}</td><td>${esc(r.source)}</td><td class="meta">${esc(r.freshness)}</td></tr>`).join('')
      : '<tr><td colspan="4" class="muted">No applicant 360 record available.</td></tr>';

    // Evidence & citations
    const statusPill = (s) => s === 'verified' ? '<span class="pill ready">Verified</span>'
      : s === 'needs_context' ? '<span class="pill">Needs context</span>'
        : '<span class="pill urgent">Unverified</span>';
    const citedBy = (section) => c.criteria.filter((r) => r.policy_section === section).map((r) => `${r.rule_id} · ${r.criterion_name}`);
    const docs = c.evidence.map((d) => `<article class="card"><div class="section-head"><h3>${esc(d.document_name)}</h3>${statusPill(d.verification_status)}</div><p class="muted" style="margin-top:var(--space-2);">Submitted ${esc(d.submitted_date)} · ${esc(d.category)} · ${esc(d.summary)}</p><span class="citation">${esc(d.document_id)}</span></article>`);
    const pols = c.policies.map((p) => {
      const refs = citedBy(p.section);
      return `<article class="card"><div class="section-head"><h3>Policy ${esc(p.section)} · ${esc(p.title)}</h3><span class="meta">Policy version ${esc(p.version)}</span></div><p style="margin-top:var(--space-2);">${esc(p.text)}</p><span class="citation">${refs.length ? `Cited by ${esc(refs.join('; '))}` : `Effective ${esc(p.effective_date)}`}</span></article>`;
    });
    $('#d-evidence').innerHTML = [...docs, ...pols].join('') || '<div class="state-block"><p>No evidence or policy citations recorded.</p></div>';

    // Audit timeline
    $('#d-timeline').innerHTML = c.timeline.length ? c.timeline.map((e) => `<div class="event ${e.origin === 'human' ? 'human' : ''}">
      <strong>${esc(e.title)}</strong><span class="pill plain origin">${e.origin === 'human' ? 'Human' : 'System'}</span>
      <p class="muted">${esc(e.description)}${e.detail ? ` · ${esc(e.detail)}` : ''}</p>
      <span class="meta">${fmtDateTime(e.timestamp)} · ${esc(e.actor)}</span>
    </div>`).join('') : '<p class="muted">No audit events recorded.</p>';
  }

  $('#d-reco-toggle').addEventListener('click', (e) => {
    const el = $('#d-reco');
    const clamped = el.classList.toggle('clamped');
    e.target.textContent = clamped ? 'Show full reasoning' : 'Show less';
  });

  async function saveChecklist(updates) {
    if (!state.selectedId) return;
    try {
      const result = await api(`/api/cases/${encodeURIComponent(state.selectedId)}/checklist`, { method: 'PUT', body: JSON.stringify(updates) });
      if (state.caseData) state.caseData.checklist = result;
    } catch (err) {
      toast(`Checklist not saved: ${err.message}`, true);
      $$('[data-check]').forEach((box) => { box.checked = !!(state.caseData && state.caseData.checklist[box.dataset.check]); });
    }
  }
  $$('[data-check]').forEach((box) => box.addEventListener('change', () => saveChecklist({ [box.dataset.check]: box.checked })));

  $('#open-citations').addEventListener('click', () => {
    showPanel('evidence');
    const box = $('[data-check="citations_opened"]');
    if (!box.checked && !box.disabled) { box.checked = true; saveChecklist({ citations_opened: true }); }
  });
  $('#download-record').addEventListener('click', () => {
    if (state.selectedId) window.location.href = `/api/cases/${encodeURIComponent(state.selectedId)}/record`;
  });

  // ------------------------------------------------------------------ Decision dialog
  const dialog = $('#decision-dialog');
  const labels = { rules_reviewed: 'Rules result reviewed', citations_opened: 'Policy citations opened', conflicts_resolved: 'Conflicting evidence resolved' };

  $('#open-decision').addEventListener('click', () => {
    const c = state.caseData;
    if (!c) return;
    const pending = Object.keys(labels).filter((k) => !(c.checklist && c.checklist[k]));
    const warn = $('#checklist-warning');
    warn.hidden = !pending.length;
    warn.innerHTML = pending.length ? `<strong>Checklist incomplete.</strong> Not yet confirmed: ${esc(pending.map((k) => labels[k]).join(', '))}.` : '';
    $('#decision-title').textContent = `Record eligibility decision · ${c.application_id}`;
    $('#form-error').textContent = '';
    dialog.showModal();
    $('#outcome').focus();
  });
  $('#cancel-decision').addEventListener('click', () => dialog.close());

  $('#decision-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const outcome = $('#outcome').value;
    const rationale = $('#reason').value.trim();
    const errorEl = $('#form-error');
    if (!outcome) { errorEl.textContent = 'Select an outcome.'; $('#outcome').focus(); return; }
    if (rationale.length < 20) { errorEl.textContent = 'Explain how the evidence and policy support your decision (at least 20 characters).'; $('#reason').focus(); return; }
    errorEl.textContent = '';
    const btn = $('#save-decision');
    btn.disabled = true;
    btn.setAttribute('aria-busy', 'true');
    btn.textContent = 'Saving…';
    try {
      await api(`/api/cases/${encodeURIComponent(state.selectedId)}/decision`, { method: 'POST', body: JSON.stringify({ outcome, rationale }) });
      dialog.close();
      $('#decision-form').reset();
      toast('Decision saved to the audit trail.');
      await Promise.all([selectCase(state.selectedId), loadQueue()]);
    } catch (err) {
      errorEl.textContent = err.message;
    } finally {
      btn.disabled = false;
      btn.removeAttribute('aria-busy');
      btn.textContent = 'Save decision';
    }
  });

  // ------------------------------------------------------------------ Policy library
  async function loadPolicies() {
    const list = $('#policy-list');
    if (!state.policies) {
      list.innerHTML = '<span class="skeleton w-80"></span><span class="skeleton w-60"></span><span class="skeleton w-80"></span>';
      try {
        state.policies = await api('/api/policies');
      } catch (err) {
        list.innerHTML = `<div class="state-block"><h3>Could not load policies</h3><p>${esc(err.message)}</p></div>`;
        return;
      }
    }
    renderPolicies();
  }
  function renderPolicies() {
    const q = $('#policy-search').value.trim().toLowerCase();
    const items = (state.policies || []).filter((p) => !q || `${p.program_name} ${p.section} ${p.title} ${p.text}`.toLowerCase().includes(q));
    $('#policy-count').textContent = `${items.length} ${items.length === 1 ? 'section' : 'sections'}`;
    $('#policy-list').innerHTML = items.length ? items.map((p) => `<article class="card"><div class="section-head"><h3>${esc(p.program_name)} · ${esc(p.section)} · ${esc(p.title)}</h3><span class="meta">Version ${esc(p.version)}</span></div><p class="policy-text">${esc(p.text)}</p><span class="citation">${esc(p.policy_id)} · Effective ${esc(p.effective_date)}</span></article>`).join('')
      : '<div class="state-block"><h3>No matching policy sections</h3></div>';
  }
  $('#policy-search').addEventListener('input', renderPolicies);

  // ------------------------------------------------------------------ Audit view
  async function loadAudit() {
    const rows = $('#audit-rows');
    rows.innerHTML = '<tr><td colspan="7"><span class="skeleton w-80"></span><span class="skeleton w-60"></span></td></tr>';
    try {
      const data = await api('/api/decisions');
      banner($('#audit-banner'), data.lakebase_error ? `Decision history unavailable: ${data.lakebase_error}` : '', true);
      rows.innerHTML = data.items.length ? data.items.map((d) => `<tr>
        <td class="meta">${fmtDateTime(d.decided_at)}</td>
        <td><a href="#/queue/${encodeURIComponent(d.application_id)}">${esc(d.application_id)}</a><br /><span class="muted">${esc(d.applicant_name)} · ${esc(d.program_name)}</span></td>
        <td><strong>${esc(d.outcome)}</strong></td>
        <td>${esc(d.agent_verdict || '—')}</td>
        <td>${esc(d.rules_outcome || '—')}${d.ruleset_version ? `<br /><span class="meta">${esc(d.ruleset_version)}</span>` : ''}</td>
        <td>${d.agrees_with_system === null ? '<span class="meta">n/a</span>' : d.agrees_with_system ? '<span class="pill ready">Aligned</span>' : '<span class="pill">Differs</span>'}</td>
        <td>${esc(d.caseworker_name || d.caseworker_email)}</td>
      </tr>`).join('') : '<tr><td colspan="7" class="muted">No human decisions recorded yet.</td></tr>';
    } catch (err) {
      rows.innerHTML = `<tr><td colspan="7"><div class="state-block"><h3>Could not load decisions</h3><p>${esc(err.message)}</p></div></td></tr>`;
    }
  }

  // ------------------------------------------------------------------ Boot
  document.addEventListener('keydown', (e) => {
    if (e.key === '/' && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA' && !dialog.open) {
      e.preventDefault();
      $('#case-search').focus();
    }
  });

  loadMe();
  loadQueue().then(route);
})();
