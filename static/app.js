const $ = (selector) => document.querySelector(selector);
let lastPayload = null;
let lastRedactedPayload = null;

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = data.detail?.reason || data.detail || data.message || `Request failed (${response.status})`;
    throw new Error(typeof message === 'string' ? message : JSON.stringify(message));
  }
  return data;
}

function setBusy(button, busy, busyText = 'Working…') {
  if (busy) {
    button.dataset.originalText = button.textContent;
    button.textContent = busyText;
    button.disabled = true;
  } else {
    button.textContent = button.dataset.originalText || button.textContent;
    button.disabled = false;
  }
}

function pillClass(decision) {
  return ({ ALLOW: 'allow', BLOCK: 'block', REVIEW: 'review', REDACT: 'info' })[decision] || 'info';
}
function showResult(element, data, title = 'Gateway result') {
  element.classList.remove('hidden');
  const decision = data.decision || (data.success ? 'ALLOW' : 'BLOCK');
  const execStatus = data.execution_status || '—';
  const lines = [];
  if (data.reason) lines.push(`<div><b>Reason:</b> ${escapeHtml(data.reason)}</div>`);
  if (data.execution_status) lines.push(`<div><b>Execution:</b> ${escapeHtml(execStatus)}</div>`);
  if (data.approval_id) lines.push(`<div><b>Approval ID:</b> ${escapeHtml(data.approval_id)}</div>`);
  if (data.note) lines.push(`<div>${escapeHtml(data.note)}</div>`);
  if (data.message) lines.push(`<div>${escapeHtml(data.message)}</div>`);
  element.innerHTML = `<div class="result-title"><strong>${escapeHtml(title)}</strong><span class="pill ${pillClass(decision)}">${escapeHtml(decision)}</span></div><div class="result-lines">${lines.join('')}</div>`;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
}

async function refreshDashboard() {
  const [overview, events, approvals, profile, config] = await Promise.all([
    api('/api/overview'), api('/api/events'), api('/api/approvals'), api('/api/profile'), api('/api/config')
  ]);
  $('#stat-total').textContent = overview.total_events;
  $('#stat-blocked').textContent = overview.blocked_actions;
  $('#stat-executed').textContent = overview.executed_actions;
  $('#stat-pending').textContent = overview.pending_approvals;
  $('#nav-pending').textContent = overview.pending_approvals;

  $('#profile-fields').innerHTML = Object.entries(profile).map(([key, value]) =>
    `<div class="profile-field"><span>${escapeHtml(key.replaceAll('_', ' '))}</span><strong>${escapeHtml(value)}</strong></div>`
  ).join('');

  const examples = {
    name: 'Rahul', work_email: 'rahul@company.test', phone: '9876543210',
    bank_account: '[RESTRICTED FIELD REQUESTED]', api_key: '[RESTRICTED]'
  };
  $('#policy-rows').innerHTML = Object.entries(config.field_policies).map(([field, policy]) =>
    `<tr><td>${escapeHtml(field.replaceAll('_', ' '))}</td><td>${escapeHtml(examples[field] || '—')}</td><td><span class="pill ${pillClass(policy)}">${escapeHtml(policy)}</span></td><td>${policy === 'ALLOW' ? 'Approved recipient only' : policy === 'REVIEW' ? 'One-time user approval' : 'Never share'}</td></tr>`
  ).join('');

  renderApprovals(approvals);
  renderEvents(events);
}

function renderApprovals(approvals) {
  const pending = approvals.filter(item => item.status === 'PENDING');
  if (!pending.length) {
    $('#approval-list').innerHTML = '<div class="empty-state">No pending approvals. A phone-number share to the approved recipient will create one.</div>';
    return;
  }
  $('#approval-list').innerHTML = pending.map(item => `
    <div class="approval-card">
      <div class="approval-top"><strong>Review requested</strong><span class="pill review">PENDING</span></div>
      <div class="approval-meta">Recipient: <b>${escapeHtml(item.recipient)}</b><br/>Expires: ${escapeHtml(new Date(item.expires_at).toLocaleTimeString())}<br/>Approval applies to this exact payload only.</div>
      <div class="approval-payload">${escapeHtml(JSON.stringify(item.payload, null, 2))}</div>
      <div class="approval-actions"><button class="button button-primary button-small" data-approve="${escapeHtml(item.id)}">Approve once</button><button class="button button-quiet button-small" data-reject="${escapeHtml(item.id)}">Reject</button></div>
    </div>`).join('');

  document.querySelectorAll('[data-approve]').forEach(button => button.addEventListener('click', async () => {
    setBusy(button, true, 'Approving…');
    try { const result = await api(`/api/approvals/${button.dataset.approve}/approve`, { method: 'POST', body: '{}' }); showResult($('#send-result'), result, 'Approval execution'); await refreshDashboard(); }
    catch (error) { showToast(error.message); await refreshDashboard(); }
    finally { setBusy(button, false); }
  }));
  document.querySelectorAll('[data-reject]').forEach(button => button.addEventListener('click', async () => {
    setBusy(button, true, 'Rejecting…');
    try { await api(`/api/approvals/${button.dataset.reject}/reject`, { method: 'POST', body: '{}' }); await refreshDashboard(); }
    catch (error) { showToast(error.message); }
    finally { setBusy(button, false); }
  }));
}

function renderEvents(events) {
  if (!events.length) {
    $('#audit-list').innerHTML = '<div class="empty-state">No events yet. Run the demo to create records.</div>';
    return;
  }
  $('#audit-list').innerHTML = events.map(item => {
    const date = new Date(item.created_at).toLocaleString();
    const fields = (item.fields || []).join(', ') || 'No fields';
    return `<div class="audit-item"><span class="audit-dot ${pillClass(item.decision)}"></span><div class="audit-main"><strong>${escapeHtml(item.action.replaceAll('_', ' '))}</strong><small>${escapeHtml(item.reason)}<br/>${escapeHtml(fields)} · ${escapeHtml(item.destination || item.tool)}</small></div><div class="audit-status"><span class="pill ${pillClass(item.decision)}">${escapeHtml(item.decision)}</span><small>${escapeHtml(item.execution_status)}</small><small>${escapeHtml(date)}</small></div></div>`;
  }).join('');
}

let toastTimer;
function showToast(message) {
  let toast = $('#toast');
  if (!toast) {
    toast = document.createElement('div'); toast.id = 'toast'; toast.className = 'toast'; document.body.appendChild(toast);
  }
  toast.textContent = message; toast.classList.add('visible');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.classList.remove('visible'), 3500);
}

$('#refresh-btn').addEventListener('click', async () => {
  try { await refreshDashboard(); showToast('Dashboard refreshed'); }
  catch (error) { showToast(error.message); }
});

$('#run-demo-btn').addEventListener('click', async () => {
  const button = $('#run-demo-btn'); setBusy(button, true, 'Running security scenario…');
  try {
    const data = await api('/api/demo/run', { method: 'POST', body: '{}' });
    const attack = data.attack_attempt || {};
    const safe = data.safe_completion || {};
    $('#demo-result').classList.remove('hidden');
    $('#demo-result').innerHTML = `
      <div class="result-title"><strong>Demo completed</strong><span class="pill allow">SCENARIO FINISHED</span></div>
      <div class="result-lines">
        <div><b>Attack attempt:</b> <span class="pill ${pillClass(attack.decision)}">${escapeHtml(attack.decision)}</span> — ${escapeHtml(attack.execution_status)}</div>
        <div><b>Reason:</b> ${escapeHtml(attack.reason)}</div>
        <div><b>Safe alternative:</b> <span class="pill redact">REDACT</span> — preview created, restricted fields removed</div>
        <div><b>Safe completion:</b> <span class="pill ${pillClass(safe.decision)}">${escapeHtml(safe.decision)}</span> — ${escapeHtml(safe.execution_status)}</div>
        <div>${escapeHtml(data.message)}</div>
      </div>`;
    await refreshDashboard();
  } catch (error) { showToast(error.message); }
  finally { setBusy(button, false); }
});

$('#clear-fields').addEventListener('click', () => {
  document.querySelectorAll('input[name="field"]').forEach(input => input.checked = false);
});

$('#send-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = event.submitter;
  const selected = [...document.querySelectorAll('input[name="field"]:checked')].map(input => input.value);
  if (!selected.length) { showToast('Select at least one data field.'); return; }
  const examples = { name: 'Rahul', work_email: 'rahul@company.test', phone: '9876543210', bank_account: '[RESTRICTED FIELD REQUESTED]' };
  lastPayload = Object.fromEntries(selected.map(key => [key, examples[key]]));
  setBusy(button, true, 'Checking policy…');
  $('#safe-alternative').classList.add('hidden');
  try {
    const result = await api('/api/tools/send', { method: 'POST', body: JSON.stringify({ recipient: $('#recipient').value, payload: lastPayload }) });
    showResult($('#send-result'), result, 'Policy gateway decision');
    if (result.safe_alternative) {
      lastRedactedPayload = result.safe_alternative;
      $('#safe-alternative').classList.remove('hidden');
      $('#safe-alternative').innerHTML = `<strong>Safer alternative available</strong><p class="muted">The full request was not executed. This preview contains only fields marked ALLOW.</p><pre>${escapeHtml(JSON.stringify(lastRedactedPayload, null, 2))}</pre><div class="form-row"><label for="safe-recipient">Choose an approved recipient for the new action</label><select id="safe-recipient"><option value="hr@company.test">hr@company.test — approved</option></select></div><button class="button button-primary button-small" id="send-safe-btn">Recheck &amp; send safe version</button>`;
      $('#send-safe-btn').addEventListener('click', sendSafeAlternative);
    }
    await refreshDashboard();
  } catch (error) { showToast(error.message); }
  finally { setBusy(button, false); }
});

async function sendSafeAlternative() {
  const button = $('#send-safe-btn'); setBusy(button, true, 'Rechecking…');
  try {
    const recipient = $('#safe-recipient').value;
    const result = await api('/api/tools/send', { method: 'POST', body: JSON.stringify({ recipient, payload: lastRedactedPayload }) });
    showResult($('#send-result'), result, 'Redacted payload rechecked');
    await refreshDashboard();
  } catch (error) { showToast(error.message); }
  finally { setBusy(button, false); }
}

$('#run-ollama-btn').addEventListener('click', async () => {
  const button = $('#run-ollama-btn'); setBusy(button, true, 'Qwen is checking tools…');
  $('#ollama-result').classList.add('hidden');
  try {
    const result = await api('/api/agent/ollama', { method: 'POST', body: JSON.stringify({ model: $('#ollama-model').value, prompt: $('#ollama-prompt').value }) });
    $('#ollama-result').classList.remove('hidden');
    const count = (result.tool_activity || []).length;
    const completed = result.success && count > 0;
    const statusClass = completed ? 'allow' : 'review';
    const statusText = result.status || (completed ? 'COMPLETED' : 'NO TOOL CALLS');
    const extraMessage = result.message ? `<div><b>Status:</b> ${escapeHtml(result.message)}</div>` : '';
    $('#ollama-result').innerHTML = `<div class="result-title"><strong>Local agent response</strong><span class="pill ${statusClass}">${escapeHtml(statusText)}</span></div><div class="result-lines"><div><b>Model:</b> ${escapeHtml(result.model)}</div><div>${escapeHtml(result.assistant_message || 'No final message returned.')}</div><div><b>Tool calls:</b> ${count}</div>${extraMessage}</div><pre class="approval-payload">${escapeHtml(JSON.stringify(result.tool_activity || [], null, 2))}</pre>`;
    await refreshDashboard();
  } catch (error) { showResult($('#ollama-result'), { decision: 'BLOCK', reason: error.message }, 'Ollama connection failed'); }
  finally { setBusy(button, false); }
});

(async function init() {
  try { await refreshDashboard(); }
  catch (error) { showToast(`Cannot load dashboard: ${error.message}`); }
})();
