'use strict';
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const LANGS = { en: 'English', es: 'Spanish', fr: 'French', de: 'German', it: 'Italian', pt: 'Portuguese', hi: 'Hindi',
  ar: 'Arabic', zh: 'Chinese', ja: 'Japanese', ko: 'Korean', ru: 'Russian', tr: 'Turkish', nl: 'Dutch', pl: 'Polish',
  sv: 'Swedish', da: 'Danish', fi: 'Finnish', el: 'Greek', he: 'Hebrew', ms: 'Malay', no: 'Norwegian', sw: 'Swahili', bn: 'Bengali' };
const STYLE = ['exaggeration', 'cfg_weight', 'temperature', 'speed', 'sentence_pause', 'paragraph_pause'];
const state = { status: null, voices: [], projects: [], project: null, task: 'script', transcript: null, poll: null };

// ---------- helpers ----------
function csrf() { return (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || ''; }
async function api(path, { method = 'GET', body, form } = {}) {
  const opts = { method, headers: { 'X-CSRFToken': csrf() } };
  if (form) opts.body = form;
  else if (body) { opts.body = JSON.stringify(body); opts.headers['Content-Type'] = 'application/json'; }
  const resp = await fetch(path, opts);
  const data = await resp.json().catch(() => ({ error: `Server error (${resp.status})` }));
  if (!resp.ok) throw new Error(data.error || `Request failed (${resp.status})`);
  return data;
}
let toastTimer;
function toast(msg, error = false) {
  const t = $('toast');
  t.textContent = msg; t.className = 'toast' + (error ? ' error' : '');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.add('hidden'), error ? 7000 : 3000);
}
const guard = (fn) => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message, true); } };
function fmtTime(s) { s = Math.round(s || 0); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; }
function options(sel, items, value) {
  sel.innerHTML = items.map(([v, label]) => `<option value="${esc(v)}">${esc(label)}</option>`).join('');
  if (value != null && items.some(([v]) => String(v) === String(value))) sel.value = value;
}
function download(name, text) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' })); a.download = name; a.click();
}
function show(view) {
  document.querySelectorAll('.view').forEach((v) => v.classList.toggle('active', v.id === 'view-' + view));
  document.querySelectorAll('#nav button').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
  location.hash = view;
}
/** Poll a job until it ends; onTick gets each update. */
async function watch(jobId, onTick) {
  for (;;) {
    const job = await api(`/api/jobs/${jobId}/`);
    onTick && onTick(job);
    if (['done', 'error', 'cancelled'].includes(job.status)) return job;
    await new Promise((r) => setTimeout(r, 1200));
  }
}
document.querySelectorAll('input[type=range]').forEach((r) => {
  const out = r.parentElement.querySelector('output');
  const sync = () => { if (out) out.textContent = r.value; };
  r.addEventListener('input', sync); r.sync = sync; sync();
});

// ---------- boot ----------
async function loadStatus() {
  state.status = await api('/api/status/');
  const d = state.status.device;
  $('device').textContent = d.gpu ? `${d.gpu} · ${d.vram_gb} GB` : 'Running on CPU';
  const llm = state.status.llm;
  $('ai-warning').classList.toggle('hidden', llm.ready);
  $('ai-warning').innerHTML = esc(llm.note) + ' <a href="#" data-goto="settings">Open Settings</a>';
  $('ai-model').textContent = llm.ready ? `Model: ${llm.model}` : '';
  $('ai-tasks').innerHTML = state.status.tasks.map((t) => `<button data-task="${t.id}">${esc(t.label)}</button>`).join('');
  setTask(state.task);
}
async function loadVoices() {
  state.voices = await api('/api/voices/');
  renderVoices();
  $('no-voice-hint').classList.toggle('hidden', state.voices.some((v) => v.ready));
}
async function loadProjects() {
  state.projects = await api('/api/projects/');
  $('project-list').innerHTML = state.projects.map((p) => `
    <div class="item ${state.project && state.project.id === p.id ? 'active' : ''}" data-id="${p.id}">
      <div class="t">${esc(p.title)}</div>
      <div class="s">${p.words} words · ${p.status}${p.stats.duration ? ' · ' + fmtTime(p.stats.duration) : ''}</div>
    </div>`).join('') || '<div class="muted small">No narrations yet.</div>';
}

// ---------- narrate ----------
function engine(id) { return state.status.engines.find((e) => e.id === id) || state.status.engines[0]; }
function fillEngineFields(p) {
  const eng = engine(p.engine);
  options($('p-engine'), state.status.engines.map((e) => [e.id, e.label + (e.available ? '' : ' (not installed)')]), eng.id);
  options($('p-language'), eng.languages.map((c) => [c, LANGS[c] || c]), p.language);
  $('p-voice-wrap').classList.toggle('hidden', !eng.clones);
  $('p-stock-wrap').classList.toggle('hidden', eng.clones);
  options($('p-voice'), state.voices.filter((v) => v.ready).map((v) => [v.id, v.name]), p.voice_id);
  const stock = (eng.stock_voices || []).filter((v) => !v.lang || v.lang === $('p-language').value);
  options($('p-stock'), stock.map((v) => [v.id, v.label]), p.stock_voice);
  document.querySelectorAll('[data-ctl]').forEach((el) => el.classList.toggle('hidden', !eng.controls.includes(el.dataset.ctl)));
  $('engine-note').classList.toggle('hidden', !eng.note);
  $('engine-note').textContent = eng.note || '';
  $('p-tags').textContent = eng.tags ? `Sound tags: ${eng.tags.join(' ')}` : '';
}
function countScript() {
  const words = ($('p-script').value.match(/[\w']+/g) || []).length;
  $('p-count').textContent = `${words} words · about ${fmtTime(words / 150 * 60)} spoken`;
}
function renderProject() {
  const p = state.project;
  $('no-project').classList.toggle('hidden', !!p);
  $('project').classList.toggle('hidden', !p);
  if (!p) return;
  $('p-title').value = p.title;
  $('p-script').value = p.script;
  fillEngineFields(p);
  for (const k of STYLE) if (p.settings[k] != null) { $('s-' + k).value = p.settings[k]; $('s-' + k).sync(); }
  $('s-verify').checked = p.settings.verify !== false;
  $('s-polish').checked = p.settings.polish !== false;
  countScript();
  renderOutput();
  if (p.job) follow(p.job.id);
}
function renderOutput() {
  const p = state.project;
  const busy = !!p.job;
  $('p-render').disabled = $('p-render-all').disabled = busy;
  $('p-cancel').classList.toggle('hidden', !busy);
  $('p-progress').classList.toggle('hidden', !busy);
  if (!busy) $('p-status').textContent = p.status === 'error' ? 'Last render failed. See the message and try again.' : '';
  const has = !!p.mp3 && p.status === 'done';
  $('p-result').classList.toggle('hidden', !has);
  if (has) {
    const bust = '?v=' + encodeURIComponent(p.updated_at);
    $('p-audio').src = p.mp3 + bust;
    $('dl-mp3').href = p.mp3 + bust; $('dl-wav').href = p.wav + bust;
    $('dl-srt').href = `/api/projects/${p.id}/captions.srt`; $('dl-vtt').href = `/api/projects/${p.id}/captions.vtt`;
    const s = p.stats;
    $('p-stats').textContent = `${fmtTime(s.duration)} · ${s.lufs} LUFS · peak ${s.true_peak} dBTP · ${s.segments} sentences` +
      (s.flagged ? ` · ${s.flagged} to review (marked below)` : ' · all takes passed the check');
  }
  $('seg-head').classList.toggle('hidden', !p.segments.length);
  $('segments').innerHTML = p.segments.map((s) => {
    const badge = s.status === 'error' ? '<span class="badge bad">failed</span>'
      : s.status === 'pending' ? '<span class="badge">not recorded</span>'
      : s.score == null ? '<span class="badge">unchecked</span>'
      : `<span class="badge ${s.status === 'flagged' ? 'warn' : 'good'}">${Math.round(s.score * 100)}% match</span>`;
    const heard = s.status === 'flagged' && s.heard ? `<div class="heard">Heard: “${esc(s.heard)}”</div>` : '';
    const err = s.error ? `<div class="heard">${esc(s.error)}</div>` : '';
    return `<div class="seg" data-id="${s.id}">
      <div class="n">${s.index + 1}</div>
      <div><div class="txt" contenteditable="true" spellcheck="false">${esc(s.text)}</div>${heard}${err}</div>
      <div class="acts">${badge}
        ${s.audio ? `<button class="mini" data-act="play" data-src="${s.audio}">▶</button>` : ''}
        <button class="mini" data-act="redo" ${busy ? 'disabled' : ''}>Re-record</button></div>
    </div>`;
  }).join('');
}
function collectProject() {
  const settings = { verify: $('s-verify').checked, polish: $('s-polish').checked };
  for (const k of STYLE) settings[k] = Number($('s-' + k).value);
  return { title: $('p-title').value, script: $('p-script').value, engine: $('p-engine').value,
    voice_id: Number($('p-voice').value) || null, stock_voice: $('p-stock').value, language: $('p-language').value, settings };
}
async function saveProject() {
  if (!state.project) return;
  const job = state.project.job;
  state.project = await api(`/api/projects/${state.project.id}/`, { method: 'PATCH', body: collectProject() });
  state.project.job = state.project.job || job;
}
async function openProject(id) {
  state.project = id ? await api(`/api/projects/${id}/`) : null;
  renderProject(); loadProjects();
}
async function follow(jobId) {
  if (state.poll === jobId) return;
  state.poll = jobId;
  const pid = state.project.id;
  const job = await watch(jobId, (j) => {
    if (!state.project || state.project.id !== pid) return;
    state.project.job = j; $('p-render').disabled = $('p-render-all').disabled = true;
    $('p-cancel').classList.remove('hidden'); $('p-progress').classList.remove('hidden');
    $('p-progress').firstElementChild.style.width = Math.round(j.progress * 100) + '%';
    $('p-status').textContent = j.status === 'queued' ? 'Waiting for another job to finish' : j.message;
  });
  state.poll = null;
  if (job.status === 'error') toast(job.message, true);
  if (state.project && state.project.id === pid) await openProject(pid); else loadProjects();
}
async function render(all) {
  await saveProject();
  const out = await api(`/api/projects/${state.project.id}/render/`, { method: 'POST', body: { all } });
  state.project = out.project; state.project.job = out.job;
  renderOutput(); follow(out.job.id);
}
$('new-project').onclick = guard(async () => {
  const p = await api('/api/projects/', { method: 'POST', body: { title: 'Untitled narration' } });
  await openProject(p.id); $('p-title').select();
});
$('project-list').onclick = guard(async (e) => {
  const item = e.target.closest('.item'); if (!item) return;
  if (state.project && !state.project.job) await saveProject().catch(() => {});
  await openProject(Number(item.dataset.id));
});
$('p-render').onclick = guard(() => render(false));
$('p-render-all').onclick = guard(() => render(true));
$('p-cancel').onclick = guard(async () => { if (state.project.job) await api(`/api/jobs/${state.project.job.id}/`, { method: 'DELETE' }); });
$('p-delete').onclick = guard(async () => {
  if (!confirm(`Delete "${state.project.title}" and its audio?`)) return;
  await api(`/api/projects/${state.project.id}/`, { method: 'DELETE' });
  await openProject(null);
});
$('p-script').oninput = countScript;
$('p-engine').onchange = $('p-language').onchange = () => fillEngineFields({ ...state.project, ...collectProject() });
$('p-title').onchange = guard(async () => { await saveProject(); loadProjects(); });
$('p-package').onclick = () => { setTask('package'); $('ai-input').value = $('p-script').value; show('write'); };
$('segments').onclick = guard(async (e) => {
  const btn = e.target.closest('button'); if (!btn) return;
  const row = btn.closest('.seg');
  if (btn.dataset.act === 'play') { new Audio(btn.dataset.src + '?t=' + Date.now()).play(); return; }
  const text = row.querySelector('.txt').textContent.trim();
  const out = await api(`/api/segments/${row.dataset.id}/`, { method: 'POST', body: { text } });
  state.project.job = out.job; renderOutput(); follow(out.job.id);
});

// ---------- voices ----------
const PROMPTS = [
  'Hi, and welcome back to the channel. Today I want to walk you through something I wish someone had explained to me years ago. It is simpler than it looks, and by the end of this video you will be able to do it yourself. So grab a coffee, get comfortable, and let us jump right in. First, a quick question: have you ever wondered why this works at all?',
  'Before we start, here is the plan. First we look at the problem, then we try the obvious fix and watch it fail, and finally we build the version that actually works. Along the way I will point out the mistakes almost everybody makes. Ready? Great. Number one is the big one, and it changes everything that follows.',
];
function renderVoices() {
  $('voice-list').innerHTML = state.voices.map((v) => {
    const q = v.quality || {};
    const cls = q.score >= 80 ? 'good' : q.score >= 55 ? 'warn' : 'bad';
    return `<div class="card" data-id="${v.id}">
      <div class="head"><span class="name">${esc(v.name)}</span>
        ${v.ready ? `<span class="badge ${cls}">quality ${q.score}/100</span>` : '<span class="badge">processing…</span>'}</div>
      <div class="small muted">${LANGS[v.language] || v.language}${q.duration ? ` · ${q.duration}s of speech · noise gap ${q.snr_db} dB` : ''}${v.is_default ? ' · default' : ''}</div>
      ${v.reference ? `<audio controls preload="none" src="${v.reference}"></audio>` : ''}
      <ul>${(q.tips || []).map((t) => `<li>${esc(t)}</li>`).join('')}</ul>
      <div class="row wrap">
        <button class="mini" data-act="test" ${v.ready ? '' : 'disabled'}>Test this voice</button>
        ${v.is_default ? '' : '<button class="mini" data-act="default">Make default</button>'}
        <button class="mini danger" data-act="delete">Delete</button></div>
    </div>`;
  }).join('') || '<p class="muted">No voices yet. Record or upload a sample above.</p>';
}
let recorder = null, recordedBlob = null, recTimer = null;
$('v-prompt').textContent = PROMPTS[Math.floor(Math.random() * PROMPTS.length)];
$('v-tabs').onclick = (e) => {
  const tab = e.target.dataset.tab; if (!tab) return;
  [...$('v-tabs').children].forEach((b) => b.classList.toggle('active', b === e.target));
  $('v-record').classList.toggle('hidden', tab !== 'record'); $('v-upload').classList.toggle('hidden', tab !== 'upload');
};
$('v-rec').onclick = guard(async () => {
  if (recorder) { recorder.stop(); return; }
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false, channelCount: 1 } });
  const chunks = []; const started = Date.now();
  recorder = new MediaRecorder(stream, { audioBitsPerSecond: 256000 });
  recorder.ondataavailable = (ev) => chunks.push(ev.data);
  recorder.onstop = () => {
    stream.getTracks().forEach((t) => t.stop()); clearInterval(recTimer);
    recordedBlob = new Blob(chunks, { type: recorder.mimeType }); recorder = null;
    $('v-rec').textContent = '● Record again';
    $('v-preview').src = URL.createObjectURL(recordedBlob); $('v-preview').classList.remove('hidden');
  };
  recorder.start();
  $('v-rec').textContent = '■ Stop';
  recTimer = setInterval(() => { $('v-timer').textContent = fmtTime((Date.now() - started) / 1000); }, 300);
});
$('v-save').onclick = guard(async () => {
  const recording = !$('v-record').classList.contains('hidden');
  const file = recording ? recordedBlob : $('v-file').files[0];
  if (!file) throw new Error(recording ? 'Record a sample first.' : 'Choose a file first.');
  const form = new FormData();
  form.append('audio', file, recording ? 'recording.webm' : file.name);
  form.append('name', $('v-name').value); form.append('language', $('v-language').value);
  form.append('consent', $('v-consent').checked);
  $('v-save').disabled = true; $('v-msg').textContent = 'Cleaning and analysing…';
  try {
    const out = await api('/api/voices/', { method: 'POST', form });
    await loadVoices();
    const job = await watch(out.job.id);
    $('v-msg').textContent = job.status === 'done' ? 'Voice saved.' : `Could not process: ${job.message}`;
    await loadVoices(); recordedBlob = null; $('v-preview').classList.add('hidden'); $('v-name').value = '';
  } finally { $('v-save').disabled = false; }
});
$('voice-list').onclick = guard(async (e) => {
  const btn = e.target.closest('button'); if (!btn) return;
  const id = Number(btn.closest('.card').dataset.id);
  const voice = state.voices.find((v) => v.id === id);
  if (btn.dataset.act === 'delete') {
    if (!confirm(`Delete the voice "${voice.name}"?`)) return;
    await api(`/api/voices/${id}/`, { method: 'DELETE' });
  } else if (btn.dataset.act === 'default') {
    await api(`/api/voices/${id}/`, { method: 'PATCH', body: { is_default: true } });
  } else if (btn.dataset.act === 'test') {
    const p = await api('/api/projects/', { method: 'POST', body: { title: `Voice test: ${voice.name}`, voice_id: id, language: voice.language,
      script: 'Hello! This is a quick test of my cloned voice. If this sounds like me, the sample is good, and I can start narrating full videos.' } });
    show('narrate'); await openProject(p.id); await render(false); return;
  }
  await loadVoices();
});

// ---------- write ----------
function setTask(id) {
  state.task = id;
  const task = state.status.tasks.find((t) => t.id === id);
  document.querySelectorAll('#ai-tasks button').forEach((b) => b.classList.toggle('active', b.dataset.task === id));
  $('ai-hint').textContent = task.hint;
  $('ai-minutes-wrap').classList.toggle('hidden', !['outline', 'script'].includes(id));
  $('ai-lang-wrap').classList.toggle('hidden', id !== 'translate');
}
$('ai-tasks').onclick = (e) => { if (e.target.dataset.task) setTask(e.target.dataset.task); };
let aiAbort = null;
$('ai-run').onclick = guard(async () => {
  aiAbort = new AbortController();
  $('ai-run').disabled = true; $('ai-stop').classList.remove('hidden'); $('ai-output').value = '';
  try {
    const resp = await fetch('/api/ai/', { method: 'POST', signal: aiAbort.signal,
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
      body: JSON.stringify({ task: state.task, text: $('ai-input').value, minutes: $('ai-minutes').value, language: $('ai-language').value }) });
    if (!resp.ok) throw new Error((await resp.json()).error);
    const reader = resp.body.getReader(); const dec = new TextDecoder();
    for (;;) {
      const { done, value } = await reader.read(); if (done) break;
      $('ai-output').value += dec.decode(value, { stream: true });
      $('ai-output').scrollTop = $('ai-output').scrollHeight;
    }
  } catch (e) { if (e.name !== 'AbortError') throw e; } finally {
    $('ai-run').disabled = false; $('ai-stop').classList.add('hidden');
  }
});
$('ai-stop').onclick = () => aiAbort && aiAbort.abort();
$('ai-copy').onclick = () => navigator.clipboard.writeText($('ai-output').value).then(() => toast('Copied'));
$('ai-reuse').onclick = () => { $('ai-input').value = $('ai-output').value; };
$('ai-narrate').onclick = guard(async () => {
  const script = $('ai-output').value.trim(); if (!script) throw new Error('Nothing to narrate yet.');
  const p = await api('/api/projects/', { method: 'POST', body: { title: script.split(/[.!?\n]/)[0].slice(0, 60), script } });
  show('narrate'); await openProject(p.id);
});

// ---------- transcribe ----------
async function loadTranscripts() {
  const rows = await api('/api/transcripts/');
  $('t-list').innerHTML = rows.map((t) => `<div class="item ${state.transcript && state.transcript.id === t.id ? 'active' : ''}" data-id="${t.id}">
    <div class="t">${esc(t.title)}</div><div class="s">${t.ready ? fmtTime(t.duration) + ' · ' + (LANGS[t.language] || t.language) : 'working…'}</div></div>`).join('');
}
async function openTranscript(id) {
  state.transcript = await api(`/api/transcripts/${id}/`);
  $('t-view').classList.remove('hidden'); $('t-title').textContent = state.transcript.title; $('t-text').value = state.transcript.text;
  loadTranscripts();
}
$('t-run').onclick = guard(async () => {
  const file = $('t-file').files[0]; if (!file) throw new Error('Choose a file first.');
  const form = new FormData(); form.append('file', file); form.append('language', $('t-language').value);
  $('t-run').disabled = true; $('t-msg').textContent = 'Uploading…';
  try {
    const out = await api('/api/transcripts/', { method: 'POST', form }); loadTranscripts();
    const job = await watch(out.job.id, (j) => { $('t-msg').textContent = `${j.message || 'Queued'} ${Math.round(j.progress * 100)}%`; });
    $('t-msg').textContent = job.status === 'done' ? '' : job.message;
    if (job.status === 'done') await openTranscript(out.transcript.id);
  } finally { $('t-run').disabled = false; }
});
$('t-list').onclick = guard(async (e) => { const it = e.target.closest('.item'); if (it) await openTranscript(Number(it.dataset.id)); });
$('t-copy').onclick = () => navigator.clipboard.writeText(state.transcript.text).then(() => toast('Copied'));
$('t-srt').onclick = () => download(state.transcript.title + '.srt', state.transcript.srt);
$('t-vtt').onclick = () => download(state.transcript.title + '.vtt', state.transcript.vtt);
$('t-package').onclick = () => { setTask('package'); $('ai-input').value = state.transcript.text; show('write'); };
$('t-delete').onclick = guard(async () => {
  if (!confirm('Delete this transcript?')) return;
  await api(`/api/transcripts/${state.transcript.id}/`, { method: 'DELETE' });
  state.transcript = null; $('t-view').classList.add('hidden'); loadTranscripts();
});

// ---------- clean ----------
$('c-run').onclick = guard(async () => {
  const file = $('c-file').files[0]; if (!file) throw new Error('Choose a recording first.');
  const form = new FormData(); form.append('file', file); form.append('denoise', $('c-denoise').value);
  $('c-run').disabled = true; $('c-msg').textContent = 'Working…';
  try {
    const out = await api('/api/clean/', { method: 'POST', form });
    const job = await watch(out.job.id);
    if (job.status !== 'done') throw new Error(job.message);
    const r = job.result;
    $('c-result').classList.remove('hidden'); $('c-audio').src = '/media/' + r.mp3;
    $('c-mp3').href = '/media/' + r.mp3; $('c-wav').href = '/media/' + r.wav;
    $('c-stats').textContent = `${fmtTime(r.duration)} · loudness ${r.lufs_before} → ${r.lufs} LUFS · peak ${r.true_peak} dBTP`;
    $('c-msg').textContent = '';
  } finally { $('c-run').disabled = false; }
});

// ---------- settings ----------
async function loadSettings() {
  const s = await api('/api/settings/');
  for (const k of ['name', 'niche', 'audience', 'tone']) $('ch-' + k).value = s.channel[k] || '';
  $('llm-provider').value = s.llm.provider;
  options($('llm-ollama-model'), s.llm_status.ollama_models.map((m) => [m, m]), s.llm.ollama_model);
  $('llm-ollama-gpu').checked = !!s.llm.ollama_gpu;
  $('llm-base').value = s.llm.base_url; $('llm-model').value = s.llm.model;
  $('llm-key').placeholder = s.llm.has_key ? 'saved (leave blank to keep)' : 'paste your API key';
  $('llm-msg').textContent = s.llm_status.ready ? `Ready: ${s.llm_status.model}` : s.llm_status.note;
  toggleProvider();
}
function toggleProvider() {
  const api_ = $('llm-provider').value === 'api';
  $('llm-api').classList.toggle('hidden', !api_); $('llm-ollama').classList.toggle('hidden', api_);
}
$('llm-provider').onchange = toggleProvider;
$('ch-save').onclick = guard(async () => {
  await api('/api/settings/', { method: 'POST', body: { channel: Object.fromEntries(['name', 'niche', 'audience', 'tone'].map((k) => [k, $('ch-' + k).value])) } });
  toast('Channel saved');
});
$('llm-save').onclick = guard(async () => {
  await api('/api/settings/', { method: 'POST', body: { llm: { provider: $('llm-provider').value, ollama_model: $('llm-ollama-model').value,
    ollama_gpu: $('llm-ollama-gpu').checked, base_url: $('llm-base').value, model: $('llm-model').value, api_key: $('llm-key').value } } });
  $('llm-key').value = ''; await loadSettings(); await loadStatus(); toast('Writing model saved');
});
async function loadPronunciations(rows) {
  rows = rows || await api('/api/pronunciations/');
  $('pr-list').innerHTML = rows.map((r) => `<div class="pr"><span><b>${esc(r.written)}</b> → ${esc(r.spoken)}</span>
    <button class="mini danger" data-id="${r.id}">Remove</button></div>`).join('');
}
$('pr-add').onclick = guard(async () => {
  loadPronunciations(await api('/api/pronunciations/', { method: 'POST', body: { written: $('pr-written').value, spoken: $('pr-spoken').value } }));
  $('pr-written').value = $('pr-spoken').value = '';
});
$('pr-list').onclick = guard(async (e) => {
  if (!e.target.dataset.id) return;
  await api(`/api/pronunciations/${e.target.dataset.id}/`, { method: 'DELETE' }); loadPronunciations();
});

// ---------- navigation ----------
$('nav').onclick = (e) => { if (e.target.dataset.view) show(e.target.dataset.view); };
document.addEventListener('click', (e) => { const g = e.target.closest('[data-goto]'); if (g) { e.preventDefault(); show(g.dataset.goto); } });
window.addEventListener('hashchange', () => { const v = location.hash.slice(1); if (document.getElementById('view-' + v)) show(v); });
window.addEventListener('beforeunload', () => { if (state.project && !state.project.job) navigator.sendBeacon && saveProject().catch(() => {}); });

(async function boot() {
  try {
    await loadStatus();
    const langs = Object.entries(LANGS);
    const cloneLangs = new Set(state.status.engines.filter((e) => e.clones).flatMap((e) => e.languages));
    options($('v-language'), langs.filter(([c]) => cloneLangs.has(c) || c === 'en'), 'en');
    options($('t-language'), [['', 'Detect automatically'], ...langs], '');
    await Promise.all([loadVoices(), loadProjects(), loadTranscripts(), loadSettings(), loadPronunciations()]);
    const view = location.hash.slice(1);
    if (document.getElementById('view-' + view)) show(view);
    if (state.projects.length) await openProject(state.projects[0].id);
  } catch (e) { toast(e.message, true); }
})();
