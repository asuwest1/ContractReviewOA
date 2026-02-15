const $ = (id) => document.getElementById(id);
let selectedWorkflowId = null;

function headers() {
  return {
    'Content-Type': 'application/json',
    'X-Remote-User': $('user').value || 'anonymous',
    'X-User-Roles': $('roles').value || ''
  };
}

async function api(path, opts = {}) {
  const res = await fetch(path, { ...opts, headers: { ...headers(), ...(opts.headers || {}) } });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Request failed');
  return data;
}

async function loadDashboard() {
  const [summary, pending, aging] = await Promise.all([
    api('/api/dashboard/summary'),
    api('/api/dashboard/pending'),
    api('/api/dashboard/aging')
  ]);
  $('summary').textContent = JSON.stringify(summary, null, 2);
  $('pending').innerHTML = pending.map(p => `<li>#${p.workflow_id} ${p.title} - ${p.required_role} -> ${p.assigned_to || 'unassigned'}</li>`).join('');
  $('aging').innerHTML = aging.map(a => `<li>#${a.workflowId} ${a.title} (${a.daysOpen}d, level ${a.reminderLevel})</li>`).join('');
}

async function loadSettings() {
  const s = await api('/api/admin/settings');
  $('s1').value = s.aging_threshold_1 || '';
  $('s2').value = s.aging_threshold_2 || '';
  $('s3').value = s.aging_threshold_3 || '';
  $('s4').value = s.aging_threshold_4 || '';
  $('s5').value = s.aging_threshold_5 || '';
}

async function loadWorkflows() {
  const data = await api('/api/workflows');
  $('workflows').innerHTML = data
    .map(w => `<li><button data-id="${w.workflow_id}">#${w.workflow_id}</button> ${w.title} [${w.current_status}] ${w.is_hold ? '⛔HOLD' : ''}</li>`)
    .join('');
  document.querySelectorAll('#workflows button').forEach(b => b.onclick = () => loadDetail(Number(b.dataset.id)));
}

function renderStepActions(workflow) {
  const pendingSteps = (workflow.steps || []).filter(s => s.step_status === 'Pending');
  $('step-actions').innerHTML = pendingSteps.map(s => `
    <li>
      Step ${s.step_id}: ${s.required_role} -> ${s.assigned_to || 'unassigned'}
      <button data-step="${s.step_id}" data-decision="Approve">Approve</button>
      <button data-step="${s.step_id}" data-decision="Reject">Reject</button>
    </li>
  `).join('') || '<li>No pending steps</li>';

  document.querySelectorAll('#step-actions button').forEach(btn => {
    btn.onclick = async () => {
      const stepId = Number(btn.dataset.step);
      const decision = btn.dataset.decision;
      const comment = prompt(`${decision} comment`, '');
      try {
        await api(`/api/approvals/${stepId}/decide`, {
          method: 'POST',
          body: JSON.stringify({ decision, comment: comment || '' })
        });
        await loadAll();
        if (selectedWorkflowId) await loadDetail(selectedWorkflowId);
      } catch (e) {
        alert(e.message);
      }
    };
  });
}

async function loadDetail(id) {
  const wf = await api(`/api/workflows/${id}`);
  selectedWorkflowId = id;
  $('selected-label').textContent = `Selected: #${wf.workflow_id} ${wf.title}`;
  $('detail').textContent = JSON.stringify(wf, null, 2);
  renderStepActions(wf);
}

$('create-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    const wf = await api('/api/workflows', {
      method: 'POST',
      body: JSON.stringify({
        title: $('title').value,
        docType: $('docType').value,
        steps: [
          { requiredRole: 'Technical', sequenceOrder: 1, parallelGroup: 1, assignedTo: 'tech.user' },
          { requiredRole: 'Commercial', sequenceOrder: 1, parallelGroup: 1, assignedTo: 'comm.user' }
        ],
        document: { filename: `${$('title').value}.txt`, content: $('docContent').value || 'initial', isGolden: true, version: 1 }
      })
    });
    $('title').value = '';
    $('docContent').value = '';
    await loadAll();
    await loadDetail(wf.workflow_id);
  } catch (e) {
    alert(e.message);
  }
});

$('set-status').onclick = async () => {
  if (!selectedWorkflowId) return alert('Select a workflow first');
  try {
    await api(`/api/workflows/${selectedWorkflowId}/status`, {
      method: 'PUT',
      body: JSON.stringify({ status: $('newStatus').value, reason: $('statusReason').value || '' })
    });
    await loadAll();
    await loadDetail(selectedWorkflowId);
  } catch (e) {
    alert(e.message);
  }
};

$('set-hold').onclick = async () => {
  if (!selectedWorkflowId) return alert('Select a workflow first');
  try {
    await api(`/api/workflows/${selectedWorkflowId}/hold`, {
      method: 'PUT',
      body: JSON.stringify({ isHold: $('holdValue').value === 'true', reason: $('holdReason').value || '' })
    });
    await loadAll();
    await loadDetail(selectedWorkflowId);
  } catch (e) {
    alert(e.message);
  }
};

$('add-document').onclick = async () => {
  if (!selectedWorkflowId) return alert('Select a workflow first');
  try {
    await api(`/api/workflows/${selectedWorkflowId}/documents`, {
      method: 'POST',
      body: JSON.stringify({
        filename: $('docName').value || `doc_${Date.now()}.txt`,
        version: Number($('docVersion').value || 1),
        isGolden: $('docGolden').checked,
        resubmission: $('docResub').checked,
        content: $('docBody').value || ''
      })
    });
    await loadAll();
    await loadDetail(selectedWorkflowId);
  } catch (e) {
    alert(e.message);
  }
};

$('save-settings').onclick = async () => {
  try {
    await api('/api/admin/settings', {
      method: 'PUT',
      body: JSON.stringify({
        aging_threshold_1: Number($('s1').value),
        aging_threshold_2: Number($('s2').value),
        aging_threshold_3: Number($('s3').value),
        aging_threshold_4: Number($('s4').value),
        aging_threshold_5: Number($('s5').value)
      })
    });
    alert('Settings updated');
    await loadAll();
  } catch (e) {
    alert(e.message);
  }
};

$('refresh').onclick = async () => {
  await loadAll();
  if (selectedWorkflowId) await loadDetail(selectedWorkflowId);
};

$('run-reminders').onclick = async () => {
  try {
    const out = await api('/api/system/run-reminders', { method: 'POST', body: '{}' });
    alert(`Reminders sent: ${out.sent}`);
    await loadAll();
  } catch (e) {
    alert(e.message);
  }
};

async function loadAll() {
  await Promise.all([loadDashboard(), loadWorkflows(), loadSettings()]);
}

loadAll().catch((e) => alert(e.message));
