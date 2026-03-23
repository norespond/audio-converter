const pageFamily = document.body.dataset.family || 'audio';
const drop = document.getElementById('drop');
const fileInput = document.getElementById('file');
const inputModeInput = document.getElementById('input_mode');
const formatInput = document.getElementById('format');
const bitrateInput = document.getElementById('bitrate');
const sampleRateInput = document.getElementById('sample_rate');
const channelsInput = document.getElementById('channels');
const retentionInput = document.getElementById('retention_minutes');
const confirmBtn = document.getElementById('confirmBtn');
const resetBtn = document.getElementById('resetBtn');
const familyTitle = document.getElementById('familyTitle');
const familyHint = document.getElementById('familyHint');
const summary = document.getElementById('summary');
const queueEl = document.getElementById('queue');
const overallText = document.getElementById('overallText');
const overallProgress = document.getElementById('overallProgress');
const etaText = document.getElementById('etaText');
const retentionText = document.getElementById('retentionText');
const controlFields = Array.from(document.querySelectorAll('[data-control]'));

const FALLBACK_FAMILIES = {
  audio: {
    key: 'audio',
    label: '音频',
    accept: 'audio/',
    extensions: ['wav', 'mp3', 'ogg', 'flac', 'm4a', 'aac', 'opus'],
    default_format: 'mp3',
    supports: { bitrate: true, sample_rate: true, channels: true },
    formats: ['wav', 'mp3', 'ogg', 'flac', 'm4a', 'aac', 'opus'],
  },
  video: {
    key: 'video',
    label: '视频',
    accept: 'video/',
    extensions: ['mp4', 'webm', 'mkv', 'mov', 'avi', 'm4v', 'ts', 'mts', 'm2ts'],
    default_format: 'mp4',
    supports: { bitrate: true, sample_rate: false, channels: false },
    formats: ['mp4', 'webm', 'mkv', 'mov', 'avi'],
  },
  image: {
    key: 'image',
    label: '图片',
    accept: 'image/',
    extensions: ['png', 'jpg', 'jpeg', 'webp', 'bmp', 'gif', 'tif', 'tiff'],
    default_format: 'png',
    supports: { bitrate: false, sample_rate: false, channels: false },
    formats: ['png', 'jpg', 'jpeg', 'webp', 'bmp', 'gif', 'tif', 'tiff'],
  },
  document: {
    key: 'document',
    label: '文档',
    accept: 'text/',
    extensions: ['txt', 'md', 'markdown', 'html', 'htm'],
    default_format: 'md',
    supports: { bitrate: false, sample_rate: false, channels: false },
    formats: ['txt', 'md', 'html'],
  },
};

const FAMILY_META = {
  audio: { title: '音频转换', hint: '仅显示音频转换相关参数。' },
  video: { title: '视频转换', hint: '仅显示视频转换相关参数。' },
  image: { title: '图片转换', hint: '仅显示图片转换相关参数。' },
  document: { title: '文档转换', hint: '仅支持 txt、md、html 之间的互转。' },
};

const state = {
  family: FALLBACK_FAMILIES[pageFamily] || FALLBACK_FAMILIES.audio,
  items: [],
  running: false,
  currentXhr: null,
  runId: 0,
  completedDurations: [],
  retentionMinutes: [5, 10, 30, 60],
  defaultRetentionMinutes: 10,
  inputMode: 'multiple',
};

const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
const formatBytes = (bytes) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
};

const formatDuration = (ms) => {
  const safe = Math.max(0, Math.round(ms / 1000));
  const h = Math.floor(safe / 3600);
  const m = Math.floor((safe % 3600) / 60);
  const s = safe % 60;
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
};

const formatClock = (ts) => new Date(ts).toLocaleTimeString('zh-CN', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

const retentionLabel = (minutes) => `${minutes} 分钟`;
const getRetentionMinutes = () => Number(retentionInput.value || state.defaultRetentionMinutes);
const makeId = () => (window.crypto && typeof window.crypto.randomUUID === 'function')
  ? window.crypto.randomUUID()
  : `item-${Date.now()}-${Math.random().toString(16).slice(2)}`;

const getFamily = () => state.family;
const getFamilyFormats = () => getFamily().formats || [];

const populateSelect = (select, values, selectedValue, renderLabel = (value) => String(value)) => {
  select.innerHTML = '';
  values.forEach((value) => {
    const option = document.createElement('option');
    option.value = String(value);
    option.textContent = renderLabel(value);
    if (String(value) === String(selectedValue)) option.selected = true;
    select.appendChild(option);
  });
};

const updateFileAccept = () => {
  const family = getFamily();
  const extensions = (family.extensions || []).map((ext) => `.${ext}`);
  const accept = [family.accept ? `${family.accept}*` : null, ...extensions].filter(Boolean).join(',');
  fileInput.setAttribute('accept', accept);
};

const updateInputMode = () => {
  state.inputMode = inputModeInput.value || 'multiple';
  fileInput.multiple = state.inputMode === 'multiple';
};

const updateConfirmButton = () => {
  const hasWaiting = state.items.some((item) => item.status === 'waiting');
  confirmBtn.disabled = state.running || !hasWaiting;
};

const updateVisibleControls = () => {
  const supports = getFamily().supports || {};
  controlFields.forEach((field) => {
    const key = field.dataset.control;
    field.classList.toggle('hidden', !supports[key]);
  });
};

const updateRetentionHeader = () => {
  retentionText.textContent = `处理后的文件会保留 ${retentionLabel(getRetentionMinutes())}，到期后自动删除。`;
};

const applyFamilyConfig = () => {
  const family = getFamily();
  const meta = FAMILY_META[family.key] || FAMILY_META.audio;
  familyTitle.textContent = meta.title;
  familyHint.textContent = meta.hint;
  updateFileAccept();
  updateInputMode();
  updateVisibleControls();
  updateRetentionHeader();
  formatInput.disabled = getFamilyFormats().length <= 1;
  updateConfirmButton();
};

const populateFamilyData = async () => {
  try {
    const response = await fetch('/capabilities');
    if (!response.ok) throw new Error('failed');
    const capabilities = await response.json();
    const family = (capabilities.families || []).find((item) => item.key === pageFamily);
    if (family) {
      state.family = {
        key: family.key,
        label: family.label,
        accept: family.accept,
        extensions: family.extensions || FALLBACK_FAMILIES[family.key].extensions,
        default_format: family.default_format || FALLBACK_FAMILIES[family.key].default_format,
        supports: family.supports || FALLBACK_FAMILIES[family.key].supports,
        formats: (family.formats || []).map((item) => item.value),
      };
    }
    state.defaultRetentionMinutes = capabilities.default_retention_minutes || 10;
    state.retentionMinutes = capabilities.retention_minutes || [5, 10, 30, 60];
  } catch {
    // Fallbacks already cover the page.
  }
};

const initializeControls = () => {
  populateSelect(formatInput, getFamilyFormats(), getFamily().default_format, (value) => value);
  populateSelect(retentionInput, state.retentionMinutes, state.defaultRetentionMinutes, (value) => `${value} 分钟`);
  populateSelect(bitrateInput, [64, 96, 128, 160, 192, 256, 320], 192, (value) => `${value} kbps`);
  populateSelect(sampleRateInput, [8000, 12000, 16000, 22050, 24000, 32000, 44100, 48000], 16000, (value) => `${value} Hz`);
  populateSelect(channelsInput, [1, 2], 2, (value) => (Number(value) === 1 ? '单声道' : '立体声'));
};

const estimateProcessingMs = (item) => {
  const sizeMb = Math.max(item.file.size / 1024 / 1024, 0.05);
  const base = item.family === 'video'
    ? 9000
    : item.family === 'image'
      ? 1800
      : item.family === 'document'
        ? 1000
        : item.format === 'wav'
          ? 3200
          : 7000;
  return clamp(sizeMb * base, 1200, 10 * 60 * 1000);
};

const estimateUploadMs = (item, now) => {
  const sizeMb = Math.max(item.file.size / 1024 / 1024, 0.05);
  if (item.status === 'uploading' && item.uploadStartedAt && item.uploadPercent > 0) {
    const elapsed = Math.max(now - item.uploadStartedAt, 1);
    return Math.max(1000, elapsed / (item.uploadPercent / 100));
  }
  return clamp(sizeMb * 1200, 1200, 120000);
};

const estimateItemRemainingMs = (item, now) => {
  if (['done', 'failed', 'expired'].includes(item.status)) return 0;
  const processing = estimateProcessingMs(item);
  const upload = estimateUploadMs(item, now);
  if (item.status === 'waiting') return upload + processing;
  if (item.status === 'uploading') {
    const uploadRemaining = item.uploadPercent > 0 ? Math.max(0, upload - (now - item.uploadStartedAt)) : upload;
    return uploadRemaining + processing;
  }
  if (item.status === 'processing') {
    const elapsed = item.processingStartedAt ? Math.max(now - item.processingStartedAt, 0) : 0;
    return Math.max(0, processing - elapsed);
  }
  return upload + processing;
};

const getItemProgress = (item, now) => {
  if (['done', 'failed', 'expired'].includes(item.status)) return 100;
  if (item.status === 'waiting') return 0;
  if (item.status === 'uploading') return Math.min(item.uploadPercent * 0.4, 40);
  if (item.status === 'processing') {
    const estimate = estimateProcessingMs(item);
    const elapsed = item.processingStartedAt ? Math.max(now - item.processingStartedAt, 0) : 0;
    return 40 + Math.min(elapsed / Math.max(estimate, 1), 0.99) * 60;
  }
  return 0;
};

const setSummary = () => {
  const total = state.items.length;
  const waiting = state.items.filter((item) => item.status === 'waiting').length;
  const uploading = state.items.filter((item) => item.status === 'uploading').length;
  const processing = state.items.filter((item) => item.status === 'processing').length;
  const done = state.items.filter((item) => item.status === 'done').length;
  const failed = state.items.filter((item) => item.status === 'failed').length;
  const expired = state.items.filter((item) => item.status === 'expired').length;
  summary.innerHTML = '';
  if (!total) {
    summary.textContent = '尚未添加文件。';
    return;
  }

  [`总数 ${total}`, `等待 ${waiting}`, `上传中 ${uploading}`, `处理中 ${processing}`, `完成 ${done}`, `失败 ${failed}`, `已删除 ${expired}`].forEach((text) => {
    const chip = document.createElement('span');
    chip.className = 'chip';
    chip.textContent = text;
    summary.appendChild(chip);
  });
};

const getStatusClass = (status) => ({
  uploading: 'status-badge status-uploading',
  processing: 'status-badge status-processing',
  done: 'status-badge status-done',
  failed: 'status-badge status-failed',
  expired: 'status-badge status-expired',
  waiting: 'status-badge status-waiting',
}[status] || 'status-badge status-waiting');

const setItemStatus = (item, status, label) => {
  item.status = status;
  item.statusEl.className = getStatusClass(status);
  item.statusEl.textContent = label;
  setSummary();
};

const setItemError = (item, message) => {
  item.errorEl.style.display = message ? 'block' : 'none';
  item.errorEl.textContent = message || '';
};

const updateOverall = (now = Date.now()) => {
  const total = state.items.length;
  if (!total) {
    overallText.textContent = '0%';
    overallProgress.value = 0;
    etaText.textContent = '预计剩余时间：计算中';
    return;
  }

  let sum = 0;
  let eta = 0;
  let complete = 0;

  state.items.forEach((item) => {
    sum += getItemProgress(item, now);
    eta += estimateItemRemainingMs(item, now);
    if (['done', 'failed', 'expired'].includes(item.status)) complete += 1;
    if (item.status === 'done' && item.expiresAt) {
      const left = item.expiresAt - now;
      if (left <= 0) {
        item.detailEl.textContent = '文件已自动删除。';
        item.actionsEl.innerHTML = '';
        item.progressEl.value = 100;
        item.url = '';
        setItemStatus(item, 'expired', '已删除');
      } else {
        item.detailEl.textContent = `文件保留至 ${formatClock(item.expiresAt)}，剩余 ${formatDuration(left)}。`;
      }
    } else if (item.status === 'processing') {
      item.detailEl.textContent = `正在处理，预计还需 ${formatDuration(estimateItemRemainingMs(item, now))}。`;
    } else if (item.status === 'uploading') {
      item.detailEl.textContent = `正在上传，预计还需 ${formatDuration(estimateItemRemainingMs(item, now))}。`;
    } else if (item.status === 'waiting') {
      item.detailEl.textContent = `已加入批量队列，预计排队时长 ${formatDuration(estimateItemRemainingMs(item, now))}。`;
    }
  });

  const overall = Math.max(0, Math.min(100, sum / total));
  overallProgress.value = overall;
  overallText.textContent = `${overall.toFixed(0)}%`;
  etaText.textContent = complete === total ? '预计剩余时间：已完成' : (eta > 0 ? `预计剩余时间：${formatDuration(eta)}` : '预计剩余时间：计算中');
};

const createItemNode = (item) => {
  const node = document.createElement('article');
  node.className = 'item';
  node.dataset.id = item.id;
  node.innerHTML = `
    <div class="item-head">
      <div>
        <div class="file-name"></div>
        <div class="file-meta"></div>
      </div>
      <div class="status-line"><span class="status-badge status-waiting"></span></div>
    </div>
    <progress value="0" max="100"></progress>
    <div class="detail"></div>
    <div class="item-actions"></div>
    <div class="error-text" style="display:none;"></div>
  `;
  node.querySelector('.file-name').textContent = item.file.name;
  node.querySelector('.file-meta').textContent = `${formatBytes(item.file.size)} · ${item.familyLabel} · 输出 ${item.format} · 保留 ${retentionLabel(item.retentionMinutes)}`;
  node.querySelector('.status-badge').textContent = '等待上传';
  node.querySelector('.detail').textContent = '已加入批量队列，等待开始处理。';
  queueEl.appendChild(node);
  item.node = node;
  item.progressEl = node.querySelector('progress');
  item.statusEl = node.querySelector('.status-badge');
  item.detailEl = node.querySelector('.detail');
  item.actionsEl = node.querySelector('.item-actions');
  item.errorEl = node.querySelector('.error-text');
};

const resetQueue = () => {
  state.runId += 1;
  if (state.currentXhr) {
    try { state.currentXhr.abort(); } catch {}
  }
  state.items.forEach((item) => {
    if (item.url) URL.revokeObjectURL(item.url);
  });
  state.items = [];
  state.running = false;
  state.currentXhr = null;
  queueEl.innerHTML = '';
  setSummary();
  updateRetentionHeader();
  updateOverall();
  updateConfirmButton();
};

const parseError = async (xhr) => (
  xhr.response && typeof xhr.response === 'object'
    ? (xhr.response.detail || xhr.statusText || `错误 ${xhr.status}`)
    : (xhr.statusText || `错误 ${xhr.status}`)
);

const matchesFamily = (file) => {
  const family = getFamily();
  if (!file || !family) return false;
  const ext = (file.name.split('.').pop() || '').toLowerCase();
  if (file.type && file.type.startsWith(family.accept)) return true;
  return (family.extensions || []).includes(ext);
};

const addFiles = (files) => {
  const accepted = Array.from(files || []);
  if (!accepted.length) return;

  const family = getFamily();
  const retentionMinutes = getRetentionMinutes();
  const uploadFiles = state.inputMode === 'single' ? accepted.slice(0, 1) : accepted;

  uploadFiles.forEach((file) => {
    const item = {
      id: makeId(),
      file,
      family: family.key,
      familyLabel: family.label,
      format: formatInput.value,
      retentionMinutes,
      status: 'waiting',
      progress: 0,
      uploadPercent: 0,
      startedAt: 0,
      uploadStartedAt: 0,
      processingStartedAt: 0,
      completedAt: 0,
      expiresAt: 0,
      downloadUrl: '',
      downloadName: '',
      url: '',
      node: null,
      progressEl: null,
      statusEl: null,
      detailEl: null,
      actionsEl: null,
      errorEl: null,
    };
    state.items.push(item);
    createItemNode(item);

    if (!matchesFamily(file)) {
      setItemStatus(item, 'failed', '失败');
      setItemError(item, `请上传${family.label}文件。`);
      item.detailEl.textContent = `该文件类型与当前“${family.label}”页面不匹配，已跳过。`;
      item.progressEl.value = 100;
    } else if (file.size > 40 * 1024 * 1024) {
      setItemStatus(item, 'failed', '失败');
      setItemError(item, '文件超过 40MB 限制。');
      item.detailEl.textContent = '文件太大，已跳过。';
      item.progressEl.value = 100;
    }
  });

  setSummary();
  updateRetentionHeader();
  updateOverall();
  updateConfirmButton();
};

const updateCurrentProgress = (item, percent) => {
  item.uploadPercent = percent;
  item.progressEl.value = percent;
};

const sendFile = (item, runId) => new Promise((resolve) => {
  const xhr = new XMLHttpRequest();
  state.currentXhr = xhr;
  xhr.open('POST', '/convert/');
  xhr.responseType = 'json';

  xhr.upload.onprogress = (e) => {
    if (runId !== state.runId) return;
    if (e.lengthComputable) {
      updateCurrentProgress(item, (e.loaded / e.total) * 100);
      if (item.status !== 'uploading') {
        setItemStatus(item, 'uploading', '上传中');
        item.uploadStartedAt = item.uploadStartedAt || Date.now();
        item.startedAt = item.startedAt || Date.now();
      }
      updateOverall();
    }
  };

  xhr.upload.onload = () => {
    if (runId !== state.runId) return;
    updateCurrentProgress(item, 100);
    item.processingStartedAt = Date.now();
    setItemStatus(item, 'processing', '处理中');
    updateOverall();
  };

  xhr.onload = async () => {
    if (runId !== state.runId) {
      resolve();
      return;
    }

    if (xhr.status === 200) {
      const data = xhr.response || {};
      item.completedAt = Date.now();
      item.expiresAt = new Date(data.expires_at).getTime();
      item.downloadUrl = data.download_url;
      item.downloadName = data.download_name || `${item.file.name.replace(/\.[^/.]+$/, '')}.${item.format}`;
      item.progressEl.value = 100;
      setItemStatus(item, 'done', '完成');
      setItemError(item, '');
      state.completedDurations.push(item.completedAt - item.startedAt);
      item.detailEl.textContent = `转换完成，文件保留至 ${formatClock(item.expiresAt)}。`;
      item.actionsEl.innerHTML = '';

      const downloadLink = document.createElement('a');
      downloadLink.href = data.download_url;
      downloadLink.className = 'btn';
      downloadLink.textContent = '下载文件';
      downloadLink.download = item.downloadName;
      item.actionsEl.appendChild(downloadLink);

      const note = document.createElement('span');
      note.className = 'hint';
      note.textContent = `将自动删除：${retentionLabel(item.retentionMinutes)}`;
      item.actionsEl.appendChild(note);

      updateRetentionHeader();
      updateOverall();
      resolve();
      return;
    }

    const detail = await parseError(xhr);
    setItemStatus(item, 'failed', '失败');
    setItemError(item, detail);
    item.detailEl.textContent = '转换失败。';
    updateOverall();
    resolve();
  };

  xhr.onerror = () => {
    if (runId !== state.runId) {
      resolve();
      return;
    }
    setItemStatus(item, 'failed', '失败');
    setItemError(item, '请求发送失败，请稍后重试。');
    item.detailEl.textContent = '请求发送失败。';
    updateOverall();
    resolve();
  };

  xhr.onabort = () => resolve();

  const family = getFamily();
  const supports = family.supports || {};
  const fd = new FormData();
  fd.append('file', item.file);
  fd.append('family', item.family);
  fd.append('format', item.format);
  if (supports.bitrate) fd.append('bitrate', bitrateInput.value);
  if (supports.sample_rate) fd.append('sample_rate', sampleRateInput.value);
  if (supports.channels) fd.append('channels', channelsInput.value);
  fd.append('retention_minutes', String(item.retentionMinutes));
  xhr.send(fd);
});

const startQueue = async () => {
  if (state.running) return;
  const runId = ++state.runId;
  state.running = true;
  updateConfirmButton();

  try {
    while (true) {
      const nextItem = state.items.find((item) => item.status === 'waiting');
      if (!nextItem) break;

      nextItem.startedAt = Date.now();
      nextItem.uploadStartedAt = Date.now();
      updateCurrentProgress(nextItem, 0);
      setItemStatus(nextItem, 'uploading', '上传中');
      nextItem.detailEl.textContent = '正在上传，准备开始转换。';
      await sendFile(nextItem, runId);
    }
  } finally {
    if (runId === state.runId) state.currentXhr = null;
    state.running = false;
    updateOverall();
    setSummary();
    updateConfirmButton();
  }
};

const refreshPendingItems = () => {
  state.items.forEach((item) => {
    if (item.status === 'waiting') {
      item.format = formatInput.value;
      item.retentionMinutes = getRetentionMinutes();
      item.node.querySelector('.file-meta').textContent = `${formatBytes(item.file.size)} · ${item.familyLabel} · 输出 ${item.format} · 保留 ${retentionLabel(item.retentionMinutes)}`;
      item.detailEl.textContent = `已加入批量队列，等待开始处理。保留后将自动删除 ${retentionLabel(item.retentionMinutes)}。`;
    }
  });
};

['dragenter', 'dragover'].forEach((eventName) => drop.addEventListener(eventName, (ev) => {
  ev.preventDefault();
  drop.classList.add('dragover');
}));

['dragleave', 'drop'].forEach((eventName) => drop.addEventListener(eventName, (ev) => {
  ev.preventDefault();
  drop.classList.remove('dragover');
}));

drop.addEventListener('drop', (ev) => {
  const files = ev.dataTransfer.files;
  if (files && files.length > 0) addFiles(files);
});

fileInput.addEventListener('change', (e) => {
  const files = e.target.files;
  if (files && files.length > 0) addFiles(files);
  fileInput.value = '';
});

confirmBtn.addEventListener('click', () => {
  startQueue();
});

resetBtn.addEventListener('click', () => {
  fileInput.value = '';
  resetQueue();
});

[inputModeInput, formatInput, bitrateInput, sampleRateInput, channelsInput, retentionInput].forEach((input) => input.addEventListener('change', () => {
  if (input === inputModeInput) {
    updateInputMode();
  }
  updateRetentionHeader();
  refreshPendingItems();
  updateConfirmButton();
  updateOverall();
}));

const initialize = async () => {
  await populateFamilyData();
  initializeControls();
  applyFamilyConfig();
  setSummary();
  updateRetentionHeader();
  updateOverall();
  setInterval(() => updateOverall(), 1000);
};

initialize().catch((error) => {
  console.error('Failed to initialize converter page:', error);
});
