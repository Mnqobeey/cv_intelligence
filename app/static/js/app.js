/* Lean OpenRouter Profile Builder */

const fieldDefinitions = window.FIELD_DEFINITIONS || [];

const state = {
  documentId: null,
  sourceView: null,
  templateState: {},
  previewHtml: '',
  reviewBoard: null,
  workflowState: null,
  inputMode: 'file',
  saving: false,
};

const uploadForm = document.getElementById('uploadForm');
const uploadBtn = document.getElementById('uploadBtn');
const statusText = document.getElementById('statusText');
const progressBar = document.getElementById('progressBar');
const progressMeta = document.getElementById('progressMeta');
const progressText = document.getElementById('progressText');
const fileNamePill = document.getElementById('fileNamePill');
const uploadStateIcon = document.getElementById('uploadStateIcon');
const uploadStateTitle = document.getElementById('uploadStateTitle');
const uploadStateHint = document.getElementById('uploadStateHint');
const uploadStateBadge = document.getElementById('uploadStateBadge');
const uploadStateFileName = document.getElementById('uploadStateFileName');
const uploadZone = document.getElementById('uploadZone');
const cvFileInput = document.getElementById('cvFile');
const fileInputArea = document.getElementById('fileInputArea');
const pasteInputArea = document.getElementById('pasteInputArea');
const cvPasteText = document.getElementById('cvPasteText');
const inputModeTabs = document.querySelectorAll('.input-mode-tab');
const documentViewer = document.getElementById('documentViewer');
const sourceMetaPill = document.getElementById('sourceMetaPill');
const templateEditor = document.getElementById('templateEditor');
const previewPane = document.getElementById('previewPane');
const reviewCard = document.getElementById('reviewCard');
const reviewSummary = document.getElementById('reviewSummary');
const reviewBoard = document.getElementById('reviewBoard');
const reviewCompleteBtn = document.getElementById('reviewCompleteBtn');
const downloadPreviewBtn = document.getElementById('downloadPreviewBtn');
const themeToggle = document.getElementById('themeToggle');
const themeIcon = document.getElementById('themeIcon');

let progressTimer = null;
let progressValue = 0;
let syncTimer = null;

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function setStatus(text) {
  statusText.textContent = text;
}

function responseMessage(data, fallback) {
  const detail = data?.detail;
  if (!detail) return fallback;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.join(' ');
  if (detail.message && Array.isArray(detail.issues) && detail.issues.length) {
    return `${detail.message} ${detail.issues[0]}`;
  }
  if (detail.message) return detail.message;
  return fallback;
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('cesta-theme', theme);
  themeIcon.textContent = theme === 'light' ? '\u263d' : '\u2600';
}

applyTheme(localStorage.getItem('cesta-theme') || 'light');
themeToggle?.addEventListener('click', () => {
  const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
  applyTheme(next);
});

const uploadZoneStates = {
  empty: {
    icon: '+',
    title: 'Drop your CV here or click to browse',
    hint: 'PDF, DOCX, TXT, or MD',
    badge: '',
    showFile: false,
  },
  selected: {
    icon: '\u2713',
    title: 'File ready to process',
    hint: 'Click Build Profile to generate the recruiter preview.',
    badge: 'Ready',
    showFile: true,
  },
  processing: {
    icon: '\u25cc',
    title: 'Structuring CV',
    hint: 'OpenRouter is turning the CV into profile JSON.',
    badge: 'Building',
    showFile: true,
  },
  processed: {
    icon: '\u2713',
    title: 'Profile built',
    hint: 'Review the fields, complete review, then download.',
    badge: 'Complete',
    showFile: true,
  },
};

function setUploadZoneState(mode, fileName = '') {
  const config = uploadZoneStates[mode] || uploadZoneStates.empty;
  if (!uploadZone) return;
  uploadZone.dataset.state = mode;
  uploadStateIcon.textContent = config.icon;
  uploadStateTitle.textContent = config.title;
  uploadStateHint.textContent = config.hint;
  uploadStateBadge.textContent = config.badge || '';
  uploadStateBadge.classList.toggle('hidden', !config.badge);
  uploadStateFileName.textContent = fileName || '';
  uploadStateFileName.classList.toggle('hidden', !config.showFile || !fileName);
}

function updateProgress(value, label) {
  const fill = progressBar.querySelector('.progress-fill');
  progressMeta.classList.remove('hidden');
  progressBar.classList.remove('hidden');
  progressText.classList.remove('hidden');
  progressValue = Math.max(0, Math.min(100, Math.round(value)));
  fill.style.width = `${progressValue}%`;
  progressText.textContent = `${label} ${progressValue}%`;
}

function showProgress() {
  clearInterval(progressTimer);
  updateProgress(8, 'Reading CV...');
  progressTimer = setInterval(() => {
    if (progressValue >= 94) return;
    const increment = progressValue < 45 ? 7 : progressValue < 75 ? 4 : 2;
    updateProgress(Math.min(94, progressValue + increment), progressValue < 55 ? 'Reading CV...' : 'Structuring...');
  }, 450);
}

function hideProgress(completed = true) {
  clearInterval(progressTimer);
  if (completed) updateProgress(100, 'Finalising...');
  setTimeout(() => {
    const fill = progressBar.querySelector('.progress-fill');
    progressBar.classList.add('hidden');
    progressText.classList.add('hidden');
    progressMeta.classList.add('hidden');
    fill.style.width = '0%';
    progressValue = 0;
  }, completed ? 500 : 150);
}

function setLoading(loading, completed = true) {
  const btnText = uploadBtn.querySelector('.btn-text');
  const btnLoader = uploadBtn.querySelector('.btn-loader');
  if (loading) {
    btnText.textContent = 'Building...';
    btnLoader.classList.remove('hidden');
    uploadBtn.disabled = true;
    setUploadZoneState('processing', cvFileInput?.files?.[0]?.name || fileNamePill.textContent || '');
    showProgress();
    return;
  }
  btnText.textContent = 'Build Profile';
  btnLoader.classList.add('hidden');
  uploadBtn.disabled = false;
  hideProgress(completed);
}

function setInputMode(mode) {
  state.inputMode = mode;
  inputModeTabs.forEach((tab) => tab.classList.toggle('active', tab.dataset.inputMode === mode));
  fileInputArea.style.display = mode === 'file' ? '' : 'none';
  pasteInputArea.style.display = mode === 'paste' ? '' : 'none';
}

inputModeTabs.forEach((tab) => {
  tab.addEventListener('click', () => setInputMode(tab.dataset.inputMode));
});

cvFileInput?.addEventListener('change', () => {
  if (cvFileInput.files.length) {
    setUploadZoneState('selected', cvFileInput.files[0].name);
    return;
  }
  setUploadZoneState(state.documentId ? 'processed' : 'empty', fileNamePill.textContent);
});

if (uploadZone) {
  ['dragenter', 'dragover'].forEach((evt) => {
    uploadZone.addEventListener(evt, (event) => {
      event.preventDefault();
      uploadZone.classList.add('dragover');
    });
  });
  ['dragleave', 'drop'].forEach((evt) => {
    uploadZone.addEventListener(evt, () => uploadZone.classList.remove('dragover'));
  });
}

function renderSource() {
  if (!state.documentId || !state.sourceView) {
    sourceMetaPill.textContent = 'No source';
    documentViewer.className = 'document-viewer empty-state';
    documentViewer.innerHTML = '<div class="empty-state-content"><div class="empty-icon">&#128196;</div><h3>Upload or paste a CV</h3><p>The source document will appear here after processing.</p></div>';
    return;
  }

  documentViewer.className = 'document-viewer fade-in';
  if (state.sourceView.type === 'pdf_pages' && Array.isArray(state.sourceView.pages)) {
    sourceMetaPill.textContent = `${state.sourceView.pages.length} page${state.sourceView.pages.length === 1 ? '' : 's'}`;
    documentViewer.innerHTML = state.sourceView.pages.map((page) => `
      <div class="pdf-page-card">
        <div class="pdf-page-header">Page ${page.page_number}</div>
        <img src="${escapeHtml(page.image_url)}" alt="CV page ${page.page_number}" class="pdf-page-image" />
      </div>
    `).join('');
    return;
  }

  if (state.sourceView.type === 'html_document') {
    sourceMetaPill.textContent = 'Text source';
    documentViewer.innerHTML = `<div class="real-doc-card">${state.sourceView.html || ''}</div>`;
    return;
  }

  if (state.sourceView.type === 'file_link') {
    sourceMetaPill.textContent = 'File source';
    documentViewer.innerHTML = `<div class="real-doc-card"><a href="${escapeHtml(state.sourceView.url)}" target="_blank" rel="noopener">Open original file</a></div>`;
    return;
  }

  sourceMetaPill.textContent = 'Source';
  documentViewer.innerHTML = '<div class="empty-state-content"><p>No source preview is available.</p></div>';
}

function groupedFields() {
  const groups = [];
  const index = new Map();
  fieldDefinitions.forEach((field) => {
    const category = field.category || 'Profile';
    if (!index.has(category)) {
      index.set(category, { category, fields: [] });
      groups.push(index.get(category));
    }
    index.get(category).fields.push(field);
  });
  return groups;
}

function renderEditor() {
  if (!state.documentId) {
    templateEditor.className = 'template-grid empty-state';
    templateEditor.innerHTML = '<div class="empty-state-content"><div class="empty-icon">&#9998;</div><h3>Your profile fields will appear here</h3><p>Build a profile to review and refine the generated content.</p></div>';
    reviewCompleteBtn.style.display = 'none';
    return;
  }

  templateEditor.className = 'template-grid fade-in';
  templateEditor.innerHTML = groupedFields().map((group) => `
    <div class="template-category">
      <h3>${escapeHtml(group.category)}</h3>
      <div class="template-category-grid">
        ${group.fields.map((field) => renderField(field)).join('')}
      </div>
    </div>
  `).join('');

  templateEditor.querySelectorAll('[data-field-key]').forEach((input) => {
    input.addEventListener('input', () => {
      state.templateState[input.dataset.fieldKey] = input.value;
      scheduleTemplateSync();
    });
  });
}

function renderField(field) {
  const value = state.templateState[field.key] || '';
  const common = `id="field-${escapeHtml(field.key)}" data-key="${escapeHtml(field.key)}" data-field-key="${escapeHtml(field.key)}"`;
  const control = field.kind === 'atomic'
    ? `<input ${common} class="field-input" value="${escapeHtml(value)}" />`
    : `<textarea ${common} class="field-textarea" rows="5">${escapeHtml(value)}</textarea>`;
  return `
    <div class="field-card" id="field-card-${escapeHtml(field.key)}">
      <label class="field-label" for="field-${escapeHtml(field.key)}">${escapeHtml(field.label)}</label>
      ${control}
    </div>
  `;
}

function renderPreview() {
  if (!state.previewHtml) {
    previewPane.className = 'preview-pane empty-state';
    previewPane.innerHTML = '<div class="empty-state-content"><div class="empty-icon">&#9733;</div><h3>Your polished profile preview</h3><p>The generated CestaSoft profile preview will appear here.</p></div>';
    return;
  }
  previewPane.className = 'preview-pane fade-in';
  previewPane.innerHTML = state.previewHtml;
}

function renderReview() {
  if (!state.documentId || !state.reviewBoard) {
    reviewCard.style.display = 'none';
    return;
  }
  reviewCard.style.display = '';
  const workflow = state.workflowState || {};
  const issues = workflow.blocking_issues || [];
  reviewSummary.textContent = workflow.review_ready
    ? workflow.review_confirmed
      ? 'Review complete. Download is unlocked.'
      : 'Profile is ready. Complete review to unlock download.'
    : issues[0] || 'Some required sections need review.';

  const sections = state.reviewBoard.sections || [];
  reviewBoard.innerHTML = sections.map((section) => `
    <div class="review-item ${section.status === 'Ready' ? 'is-ready' : 'needs-attention'}">
      <div class="review-item-top">
        <strong>${escapeHtml(section.label)}</strong>
        <span>${escapeHtml(section.status)}</span>
      </div>
      <small class="review-item-text">${escapeHtml(section.issue || '')}</small>
    </div>
  `).join('');
}

function updateActionButtons() {
  const workflow = state.workflowState || {};
  reviewCompleteBtn.style.display = state.documentId ? '' : 'none';
  reviewCompleteBtn.disabled = !workflow.review_ready || !!workflow.review_confirmed;
  downloadPreviewBtn.style.display = workflow.can_download ? '' : 'none';
}

function applyDocumentResponse(data) {
  state.documentId = data.document_id;
  state.sourceView = data.source_view || null;
  state.templateState = data.template_state || {};
  state.previewHtml = data.preview_html || '';
  state.reviewBoard = data.review_board || null;
  state.workflowState = data.workflow_state || null;
  fileNamePill.textContent = data.filename || 'CV Profile';

  renderSource();
  renderEditor();
  renderPreview();
  renderReview();
  updateActionButtons();

  const workflow = state.workflowState || {};
  if (workflow.review_ready) {
    setStatus('Profile built. Review the fields and complete review to unlock download.');
  } else {
    setStatus((workflow.blocking_issues || [])[0] || 'Profile built. Some fields need review.');
  }
}

function scheduleTemplateSync() {
  clearTimeout(syncTimer);
  syncTimer = setTimeout(syncTemplate, 450);
}

async function syncTemplate() {
  if (!state.documentId || state.saving) return;
  state.saving = true;
  try {
    const response = await fetch(`/api/document/${state.documentId}/template`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(state.templateState),
    });
    const data = await response.json();
    if (!response.ok) {
      setStatus(responseMessage(data, 'Unable to save profile edits.'));
      return;
    }
    state.templateState = data.template_state || state.templateState;
    state.previewHtml = data.preview_html || '';
    state.reviewBoard = data.review_board || null;
    state.workflowState = data.workflow_state || null;
    renderPreview();
    renderReview();
    updateActionButtons();
  } catch (err) {
    setStatus('Network error while saving profile edits.');
  } finally {
    state.saving = false;
  }
}

async function completeReview() {
  if (!state.documentId) return;
  await syncTemplate();
  setStatus('Validating profile for download...');
  try {
    const response = await fetch(`/api/document/${state.documentId}/review-complete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ template_state: state.templateState }),
    });
    const data = await response.json();
    if (!response.ok) {
      setStatus(responseMessage(data, 'Review could not be completed.'));
      return;
    }
    applyDocumentResponse(data);
    setStatus('Review complete. DOCX download is ready.');
  } catch (err) {
    setStatus('Network error while completing review.');
  }
}

async function downloadProfile() {
  if (!state.documentId) return;
  setStatus('Preparing DOCX profile...');
  try {
    const response = await fetch(`/api/document/${state.documentId}/download`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ template_state: state.templateState }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      setStatus(responseMessage(data, 'Download failed.'));
      return;
    }
    const blob = await response.blob();
    const disposition = response.headers.get('content-disposition') || '';
    const filenameMatch = disposition.match(/filename="?([^"]+)"?/);
    const filename = filenameMatch ? filenameMatch[1] : 'Professional_Profile.docx';
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
    setStatus('Profile downloaded successfully.');
  } catch (err) {
    setStatus('Network error while downloading profile.');
  }
}

reviewCompleteBtn.addEventListener('click', completeReview);
downloadPreviewBtn.addEventListener('click', downloadProfile);

uploadForm.addEventListener('submit', async (event) => {
  event.preventDefault();

  let request;
  let selectedName = '';
  if (state.inputMode === 'paste') {
    const text = (cvPasteText.value || '').trim();
    if (!text) {
      setStatus('Please paste CV text first.');
      return;
    }
    selectedName = 'Pasted CV Text';
    request = fetch('/api/upload-text', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
  } else {
    const file = cvFileInput.files[0];
    if (!file) {
      setStatus('Please select a CV file first.');
      return;
    }
    selectedName = file.name;
    const formData = new FormData();
    formData.append('file', file);
    request = fetch('/api/upload', { method: 'POST', body: formData });
  }

  setLoading(true);
  setStatus('Building profile with OpenRouter...');
  try {
    const response = await request;
    const data = await response.json();
    if (!response.ok) {
      setStatus(responseMessage(data, 'Profile build failed.'));
      setLoading(false, false);
      setUploadZoneState(state.documentId ? 'processed' : 'empty', state.documentId ? fileNamePill.textContent : '');
      return;
    }
    cvFileInput.value = '';
    setUploadZoneState('processed', data.filename || selectedName);
    applyDocumentResponse(data);
    setLoading(false);
  } catch (err) {
    setStatus('Network error. Is the server running?');
    setLoading(false, false);
  }
});

setUploadZoneState('empty');
renderSource();
renderEditor();
renderPreview();
renderReview();
updateActionButtons();
