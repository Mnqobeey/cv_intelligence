/* =========================================================================
   CestaCV Intelligence Studio — Frontend v6
   ========================================================================= */

const fieldDefinitions = window.FIELD_DEFINITIONS || [];
const fieldMap = Object.fromEntries(fieldDefinitions.map((f) => [f.key, f]));

// Group fields by category
const fieldCategories = {};
fieldDefinitions.forEach((f) => {
  const cat = f.category || 'Other';
  if (!fieldCategories[cat]) fieldCategories[cat] = [];
  fieldCategories[cat].push(f);
});

const state = {
  documentId: null,
  documentProfile: null,
  sourceSections: [],
  sourceView: null,
  textBlocks: [],
  templateState: {},
  annotations: [],
  previewHtml: '',
  mappingMode: 'replace',
  currentSelection: null,
  mappedTexts: new Set(),
  reviewBoard: null,
  detectedBlocks: [],
  activeTargetKey: null,
  workflowState: null,
  recommendations: [],
  restorableFields: [],
  structuringPrompt: null,
  activeStructuringPromptKey: null,
  inputMode: 'file', // 'file' or 'paste'
  structuredSource: false,
  importMode: null,
};

// DOM references
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
const documentViewer = document.getElementById('documentViewer');
const builderQuickView = document.getElementById('builderQuickView');
const templateEditor = document.getElementById('templateEditor');
const previewPane = document.getElementById('previewPane');
const annotationList = document.getElementById('annotationList');
const selectionMenu = document.getElementById('selectionMenu');
const selectionClose = document.getElementById('selectionClose');
const selectionPreviewText = document.getElementById('selectionPreviewText');
const selectionCategories = document.getElementById('selectionCategories');
const fieldSearchInput = document.getElementById('fieldSearchInput');
const themeToggle = document.getElementById('themeToggle');
const themeIcon = document.getElementById('themeIcon');
const mappingModeLabel = document.getElementById('mappingModeLabel');
const mappingModeCard = document.getElementById('mappingModeCard');
const reviewCard = document.getElementById('reviewCard');
const reviewSummary = document.getElementById('reviewSummary');
const reviewBoard = document.getElementById('reviewBoard');
const detectedBlocks = document.getElementById('detectedBlocks');
const detectedBlocksWrap = document.getElementById('detectedBlocksWrap');
const downloadPreviewBtn = document.getElementById('downloadPreviewBtn');
const reviewCompleteBtn = document.getElementById('reviewCompleteBtn');
const sectionCountPill = document.getElementById('sectionCountPill');
const fileInputArea = document.getElementById('fileInputArea');
const pasteInputArea = document.getElementById('pasteInputArea');
const cvPasteText = document.getElementById('cvPasteText');
const inputModeTabs = document.querySelectorAll('.input-mode-tab');
const expandBuilderBtn = document.getElementById('expandBuilderBtn');
const backToWorkspaceBtn = document.getElementById('backToWorkspaceBtn');
const recommendationsCard = document.getElementById('recommendationsCard');
const recommendationsList = document.getElementById('recommendationsList');
const promptPreview = document.getElementById('promptPreview');
const promptRecommendation = document.getElementById('promptRecommendation');
const promptPresetList = document.getElementById('promptPresetList');
const promptGuidance = document.getElementById('promptGuidance');
const viewPromptBtn = document.getElementById('viewPromptBtn');
const copyPromptBtn = document.getElementById('copyPromptBtn');

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
function setStatus(text) {
  statusText.textContent = text;
}

const uploadZoneStates = {
  empty: {
    icon: '+',
    title: 'Drop your CV here or click to browse',
    hint: 'PDF, DOCX, TXT supported',
    badge: '',
    showFile: false,
  },
  selected: {
    icon: '\u2713',
    title: 'File ready to analyse',
    hint: 'Click Analyse CV to generate the recruiter preview.',
    badge: 'Ready',
    showFile: true,
  },
  processing: {
    icon: '\u25cc',
    title: 'Analysing CV',
    hint: 'Extracting sections, checking structured JSON, and preparing the review workspace.',
    badge: 'Analysing',
    showFile: true,
  },
  processed: {
    icon: '\u2713',
    title: 'Analysis complete',
    hint: 'Recruiter preview generated and ready for review.',
    badge: 'Complete',
    showFile: true,
  },
};

let progressTimer = null;
let progressValue = 0;
let uploadZoneBurstTimer = null;

function setUploadZoneState(mode, fileName = '') {
  const config = uploadZoneStates[mode] || uploadZoneStates.empty;
  if (!uploadZone) return;
  const previousMode = uploadZone.dataset.state;
  const previousFileName = uploadStateFileName.textContent;
  const isTransition = previousMode !== mode || previousFileName !== (fileName || '');

  // Briefly fade content during state transition for smooth feel
  if (isTransition) {
    const textEl = uploadZone.querySelector('.upload-zone-text');
    if (textEl) {
      textEl.style.transition = 'opacity 0.15s ease, transform 0.15s ease';
      textEl.style.opacity = '0';
      textEl.style.transform = 'translateY(4px)';
    }
  }

  // Small delay to allow fade-out before content swap
  const applyState = () => {
    uploadZone.dataset.state = mode;
    uploadZone.dataset.hasFile = config.showFile && !!fileName ? 'true' : 'false';
    uploadStateIcon.textContent = config.icon;
    uploadStateTitle.textContent = config.title;
    uploadStateHint.textContent = config.hint;
    if (uploadStateBadge) {
      uploadStateBadge.textContent = config.badge || '';
      uploadStateBadge.classList.toggle('hidden', !config.badge);
    }
    uploadStateFileName.textContent = fileName || '';
    uploadStateFileName.classList.toggle('hidden', !config.showFile || !fileName);

    if (isTransition) {
      uploadZone.classList.remove('state-burst');
      void uploadZone.offsetWidth;
      uploadZone.classList.add('state-burst');
      clearTimeout(uploadZoneBurstTimer);
      uploadZoneBurstTimer = window.setTimeout(() => uploadZone.classList.remove('state-burst'), 600);

      // Fade content back in
      const textEl = uploadZone.querySelector('.upload-zone-text');
      if (textEl) {
        requestAnimationFrame(() => {
          textEl.style.transition = 'opacity 0.35s ease, transform 0.35s ease';
          textEl.style.opacity = '1';
          textEl.style.transform = 'translateY(0)';
        });
      }
    }
  };

  if (isTransition) {
    setTimeout(applyState, 120);
  } else {
    applyState();
  }
}

function getUploadZoneFileName() {
  return cvFileInput?.files[0]?.name || (state.documentId ? fileNamePill.textContent : '');
}

function getUploadZoneRestingState() {
  if (cvFileInput?.files.length) return 'selected';
  if (state.documentId) return 'processed';
  return 'empty';
}

function progressPhaseLabel(value) {
  if (value >= 95) return 'Finalising...';
  if (value >= 55) return 'Processing...';
  return 'Analysing CV...';
}

function updateProgress(value, label = progressPhaseLabel(value)) {
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
  updateProgress(8, 'Analysing CV...');
  progressTimer = setInterval(() => {
    if (progressValue >= 94) return;
    const increment = progressValue < 45 ? 7 : (progressValue < 75 ? 4 : 2);
    updateProgress(Math.min(94, progressValue + increment));
  }, 450);
}

function hideProgress(completed = true) {
  clearInterval(progressTimer);
  if (completed) {
    updateProgress(100, 'Finalising...');
  }
  setTimeout(() => {
    const fill = progressBar.querySelector('.progress-fill');
    progressBar.classList.add('hidden');
    progressText.classList.add('hidden');
    progressMeta.classList.add('hidden');
    fill.style.width = '0%';
    progressValue = 0;
  }, completed ? 500 : 150);
}

function setLoading(loading, options = {}) {
  const btnText = uploadBtn.querySelector('.btn-text');
  const btnLoader = uploadBtn.querySelector('.btn-loader');
  const completed = options.completed !== false;
  if (loading) {
    btnText.textContent = 'Analysing...';
    btnLoader.classList.remove('hidden');
    uploadBtn.disabled = true;
    showProgress();
    setUploadZoneState('processing', getUploadZoneFileName());
  } else {
    btnText.textContent = 'Analyse CV';
    btnLoader.classList.add('hidden');
    uploadBtn.disabled = false;
    hideProgress(completed);
  }
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function prettyLabel(text) {
  return String(text).replace(/_/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase());
}

function debounce(fn, wait) {
  let timeout;
  return (...args) => {
    clearTimeout(timeout);
    timeout = setTimeout(() => fn(...args), wait);
  };
}

function truncate(text, max = 120) {
  if (text.length <= max) return text;
  return text.substring(0, max) + '...';
}

const optionalFieldPlaceholders = {
  availability: 'Availability not provided',
  region: 'Region not provided',
  location: 'Location not provided',
  linkedin: 'LinkedIn not provided',
  portfolio: 'Portfolio not provided',
  certifications: 'No certifications listed',
  training: 'No training or courses listed',
  projects: 'No projects listed',
  volunteering: 'No volunteering listed',
  publications: 'No publications listed',
  languages: 'No languages listed',
  awards: 'No awards listed',
  interests: 'No interests listed',
  references: 'Available on request',
  additional_information: 'No additional information provided',
};

function displayPlaceholderForField(fieldKey) {
  return optionalFieldPlaceholders[fieldKey] || 'Not yet mapped';
}

// ---------------------------------------------------------------------------
// Theme
// ---------------------------------------------------------------------------
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('cesta-theme', theme);
  themeIcon.textContent = theme === 'light' ? '\u263D' : '\u2600';
}
applyTheme(localStorage.getItem('cesta-theme') || 'light');

themeToggle.addEventListener('click', () => {
  const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
  applyTheme(next);
});

// ---------------------------------------------------------------------------
// Tab navigation
// ---------------------------------------------------------------------------
function setActiveTab(tab) {
  document.querySelectorAll('.nav-link').forEach((btn) => btn.classList.toggle('active', btn.dataset.tab === tab));
  document.querySelectorAll('.tab-panel').forEach((panel) => panel.classList.toggle('active', panel.dataset.tabPanel === tab));
}

document.querySelectorAll('.nav-link').forEach((btn) => {
  btn.addEventListener('click', () => setActiveTab(btn.dataset.tab));
});

expandBuilderBtn.addEventListener('click', () => setActiveTab('builder'));
backToWorkspaceBtn.addEventListener('click', () => setActiveTab('workspace'));

// ---------------------------------------------------------------------------
// Mapping mode
// ---------------------------------------------------------------------------
document.querySelectorAll('.chip[data-mode]').forEach((chip) => {
  chip.addEventListener('click', () => {
    document.querySelectorAll('.chip[data-mode]').forEach((c) => c.classList.remove('active'));
    chip.classList.add('active');
    state.mappingMode = chip.dataset.mode;
    mappingModeLabel.textContent = prettyLabel(state.mappingMode);
  });
});

// ---------------------------------------------------------------------------
// Upload zone drag & drop
// ---------------------------------------------------------------------------
const uploadZone = document.getElementById('uploadZone');
const cvFileInput = document.getElementById('cvFile');
setUploadZoneState('empty');

if (uploadZone) {
  cvFileInput?.addEventListener('change', () => {
    if (state.documentId && !cvFileInput.files.length) {
      setUploadZoneState('processed', fileNamePill.textContent);
      return;
    }
    if (cvFileInput.files.length) {
      setUploadZoneState('selected', cvFileInput.files[0].name);
      return;
    }
    setUploadZoneState(getUploadZoneRestingState(), getUploadZoneFileName());
  });
  ['dragenter', 'dragover'].forEach((evt) => {
    uploadZone.addEventListener(evt, (e) => { e.preventDefault(); uploadZone.classList.add('dragover'); });
  });
  ['dragleave', 'drop'].forEach((evt) => {
    uploadZone.addEventListener(evt, () => uploadZone.classList.remove('dragover'));
  });
}

// ---------------------------------------------------------------------------
// Input mode toggle (File vs Paste)
// ---------------------------------------------------------------------------
function setInputMode(mode) {
  state.inputMode = mode;
  inputModeTabs.forEach((tab) => tab.classList.toggle('active', tab.dataset.inputMode === mode));
  fileInputArea.style.display = mode === 'file' ? '' : 'none';
  pasteInputArea.style.display = mode === 'paste' ? '' : 'none';
  const btnText = uploadBtn.querySelector('.btn-text');
  if (btnText && !uploadBtn.disabled) {
    btnText.textContent = 'Analyse CV';
  }
}

inputModeTabs.forEach((tab) => {
  tab.addEventListener('click', () => setInputMode(tab.dataset.inputMode));
});

// ---------------------------------------------------------------------------
// Source selection helpers
// ---------------------------------------------------------------------------
function getSelectionMenuRectFromElement(el) {
  const rect = el.getBoundingClientRect();
  return { left: rect.left + 12, bottom: rect.bottom + 4 };
}

function highlightSourceSection(sectionEl) {
  documentViewer.querySelectorAll('.source-section.is-selected, .pdf-text-span.is-selected').forEach((el) => el.classList.remove('is-selected'));
  if (sectionEl) sectionEl.classList.add('is-selected');
}

function getSectionPayload(section) {
  const sourceLabel = section.querySelector('.source-section-title')?.textContent || 'Detected Section';
  const content = (section.querySelector('.source-section-content')?.textContent || '').trim();
  return {
    text: [sourceLabel, content].join('\n').trim(),
    content,
    blockId: section.dataset.sectionId || section.dataset.blockId || 'viewer',
    sourceLabel,
    suggestedField: section.dataset.mappedField || null,
  };
}

async function autoApplySourceSection(section, preferredTargetKey = null) {
  const payload = getSectionPayload(section);
  if (!payload.content) return;
  highlightSourceSection(section);
  state.currentSelection = { ...(state.currentSelection || {}), ...payload };
  const targetKey = preferredTargetKey || payload.suggestedField;
  if (targetKey && targetKey !== 'additional_sections') {
    await assignSelection(targetKey, { selectionOverride: { ...payload, text: payload.content } });
    return;
  }
  showSelectionMenu(getSelectionMenuRectFromElement(section), payload.text, payload.blockId);
}

function bindViewerInteractions() {
  documentViewer.querySelectorAll('.source-section').forEach((section) => {
    section.querySelector('.source-section-header')?.addEventListener('click', async (e) => {
      e.preventDefault();
      e.stopPropagation();
      await autoApplySourceSection(section);
    });

    section.querySelector('.source-map-btn')?.addEventListener('click', async (e) => {
      e.preventDefault();
      e.stopPropagation();
      await autoApplySourceSection(section, section.dataset.mappedField || null);
    });

    section.addEventListener('click', (e) => {
      if (e.target.closest('button') || e.target.closest('.source-section-content')) return;
      const payload = getSectionPayload(section);
      if (!payload.text) return;
      highlightSourceSection(section);
      state.currentSelection = { ...(state.currentSelection || {}), ...payload };
      showSelectionMenu(getSelectionMenuRectFromElement(section), payload.text, payload.blockId);
      e.stopPropagation();
    });
  });

  documentViewer.querySelectorAll('.pdf-text-span').forEach((span) => {
    span.addEventListener('click', (e) => {
      const pageCard = span.closest('.pdf-page-card');
      const blockId = pageCard ? `page-${pageCard.dataset.pageNumber}` : (span.dataset.blockId || 'viewer');
      const text = (span.textContent || '').trim();
      if (!text) return;
      documentViewer.querySelectorAll('.pdf-text-span.is-selected').forEach((el) => el.classList.remove('is-selected'));
      span.classList.add('is-selected');
      state.currentSelection = { text, blockId, sourceLabel: pageCard ? `Page ${pageCard.dataset.pageNumber}` : 'Source Document' };
      showSelectionMenu(getSelectionMenuRectFromElement(span), text, blockId);
      e.stopPropagation();
    });
  });
}

// ---------------------------------------------------------------------------
// Render: Source Viewer (real source document when available)
// ---------------------------------------------------------------------------
function renderViewer() {
  if (!state.documentId) {
    documentViewer.className = 'document-viewer empty-state';
    documentViewer.innerHTML = `<div class="empty-state-content"><div class="empty-icon">&#128196;</div><h3>Upload a CV to get started</h3><p>Your original CV will appear here for direct review and mapping.</p></div>`;
    return;
  }
  documentViewer.className = 'document-viewer fade-in';

  if (state.sourceView?.type === 'pdf_pages' && state.sourceView.pages?.length) {
    sectionCountPill.textContent = `${state.sourceView.pages.length} page${state.sourceView.pages.length !== 1 ? 's' : ''}`;
    documentViewer.innerHTML = state.sourceView.pages.map((page) => `
      <div class="pdf-page-card" data-page-number="${page.page_number}">
        <div class="pdf-page-header">Page ${page.page_number}</div>
        <div class="pdf-page-stage" style="aspect-ratio:${page.width}/${page.height};">
          <img src="${page.image_url}" alt="CV page ${page.page_number}" class="pdf-page-image" />
          <div class="pdf-text-overlay">
            ${page.spans.map((sp) => `<span class="pdf-text-span" data-block-id="${sp.id}" style="left:${(sp.x/page.width)*100}%;top:${(sp.y/page.height)*100}%;width:${(sp.w/page.width)*100}%;height:${(sp.h/page.height)*100}%;font-size:${Math.max(8, (sp.font_size/page.height)*100)}%;">${escapeHtml(sp.text)}</span>`).join('')}
          </div>
        </div>
      </div>`).join('');
    bindViewerInteractions();
    return;
  }

  if (state.sourceView?.type === 'html_document') {
    sectionCountPill.textContent = 'Original document';
    documentViewer.innerHTML = `<div class="real-doc-card"><div class="real-doc-inner selectable-html">${state.sourceView.html || ''}</div></div>`;
    bindViewerInteractions();
    return;
  }

  const sections = state.sourceSections || [];
  sectionCountPill.textContent = `${sections.length} section${sections.length !== 1 ? 's' : ''}`;
  if (sections.length > 0) {
    documentViewer.innerHTML = sections.map((sec) => `
      <div class="source-section" data-section-id="${sec.id}" data-mapped-field="${sec.mapped_field || ''}" data-canonical-key="${sec.canonical_key || ''}">
        <div class="source-section-header">
          <span class="source-section-title">${escapeHtml(sec.title)}</span>
          <span class="source-section-mapped">${escapeHtml(sec.mapped_label || prettyLabel(sec.canonical_key))}</span>
        </div>
        <div class="source-section-content">${escapeHtml(sec.content)}</div>
        <div class="source-section-actions">
          <button type="button" class="small-btn source-map-btn" data-block-id="${sec.id}" data-target-key="${sec.mapped_field || 'additional_sections'}">Add to builder</button>
        </div>
      </div>`).join('');
  } else {
    documentViewer.innerHTML = state.textBlocks.map((block, i) => `
      <div class="source-section" data-block-id="${block.id}">
        <div class="source-section-header"><span class="source-section-title">Block ${i + 1}</span></div>
        <div class="source-section-content">${escapeHtml(block.text)}</div>
      </div>`).join('');
  }
  bindViewerInteractions();
}

// ---------------------------------------------------------------------------
// Render: Review Board
// ---------------------------------------------------------------------------
function renderReviewBoard() {
  if (!state.reviewBoard?.sections?.length) {
    reviewCard.style.display = 'none';
    return;
  }
  reviewCard.style.display = '';
  const summary = state.reviewBoard.summary || {};
  const warningCount = (state.workflowState?.warning_issues || []).length;
  reviewSummary.textContent = `${summary.ready || 0} sections ready • ${summary.needs_attention || 0} need attention${warningCount ? ` • ${warningCount} warning${warningCount !== 1 ? 's' : ''}` : ''}`;
  reviewBoard.innerHTML = state.reviewBoard.sections.map((item) => `
    <button type="button" class="review-item ${item.status !== 'Ready' ? 'needs-attention' : 'is-ready'} ${state.activeTargetKey === item.key ? 'active' : ''}" data-target-key="${item.key}">
      <span class="review-item-top">
        <strong>${escapeHtml(item.label)}</strong>
        <span class="status-pill ${item.status.toLowerCase().replace(/\s+/g,'-')}">${escapeHtml(item.status)}</span>
      </span>
      <span class="review-item-text">${escapeHtml(item.issue)}</span>
    </button>`).join('');

  reviewBoard.querySelectorAll('.review-item').forEach((item, index) => {
    item.style.setProperty('--stagger', `${index * 55}ms`);
  });

  reviewBoard.querySelectorAll('[data-target-key]').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.activeTargetKey = btn.dataset.targetKey;
      renderReviewBoard();
      renderDetectedBlocks();
      setActiveTab('workspace');
      focusFieldCard(state.activeTargetKey);
      setStatus(`Fixing ${prettyLabel(state.activeTargetKey)}. Choose a detected block or highlight a precise source snippet.`);
    });
  });
}

function dismissDetectedBlock(blockId) {
  if (!blockId) return;
  state.detectedBlocks = (state.detectedBlocks || []).filter((item) => item.id !== blockId);
}

function restoreFieldStateFromResponse(data, targetKey) {
  state.templateState = data.template_state;
  state.reviewBoard = data.review_board;
  state.workflowState = data.workflow_state;
  state.previewHtml = data.preview_html;
  state.recommendations = data.recommendations || [];
  state.restorableFields = data.restorable_fields || [];
  state.activeTargetKey = targetKey || state.activeTargetKey;
  renderBuilderQuickView();
  renderBuilder();
  renderReviewBoard();
  renderDetectedBlocks();
  renderPreview();
  renderAnnotations();
  renderRecommendations();
  updateDownloadButtons();
}

function focusFieldSurfaces(key, tab = 'workspace') {
  if (!key) return;
  if (tab) setActiveTab(tab);
  focusFieldCard(key);
  const quick = document.querySelector(`.builder-field[data-field-key="${key}"]`);
  if (quick) {
    quick.scrollIntoView({ behavior: 'smooth', block: 'center' });
    quick.classList.add('flash-focus');
    setTimeout(() => quick.classList.remove('flash-focus'), 1600);
  }
}

// ---------------------------------------------------------------------------
// Render: Recommendations
// ---------------------------------------------------------------------------
function renderRecommendations() {
  const recommendations = state.recommendations || [];
  if (!recommendations.length) {
    recommendationsCard.style.display = 'none';
    recommendationsList.innerHTML = '';
    return;
  }
  recommendationsCard.style.display = '';
  recommendationsList.innerHTML = recommendations.map((item) => `
    <div class="recommendation-card ${item.action === 'apply_block' ? 'is-actionable' : ''}" data-recommendation-id="${item.id}" data-target-key="${item.target_key}" data-block-id="${item.block_id || ''}" data-action="${item.action}">
      <span class="recommendation-title">${escapeHtml(item.title)}</span>
      <span class="recommendation-copy">${escapeHtml(item.message)}</span>
      <div class="recommendation-actions">
        ${item.action === 'apply_block' ? `<button type="button" class="small-btn recommendation-apply">${escapeHtml(item.action_label || 'Apply suggestion')}</button>` : ''}
        <button type="button" class="small-btn recommendation-focus">${escapeHtml(item.secondary_label || item.action_label || 'Review field')}</button>
      </div>
    </div>`).join('');

  recommendationsList.querySelectorAll('.recommendation-card').forEach((card) => {
    const targetKey = card.dataset.targetKey;
    const blockId = card.dataset.blockId;
    const applyBtn = card.querySelector('.recommendation-apply');
    const focusBtn = card.querySelector('.recommendation-focus');
    if (applyBtn) {
      applyBtn.addEventListener('click', async (event) => {
        event.stopPropagation();
        state.activeTargetKey = targetKey;
        await applyDetectedBlock(blockId, targetKey);
      });
    }
    if (focusBtn) {
      focusBtn.addEventListener('click', (event) => {
        event.stopPropagation();
        dismissDetectedBlock(blockId);
        state.activeTargetKey = targetKey;
        renderReviewBoard();
        renderBuilderQuickView();
        renderDetectedBlocks();
        renderBuilder();
        focusFieldSurfaces(targetKey, 'workspace');
        setStatus(`Reviewing ${prettyLabel(targetKey)} manually. The suggestion was dismissed so you can focus on the field.`);
      });
    }
  });
}

// ---------------------------------------------------------------------------
// Prompt helpers
// ---------------------------------------------------------------------------
function getStructuringPromptCatalog() {
  if (!state.structuringPrompt || !Array.isArray(state.structuringPrompt.prompts)) return [];
  return state.structuringPrompt.prompts;
}

function getActiveStructuringPrompt() {
  if (!state.structuringPrompt) return null;
  const prompts = getStructuringPromptCatalog();
  if (!prompts.length) {
    return {
      key: state.structuringPrompt.prompt_key || 'default',
      label: state.structuringPrompt.prompt_label || 'ChatGPT Structuring Prompt',
      description: '',
      recommended: true,
      prompt: state.structuringPrompt.prompt || '',
    };
  }
  const preferredKey = state.activeStructuringPromptKey || state.structuringPrompt.recommended_prompt_key || state.structuringPrompt.prompt_key;
  return prompts.find((prompt) => prompt.key === preferredKey) || prompts[0];
}

function syncPromptPreview() {
  const activePrompt = getActiveStructuringPrompt();
  if (!activePrompt || promptPreview.classList.contains('hidden')) return;
  promptPreview.textContent = activePrompt.prompt || '';
}

function renderStructuringPromptFramework() {
  const activePrompt = getActiveStructuringPrompt();
  if (!activePrompt) return;

  if (promptRecommendation) {
    promptRecommendation.textContent = activePrompt.recommended
      ? `${activePrompt.label} (Recommended)`
      : `Prompt Variant: ${activePrompt.label}`;
  }
  if (promptGuidance) {
    promptGuidance.textContent = state.structuringPrompt.pre_paste_guidance || '';
  }

  const prompts = getStructuringPromptCatalog();
  if (promptPresetList) {
    promptPresetList.innerHTML = prompts.map((prompt) => `
      <button
        class="chip ${prompt.key === activePrompt.key ? 'active' : ''}"
        data-prompt-key="${escapeHtml(prompt.key)}"
        title="${escapeHtml(prompt.description || '')}"
        type="button"
      >${escapeHtml(prompt.label)}</button>
    `).join('');

    promptPresetList.querySelectorAll('[data-prompt-key]').forEach((button) => {
      button.addEventListener('click', () => {
        state.activeStructuringPromptKey = button.dataset.promptKey;
        renderStructuringPromptFramework();
        syncPromptPreview();
        const selectedPrompt = getActiveStructuringPrompt();
        if (selectedPrompt) {
          setStatus(`${selectedPrompt.label} ready to copy.`);
        }
      });
    });
  }

  syncPromptPreview();
}

async function loadStructuringPrompt() {
  try {
    const res = await fetch('/api/structuring-prompt');
    const data = await res.json();
    if (!res.ok) return;
    state.structuringPrompt = data;
    state.activeStructuringPromptKey = data.recommended_prompt_key || data.prompt_key || null;
    renderStructuringPromptFramework();
  } catch (err) {
    // ignore
  }
}

function togglePromptPreview() {
  const activePrompt = getActiveStructuringPrompt();
  if (!activePrompt) return;
  const isHidden = promptPreview.classList.contains('hidden');
  if (isHidden) {
    promptPreview.textContent = activePrompt.prompt || '';
    promptPreview.classList.remove('hidden');
    viewPromptBtn.textContent = 'Hide Prompt';
  } else {
    promptPreview.classList.add('hidden');
    viewPromptBtn.textContent = 'View Prompt';
  }
}

async function copyStructuringPrompt() {
  const activePrompt = getActiveStructuringPrompt();
  if (!activePrompt) return;
  try {
    await navigator.clipboard.writeText(activePrompt.prompt || '');
    setStatus(`${activePrompt.label} copied.`);
  } catch (err) {
    setStatus('Unable to copy the prompt right now.');
  }
}

// ---------------------------------------------------------------------------
// Render: Builder Quick View (in workspace pane)
// ---------------------------------------------------------------------------
function renderBuilderQuickView() {
  if (!state.documentId) {
    builderQuickView.className = 'builder-quick-view empty-state';
    builderQuickView.innerHTML = `<div class="empty-state-content"><div class="empty-icon">&#9998;</div><h3>Profile fields will populate here</h3><p>Once a CV is uploaded, extracted information fills each section automatically.</p></div>`;
    return;
  }
  builderQuickView.className = 'builder-quick-view fade-in';

  let html = '';
  for (const [category, fields] of Object.entries(fieldCategories)) {
    html += `<div class="builder-section-group"><div class="builder-group-title">${escapeHtml(category)}</div>`;
    for (const field of fields) {
      const value = state.templateState[field.key] || '';
      const isEmpty = !value.trim();
      const displayValue = isEmpty ? displayPlaceholderForField(field.key) : truncate(value.replace(/\n/g, ' '), 100);
      const reviewItem = state.reviewBoard?.sections?.find((s) => s.key === field.key);
      html += `
        <div class="builder-field ${state.activeTargetKey === field.key ? 'active' : ''}" data-field-key="${field.key}">
          <div class="builder-field-header">
            <div class="builder-field-label">${escapeHtml(field.label)}</div>
            <div class="builder-field-tools">
              ${reviewItem ? `<span class="status-pill ${reviewItem.status.toLowerCase().replace(/\s+/g,'-')}">${escapeHtml(reviewItem.status)}</span>` : ''}
              ${state.restorableFields.includes(field.key) ? `<button type="button" class="inline-restore-btn" data-target-key="${field.key}" title="Undo last change">&#8630;</button>` : ''}
            </div>
          </div>
          <div class="builder-field-value ${isEmpty ? 'empty' : ''}">${escapeHtml(displayValue)}</div>
        </div>`;
    }
    html += '</div>';
  }
  builderQuickView.innerHTML = html;

  // Click on field → switch to builder and focus
  builderQuickView.querySelectorAll('.inline-restore-btn').forEach((btn) => {
    btn.addEventListener('click', async (event) => {
      event.stopPropagation();
      const targetKey = btn.dataset.targetKey;
      if (!state.documentId || !targetKey) return;
      try {
        const res = await fetch(`/api/document/${state.documentId}/restore-field`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ target_key: targetKey }),
        });
        const data = await res.json();
        if (!res.ok) {
          setStatus(data.detail || 'Unable to undo this change.');
          return;
        }
        restoreFieldStateFromResponse(data, targetKey);
        focusFieldSurfaces(targetKey, 'workspace');
        setStatus(`Undid the last change for ${prettyLabel(targetKey)}.`);
      } catch (err) {
        setStatus('Unable to undo this change right now.');
      }
    });
  });

  builderQuickView.querySelectorAll('.builder-field').forEach((el) => {
    el.addEventListener('click', (event) => {
      if (event.target.closest('.inline-restore-btn')) return;
      const key = el.dataset.fieldKey;
      state.activeTargetKey = key;
      renderBuilderQuickView();
      renderReviewBoard();
      renderDetectedBlocks();
      setActiveTab('builder');
      focusFieldSurfaces(key, 'builder');
    });
  });
}

// ---------------------------------------------------------------------------
// Render: Full Builder
// ---------------------------------------------------------------------------
// Fields that warrant wide (2-col) or full (3-col) span in the builder grid.
const builderSpanMap = {
  summary: 'span-full',
  career_history: 'span-full',
  skills: 'span-wide',
  education: 'span-wide',
  projects: 'span-wide',
  additional_sections: 'span-wide',
};

function renderBuilder() {
  let html = '';
  let currentCategory = '';

  for (const field of fieldDefinitions) {
    if (field.category !== currentCategory) {
      currentCategory = field.category;
      const catFieldCount = fieldCategories[currentCategory]?.length || 0;
      html += `<div class="builder-category-divider span-full"><span class="builder-category-label">${escapeHtml(currentCategory)}</span><span class="builder-category-count">${catFieldCount} field${catFieldCount !== 1 ? 's' : ''}</span></div>`;
    }
    const value = state.templateState[field.key] || '';
    const isRich = field.kind === 'rich';
    const spanClass = builderSpanMap[field.key] || '';
    const reviewItem = (state.reviewBoard?.sections || []).find((s) => s.key === field.key);
    html += `
      <section class="field-card ${spanClass}" id="field-card-${field.key}">
        <div class="field-header">
          <div>
            <div class="field-title">${escapeHtml(field.label)}</div>
          </div>
          <div class="field-actions-inline">
            ${reviewItem ? `<span class="status-pill ${(reviewItem.status || 'Ready').toLowerCase().replace(/\s+/g,'-')}">${escapeHtml(reviewItem.status || 'Ready')}</span>` : ''}
            <button type="button" class="small-btn use-source-btn" data-target-key="${field.key}">Use source</button>
            ${state.restorableFields.includes(field.key) ? `<button type="button" class="small-btn restore-field-btn" data-target-key="${field.key}" title="Restore previous value">&#8630;</button>` : ''}
          </div>
        </div>
        ${state.activeTargetKey === field.key ? `<div class="field-context-note">Selecting a source section now uses its full context for this field.</div>` : ''}
        ${isRich
          ? `<textarea data-key="${field.key}" placeholder="Enter ${escapeHtml(field.label).toLowerCase()}...">${escapeHtml(value)}</textarea>`
          : `<input data-key="${field.key}" value="${escapeHtml(value)}" placeholder="Enter ${escapeHtml(field.label).toLowerCase()}..." />`}
      </section>`;
  }

  templateEditor.innerHTML = html;
  templateEditor.querySelectorAll('.use-source-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.activeTargetKey = btn.dataset.targetKey;
      renderBuilderQuickView();
      renderReviewBoard();
      renderDetectedBlocks();
      renderBuilder();
      setActiveTab('workspace');
      setStatus(`Choose a source block for ${prettyLabel(state.activeTargetKey)} or highlight a precise snippet.`);
    });
  });

  templateEditor.querySelectorAll('.restore-field-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const targetKey = btn.dataset.targetKey;
      if (!state.documentId || !targetKey) return;
      try {
        const res = await fetch(`/api/document/${state.documentId}/restore-field`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ target_key: targetKey }),
        });
        const data = await res.json();
        if (!res.ok) {
          setStatus(data.detail || 'Unable to restore this field.');
          return;
        }
        state.templateState = data.template_state;
        state.reviewBoard = data.review_board;
        state.workflowState = data.workflow_state;
        state.previewHtml = data.preview_html;
        state.recommendations = data.recommendations || [];
        state.restorableFields = data.restorable_fields || [];
        state.activeTargetKey = targetKey;
        renderBuilderQuickView();
        renderBuilder();
        renderReviewBoard();
        renderDetectedBlocks();
        renderPreview();
        renderRecommendations();
        updateDownloadButtons();
        focusFieldCard(targetKey);
        setStatus(`Restored ${prettyLabel(targetKey)}.`);
      } catch (err) {
        setStatus('Unable to restore this field right now.');
      }
    });
  });

  templateEditor.querySelectorAll('input, textarea').forEach((input) => {
    input.addEventListener('input', debounce(async () => {
      state.templateState[input.dataset.key] = input.value;
      await syncTemplate();
      renderBuilderQuickView();
    }, 400));
  });
}

// ---------------------------------------------------------------------------
// Render: Preview
// ---------------------------------------------------------------------------
function enhancePreviewPresentation() {
  const report = previewPane.querySelector('.report-preview');
  if (!report) return;
  report.style.opacity = '0';
  report.style.transform = 'translateY(12px)';
  requestAnimationFrame(() => {
    report.style.transition = 'opacity 0.5s ease, transform 0.5s cubic-bezier(0.2, 0.8, 0.2, 1)';
    report.style.opacity = '1';
    report.style.transform = 'translateY(0)';
  });
  report.dataset.reviewState = state.workflowState?.can_download
    ? 'complete'
    : (report.querySelector('.report-alert') ? 'attention' : 'ready');
  const revealNodes = report.querySelectorAll('.report-header, .meta-card, .report-grid > .report-section, .experience-card, .skill-entry');
  revealNodes.forEach((node, index) => {
    node.style.setProperty('--reveal-delay', `${Math.min(index * 55, 440)}ms`);
  });
}

function renderPreview() {
  if (!state.documentId) {
    previewPane.className = 'preview-pane empty-state';
    previewPane.innerHTML = `<div class="empty-state-content"><div class="empty-icon">&#9733;</div><h3>Your polished profile preview</h3><p>Upload and process a CV to see the recruiter-ready output here.</p></div>`;
    return;
  }
  previewPane.className = 'preview-pane';
  previewPane.innerHTML = state.previewHtml || '';
  enhancePreviewPresentation();
  const canConfirm = !!state.workflowState?.review_ready && !state.workflowState?.review_confirmed;
  reviewCompleteBtn.style.display = canConfirm ? '' : 'none';
  // Apply animated reveal class for the review-page CTA button
  if (canConfirm) {
    reviewCompleteBtn.classList.remove('cta-reveal');
    void reviewCompleteBtn.offsetWidth; // force reflow to restart animation
    reviewCompleteBtn.classList.add('cta-reveal');
  }
  if (state.workflowState?.can_download) {
    setStatus('Profile reviewed successfully. Download is now unlocked.');
  } else if (previewPane.querySelector('.report-alert')) {
    const warningCount = (state.workflowState?.warning_issues || []).length;
    setStatus(warningCount ? `Profile preview generated. Blocking issues must be cleared before download. ${warningCount} warning${warningCount !== 1 ? 's' : ''} remain visible.` : 'Profile preview generated. Clear the review issues to unlock download.');
  }
}

// ---------------------------------------------------------------------------
// Render: Detected blocks
// ---------------------------------------------------------------------------
function updateDetectedBlocksVisibility() {
  if (!detectedBlocksWrap) return;
  detectedBlocksWrap.style.display = state.structuredSource ? 'none' : '';
}

function renderDetectedBlocks() {
  updateDetectedBlocksVisibility();
  if (state.structuredSource) {
    detectedBlocks.className = 'detected-blocks empty-state';
    detectedBlocks.textContent = state.importMode === 'structured_section_text'
      ? 'Structured section text ingested directly.'
      : 'Structured CV JSON ingested directly.';
    return;
  }
  if (!state.documentId) {
    detectedBlocks.className = 'detected-blocks empty-state';
    detectedBlocks.textContent = 'Upload a CV to review detected blocks.';
    return;
  }
  const blocks = state.detectedBlocks || [];
  if (!blocks.length) {
    detectedBlocks.className = 'detected-blocks empty-state';
    detectedBlocks.textContent = 'No detected blocks available for guided review.';
    return;
  }
  detectedBlocks.className = 'detected-blocks';
  detectedBlocks.innerHTML = blocks.map((block) => {
    const suggested = fieldMap[block.mapped_field]?.label || prettyLabel(block.mapped_field);
    const selected = state.activeTargetKey && state.activeTargetKey === block.mapped_field;
    return `
      <div class="detected-block-card ${block.status} ${selected ? 'selected' : ''}" data-block-id="${block.id}" data-target-key="${block.mapped_field}">
        <div class="detected-block-top">
          <strong>${escapeHtml(block.title)}</strong>
          <span class="status-pill ${block.status === 'ready' ? 'ready' : 'needs-confirmation'}">${block.status === 'ready' ? 'Suggested' : 'Check'}</span>
        </div>
        <div class="detected-block-meta">Suggested destination: ${escapeHtml(suggested)}</div>
        <div class="detected-block-preview">${escapeHtml(block.preview || block.content || '')}</div>
        <div class="detected-block-actions">
          <button type="button" class="small-btn accept-block-btn" data-block-id="${block.id}" data-target-key="${block.mapped_field}">Apply suggestion</button>
          <button type="button" class="small-btn target-block-btn" data-block-id="${block.id}" data-target-key="${block.mapped_field}">Review manually</button>
        </div>
      </div>`;
  }).join('');

  detectedBlocks.querySelectorAll('.accept-block-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      applyDetectedBlock(btn.dataset.blockId, btn.dataset.targetKey || state.activeTargetKey || 'additional_sections');
    });
  });
  detectedBlocks.querySelectorAll('.target-block-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      dismissDetectedBlock(btn.dataset.blockId);
      state.activeTargetKey = btn.dataset.targetKey;
      renderReviewBoard();
      renderBuilderQuickView();
      renderDetectedBlocks();
      renderBuilder();
      focusFieldSurfaces(state.activeTargetKey, 'workspace');
      setStatus(`Reviewing ${prettyLabel(state.activeTargetKey)} manually. The suggestion was dismissed so you can focus on the field.`);
    });
  });
}

async function applyDetectedBlock(blockId, targetKey) {
  const block = (state.detectedBlocks || []).find((item) => item.id === blockId);
  if (!state.documentId || !block) return;
  const form = new FormData();
  form.append('selected_text', block.content);
  form.append('target_key', targetKey || block.mapped_field);
  form.append('mode', state.mappingMode || 'replace');
  form.append('source_block_id', block.id);
  form.append('source_label', block.title || 'Detected block');
  try {
    const res = await fetch(`/api/document/${state.documentId}/annotate`, { method: 'POST', body: form });
    const data = await res.json();
    if (!res.ok) {
      setStatus(data.detail || 'Unable to apply detected block.');
      return;
    }
    state.annotations = data.annotations;
    dismissDetectedBlock(block.id);
    restoreFieldStateFromResponse(data, targetKey || block.mapped_field);
    focusFieldSurfaces(state.activeTargetKey, 'workspace');
    setStatus(`Applied ${block.title} to ${fieldMap[state.activeTargetKey]?.label || prettyLabel(state.activeTargetKey)}. You can use the undo icon if you want to restore the previous value.`);
  } catch (err) {
    setStatus('Unable to apply detected block right now.');
  }
}

// ---------------------------------------------------------------------------
// Render: Annotations
// ---------------------------------------------------------------------------
function renderAnnotations() {
  if (!annotationList) return;
  if (!state.annotations.length) {
    annotationList.className = 'annotation-list empty-state';
    annotationList.textContent = 'No manual mappings yet.';
    return;
  }
  annotationList.className = 'annotation-list fade-in';
  annotationList.innerHTML = state.annotations.map((item) => `
    <div class="annotation-card">
      <strong>${escapeHtml(item.target_label)}</strong>
      <div class="annotation-meta">${escapeHtml(item.mode)} &bull; ${escapeHtml(item.source_block_id)}</div>
      <div class="pre-wrap">${escapeHtml(truncate(item.text, 200))}</div>
    </div>`).join('');
}

// ---------------------------------------------------------------------------
// Download controls
// ---------------------------------------------------------------------------
function updateDownloadButtons() {
  const canDownload = !!state.workflowState?.can_download;
  const canConfirm = !!state.workflowState?.review_ready && !state.workflowState?.review_confirmed;
  reviewCompleteBtn.style.display = canConfirm ? '' : 'none';
  downloadPreviewBtn.style.display = canDownload ? '' : 'none';
  if (canDownload) {
    downloadPreviewBtn.classList.remove('cta-reveal');
    void downloadPreviewBtn.offsetWidth;
    downloadPreviewBtn.classList.add('cta-reveal');
  } else {
    downloadPreviewBtn.classList.remove('cta-reveal');
  }
}

async function handleDownload() {
  if (!state.documentId) return;
  setStatus('Preparing your DOCX professional profile for download...');
  try {
    const res = await fetch(`/api/document/${state.documentId}/download`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ template_state: state.templateState }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      setStatus(data.detail || 'Download failed. Complete review first.');
      return;
    }
    const blob = await res.blob();
    const disposition = res.headers.get('content-disposition') || '';
    const filenameMatch = disposition.match(/filename="?([^"]+)"?/);
    const filename = filenameMatch ? filenameMatch[1] : 'Professional_Profile.docx';
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    setStatus('Profile downloaded successfully.');
  } catch (err) {
    setStatus('Network error — download failed.');
  }
}

async function handleReviewComplete() {
  if (!state.documentId) return;
  try {
    const res = await fetch(`/api/document/${state.documentId}/review-complete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ template_state: state.templateState }),
    });
    const data = await res.json();
    if (!res.ok) {
      const detail = data.detail?.message || data.detail || 'Review could not be completed.';
      setStatus(detail);
      return;
    }
    state.reviewBoard = data.review_board;
    state.workflowState = data.workflow_state;
    state.previewHtml = data.preview_html;
    state.recommendations = data.recommendations || [];
    state.restorableFields = data.restorable_fields || [];
    renderPreview();
    renderReviewBoard();
    renderRecommendations();
    updateDownloadButtons();
  } catch (err) {
    setStatus('Unable to complete review right now.');
  }
}

reviewCompleteBtn.addEventListener('click', handleReviewComplete);

downloadPreviewBtn.addEventListener('click', handleDownload);

// ---------------------------------------------------------------------------
// Selection menu / Mapping dialog
// ---------------------------------------------------------------------------
function showSelectionMenu(rect, text, blockId) {
  state.currentSelection = { ...(state.currentSelection || {}), text, blockId };
  selectionPreviewText.textContent = truncate(text, 200);

  // Build categorised field list
  renderFieldOptions('');
  selectionMenu.classList.remove('hidden');

  const menuLeft = Math.min(rect.left, window.innerWidth - 500);
  const menuTop = Math.min(rect.bottom + 8, window.innerHeight - 420);
  selectionMenu.style.left = `${Math.max(8, menuLeft)}px`;
  selectionMenu.style.top = `${Math.max(8, menuTop)}px`;

  fieldSearchInput.value = '';
  fieldSearchInput.focus();
}

function renderFieldOptions(filter) {
  const lower = filter.toLowerCase();
  let html = '';
  const suggestedField = state.currentSelection?.suggestedField || null;
  for (const [category, fields] of Object.entries(fieldCategories)) {
    const filtered = fields
      .filter((f) => !lower || f.label.toLowerCase().includes(lower) || f.key.toLowerCase().includes(lower))
      .sort((a, b) => {
        const aScore = a.key === suggestedField ? 0 : 1;
        const bScore = b.key === suggestedField ? 0 : 1;
        if (aScore !== bScore) return aScore - bScore;
        return a.label.localeCompare(b.label);
      });
    if (filtered.length === 0) continue;
    html += `<div class="selection-category-title">${escapeHtml(category)}</div><div class="selection-grid">`;
    html += filtered.map((f) => `<button type="button" class="selection-option ${f.key === suggestedField ? 'is-suggested' : ''}" data-field="${f.key}">${escapeHtml(f.label)}${f.key === suggestedField ? ' <span class="selection-option-badge">Suggested</span>' : ''}</button>`).join('');
    html += '</div>';
  }
  selectionCategories.innerHTML = html || '<p style="color:var(--muted);padding:12px;text-align:center;">No matching fields</p>';

  selectionCategories.querySelectorAll('.selection-option').forEach((btn) => {
    btn.addEventListener('click', () => assignSelection(btn.dataset.field));
  });
}

fieldSearchInput.addEventListener('input', () => {
  renderFieldOptions(fieldSearchInput.value);
});

function hideSelectionMenu() {
  selectionMenu.classList.add('hidden');
  state.currentSelection = null;
  documentViewer.querySelectorAll('.source-section.is-selected, .pdf-text-span.is-selected').forEach((el) => el.classList.remove('is-selected'));
}

selectionClose.addEventListener('click', hideSelectionMenu);

async function assignSelection(targetKey, options = {}) {
  const selection = options.selectionOverride || state.currentSelection;
  if (!state.documentId || !selection?.text) return;
  const form = new FormData();
  form.append('selected_text', selection.text);
  form.append('target_key', targetKey);
  form.append('mode', state.mappingMode);
  form.append('source_block_id', selection.blockId || 'manual');
  form.append('source_label', selection.sourceLabel || 'Source Document');

  try {
    const res = await fetch(`/api/document/${state.documentId}/annotate`, { method: 'POST', body: form });
    const data = await res.json();
    if (!res.ok) {
      setStatus(data.detail || 'Unable to assign selection.');
      return;
    }
    state.annotations = data.annotations;
    state.templateState = data.template_state;
    state.previewHtml = data.preview_html;
    state.reviewBoard = data.review_board;
    state.workflowState = data.workflow_state;
    state.recommendations = data.recommendations || [];
    state.restorableFields = data.restorable_fields || [];
    state.mappedTexts.add(selection.text);
    markMappedSelection(selection.text, selection.blockId);
    renderBuilderQuickView();
    renderBuilder();
    renderReviewBoard();
    renderDetectedBlocks();
    renderPreview();
    renderAnnotations();
    renderRecommendations();
    updateDownloadButtons();
    hideSelectionMenu();
    focusFieldCard(targetKey);
    setStatus(`Mapped to \"${fieldMap[targetKey]?.label || targetKey}\" successfully.`);
  } catch (err) {
    setStatus('Network error — unable to assign selection.');
  }
}


function markMappedSelection(text, blockId) {
  if (!text) return;
  const normalized = text.replace(/\s+/g, ' ').trim().toLowerCase();
  if (blockId && blockId.startsWith('page-')) {
    const page = document.querySelector(`.pdf-page-card[data-page-number="${blockId.replace('page-','')}"]`);
    if (!page) return;
    page.querySelectorAll('.pdf-text-span').forEach((el) => {
      const spanText = (el.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
      if (spanText && normalized.includes(spanText)) el.classList.add('mapped');
    });
  }
}

function focusFieldCard(key) {
  const el = document.getElementById(`field-card-${key}`);
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.add('flash-focus');
    setTimeout(() => el.classList.remove('flash-focus'), 1600);
  }
}

// ---------------------------------------------------------------------------
// Text selection listener
// ---------------------------------------------------------------------------
document.addEventListener('mouseup', (e) => {
  if (!documentViewer.contains(e.target)) return;
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed) return;
  let text = sel.toString().trim();
  if (!text || text.length < 2) return;
  const range = sel.getRangeAt(0);
  const rect = range.getBoundingClientRect();
  const pageCard = (sel.anchorNode?.parentElement?.closest('.pdf-page-card')) || (sel.focusNode?.parentElement?.closest('.pdf-page-card'));
  const section = (sel.anchorNode?.parentElement?.closest('.source-section')) || (sel.focusNode?.parentElement?.closest('.source-section'));
  const docCard = (sel.anchorNode?.parentElement?.closest('.real-doc-card')) || (sel.focusNode?.parentElement?.closest('.real-doc-card'));
  let blockId = 'viewer';
  let sourceLabel = 'Source Document';
  if (pageCard) {
    blockId = `page-${pageCard.dataset.pageNumber}`;
    sourceLabel = `Page ${pageCard.dataset.pageNumber}`;
  } else if (section) {
    blockId = section?.dataset.sectionId || section?.dataset.blockId || 'viewer';
    sourceLabel = section.querySelector('.source-section-title')?.textContent || 'Detected Section';
    highlightSourceSection(section);
    const sectionText = [sourceLabel, section.querySelector('.source-section-content')?.textContent || ''].join('\n').trim();
    if (sectionText.includes(text) || text.length < 20) text = sectionText;
  } else if (docCard) {
    sourceLabel = 'Original document';
  }
  state.currentSelection = { ...(state.currentSelection || {}), text, blockId, sourceLabel, suggestedField: state.currentSelection?.suggestedField || (section?.dataset?.mappedField) || null };
  showSelectionMenu(rect, text, blockId);
});

document.addEventListener('mousedown', (e) => {
  if (!selectionMenu.contains(e.target) && !documentViewer.contains(e.target)) {
    hideSelectionMenu();
  }
});

// ---------------------------------------------------------------------------
// Template sync
// ---------------------------------------------------------------------------
async function syncTemplate() {
  if (!state.documentId) return;
  try {
    const res = await fetch(`/api/document/${state.documentId}/template`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(state.templateState),
    });
    const data = await res.json();
    if (res.ok) {
      state.previewHtml = data.preview_html;
      state.reviewBoard = data.review_board;
      state.workflowState = data.workflow_state;
      state.recommendations = data.recommendations || [];
      state.restorableFields = data.restorable_fields || [];
      renderPreview();
      renderReviewBoard();
      renderDetectedBlocks();
      renderRecommendations();
      updateDownloadButtons();
    }
  } catch (err) {
    // Silent fail for background sync
  }
}

// ---------------------------------------------------------------------------
// Upload handler
// ---------------------------------------------------------------------------
function runUiStep(stepName, action) {
  try {
    action();
  } catch (err) {
    console.error(`UI step failed: ${stepName}`, err);
  }
}

function applyAnalysisResult(data) {
  state.documentId = data.document_id;
  state.textBlocks = data.text_blocks;
  state.sourceSections = data.source_sections || [];
  state.sourceView = data.source_view || null;
  state.documentProfile = data.profile;
  state.templateState = data.template_state;
  state.annotations = data.annotations;
  state.previewHtml = data.preview_html;
  state.reviewBoard = data.review_board;
  state.workflowState = data.workflow_state;
  state.detectedBlocks = data.detected_blocks || [];
  state.recommendations = data.recommendations || [];
  state.restorableFields = data.restorable_fields || [];
  state.structuredSource = !!data.structured_source;
  state.importMode = data.import_mode || null;
  state.mappedTexts = new Set();

  fileNamePill.textContent = data.filename;
  mappingModeCard.style.display = '';

  runUiStep('renderViewer', () => renderViewer());
  runUiStep('renderBuilderQuickView', () => renderBuilderQuickView());
  runUiStep('renderBuilder', () => renderBuilder());
  runUiStep('renderPreview', () => renderPreview());
  runUiStep('renderAnnotations', () => renderAnnotations());
  runUiStep('renderReviewBoard', () => renderReviewBoard());
  runUiStep('renderDetectedBlocks', () => renderDetectedBlocks());
  runUiStep('renderRecommendations', () => renderRecommendations());
  runUiStep('updateDownloadButtons', () => updateDownloadButtons());

  setActiveTab('workspace');
  setStatus(
    data.import_mode === 'structured_section_text'
      ? 'Structured section text ingested directly. Review only what needs attention.'
      : data.structured_source
        ? 'Structured CV JSON ingested directly. Review only what needs attention.'
        : 'CV processed successfully. Review sections and refine your profile.'
  );
  setLoading(false);
}

uploadForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  e.stopImmediatePropagation();

  if (state.inputMode === 'paste') {
    const pastedText = (cvPasteText.value || '').trim();
    if (!pastedText) {
      setStatus('Please paste your CV text before analysing.');
      return;
    }

    setLoading(true);
    setStatus('Analysing pasted CV text, checking for structured JSON, and extracting sections...');

    let data;
    try {
      const res = await fetch('/api/upload-text', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: pastedText }),
      });
      data = await res.json();
      if (!res.ok) {
        setStatus(data.detail || 'Analysis failed. Check your pasted text and try again.');
        setLoading(false, { completed: false });
        return;
      }
    } catch (err) {
      setStatus('Network error - is the server running?');
      setLoading(false, { completed: false });
      return;
    }

    setUploadZoneState('processed', data.filename);
    applyAnalysisResult(data);
    return;
  }

  const input = cvFileInput;
  if (!input.files.length) {
    setStatus('Please select a CV file first.');
    return;
  }

  const selectedFile = input.files[0];
  setLoading(true);
  setStatus('Analysing your CV and extracting sections...');
  const formData = new FormData();
  formData.append('file', selectedFile);

  let data;
  try {
    const res = await fetch('/api/upload', { method: 'POST', body: formData });
    data = await res.json();
    if (!res.ok) {
      setStatus(data.detail || 'Upload failed. Please try a different file.');
      setUploadZoneState(getUploadZoneRestingState(), getUploadZoneFileName());
      setLoading(false, { completed: false });
      return;
    }
  } catch (err) {
    setStatus('Network error - is the server running?');
    setUploadZoneState(getUploadZoneRestingState(), getUploadZoneFileName());
    setLoading(false, { completed: false });
    return;
  }

  input.value = '';
  setUploadZoneState('processed', data.filename);
  applyAnalysisResult(data);
});

uploadForm.addEventListener('submit', async (e) => {
  e.preventDefault();

  // --- Paste mode ---
  if (state.inputMode === 'paste') {
    const pastedText = (cvPasteText.value || '').trim();
    if (!pastedText) {
      setStatus('Please paste your CV text before analysing.');
      return;
    }
    setLoading(true);
    setStatus('Analysing pasted CV text, checking for structured JSON, and extracting sections...');
    try {
      const res = await fetch('/api/upload-text', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: pastedText }),
      });
      const data = await res.json();
      if (!res.ok) {
        setStatus(data.detail || 'Analysis failed. Check your pasted text and try again.');
        setLoading(false, { completed: false });
        return;
      }
      setUploadZoneState('processed', data.filename);
      applyAnalysisResult(data);
    } catch (err) {
      setStatus('Network error — is the server running?');
      setLoading(false, { completed: false });
    }
    return;
  }

  // --- File mode ---
  const input = cvFileInput;
  if (!input.files.length) {
    setStatus('Please select a CV file first.');
    return;
  }
  const selectedFile = input.files[0];
  setLoading(true);
  setStatus('Analysing your CV and extracting sections...');
  const formData = new FormData();
  formData.append('file', selectedFile);

  try {
    const res = await fetch('/api/upload', { method: 'POST', body: formData });
    const data = await res.json();
    if (!res.ok) {
      setStatus(data.detail || 'Upload failed. Please try a different file.');
      setUploadZoneState(getUploadZoneRestingState(), getUploadZoneFileName());
      setLoading(false, { completed: false });
      return;
    }
    input.value = '';
    setUploadZoneState('processed', data.filename);
    applyAnalysisResult(data);
  } catch (err) {
    setStatus('Network error — is the server running?');
    setUploadZoneState(getUploadZoneRestingState(), getUploadZoneFileName());
    setLoading(false, { completed: false });
  }
});

// ---------------------------------------------------------------------------
// Initial render
// ---------------------------------------------------------------------------
viewPromptBtn.addEventListener('click', togglePromptPreview);
copyPromptBtn.addEventListener('click', copyStructuringPrompt);
loadStructuringPrompt();

renderViewer();
renderBuilderQuickView();
renderBuilder();
renderRecommendations();
