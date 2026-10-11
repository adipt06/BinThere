import { startRecognitionProgress, readRecognitionResponse } from './recognition_feedback.js';
import './ai_assistant.css';
import { RequestLane } from './state.js';
import { validateFile, imageDimensions, navigationAction, validateAnalysis, BIN_LABELS } from './ai_state.js';

export function initializeAssistant({ apiBase, navigate, selectView }) {
  const $ = id => document.getElementById(id);
  const lane = new RequestLane();
  let photo = null, previewURL = null, processing = false, loading = false, photoGeneration = 0;
  const status = (text, error = false) => {
    $('ai-status').textContent = text; $('ai-status').classList.toggle('ai-error', error);
    if (error && !$('ai-view').hidden) $('ai-status').scrollIntoView({ block: 'nearest' });
  };
  function setLoading(value) {
    loading = value; $('ai-submit').disabled = value || processing;
    $('ai-submit').textContent = value ? 'Analyzing…' : 'Analyze waste';
    $('ai-form').setAttribute('aria-busy', String(value)); $('ai-cancel').hidden = !value;
  }
  function invalidate(message = '') { lane.cancel(); setLoading(false); $('ai-results').hidden = true; status(message); }
  const selectTab = ai => selectView(ai ? 'ai' : 'navigation');
  function removePhoto() {
    photoGeneration++; processing = false; invalidate(); photo = null;
    if (previewURL) URL.revokeObjectURL(previewURL); previewURL = null;
    $('ai-preview').removeAttribute('src'); $('ai-preview').hidden = true; $('ai-file').value = ''; $('ai-remove').hidden = true;
    $('ai-photo-label').textContent = 'Choose, drop or paste a photo';
  }
  async function loadPhoto(file) {
    removePhoto(); const generation = photoGeneration;
    try {
      validateFile(file); processing = true; $('ai-submit').disabled = true; status('Preparing photo…');
      const url = URL.createObjectURL(file);
      let image;
      try { image = await new Promise((resolve, reject) => {
        const img = new Image();
        const timeout = setTimeout(() => { img.onload = img.onerror = null; img.src = ''; reject(new Error('Photo preparation timed out. Try a smaller JPEG, PNG or WebP.')); }, 15000);
        img.onload = () => { clearTimeout(timeout); resolve(img); };
        img.onerror = () => { clearTimeout(timeout); reject(new Error('Cannot decode this image. Choose an intact JPEG, PNG or WebP.')); };
        img.src = url;
      }); }
      finally { URL.revokeObjectURL(url); }
      if (generation !== photoGeneration) return;
      const [width, height] = imageDimensions(image.naturalWidth, image.naturalHeight);
      const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height;
      const ctx = canvas.getContext('2d'); if (!ctx) throw new Error('Image processing is unavailable in this browser.');
      ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, width, height); ctx.drawImage(image, 0, 0, width, height);
      const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.8));
      if (generation !== photoGeneration) return;
      if (!blob) throw new Error('Could not prepare this image. Try another photo.');
      photo = new File([blob], 'waste-photo.jpg', { type: 'image/jpeg' });
      previewURL = URL.createObjectURL(photo); $('ai-preview').src = previewURL; $('ai-preview').hidden = false; $('ai-remove').hidden = false;
      $('ai-photo-label').textContent = 'Photo ready. Choose another to replace it.'; status('Photo ready. Add an optional question or analyze now.');
    } catch (error) { if (generation === photoGeneration) status(error.message, true); }
    finally { if (generation === photoGeneration) { processing = false; setLoading(false); } }
  }
  $('ai-file').onchange = () => { if ($('ai-file').files[0]) loadPhoto($('ai-file').files[0]); };
  $('ai-remove').onclick = removePhoto; $('ai-drop').onclick = () => $('ai-file').click();
  $('ai-drop').onkeydown = e => { if (['Enter', ' '].includes(e.key)) { e.preventDefault(); $('ai-file').click(); } };
  for (const type of ['dragenter', 'dragover', 'dragleave', 'drop']) $('ai-drop').addEventListener(type, e => {
    e.preventDefault(); $('ai-drop').classList.toggle('ai-dragging', type === 'dragenter' || type === 'dragover');
    if (type === 'drop' && e.dataTransfer?.files[0]) loadPhoto(e.dataTransfer.files[0]);
  });
  window.addEventListener('paste', e => {
    if ($('ai-view').hidden) return;
    const item = [...(e.clipboardData?.items || [])].find(i => i.type.startsWith('image/'));
    if (item) { e.preventDefault(); loadPhoto(item.getAsFile()); }
  });
  $('ai-question').oninput = $('ai-place').oninput = () => invalidate(loading ? 'Analysis cancelled because the inputs changed. Select Analyze waste again when ready.' : '');
  $('ai-question').onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('ai-form').requestSubmit(); } };
  $('ai-cancel').onclick = () => { invalidate(); status('Analysis canceled.'); };
  const node = (tag, text, cls) => { const n = document.createElement(tag); n.textContent = text; if (cls) n.className = cls; return n; };
  function render(data) {
    $('ai-items').replaceChildren(); $('ai-answer').textContent = data.answer || ''; $('ai-answer').hidden = !data.answer;
    $('ai-summary').textContent = data.summary;
    $('ai-unsure').textContent = data.unsure || (!data.items.length && !data.answer ? 'No recognizable items. Try a clearer photo or ask a question.' : '');
    $('ai-unsure').hidden = !$('ai-unsure').textContent;
    for (const item of data.items) {
      const card = node('article', '', `ai-item ai-${item.bin}`);
      card.append(node('span', BIN_LABELS[item.bin], 'ai-bin'), node('h3', item.name), node('p', item.material, 'location-note'));
      const steps = document.createElement('ol'); item.steps.forEach(step => steps.append(node('li', step))); card.append(steps);
      if (item.tip) card.append(node('p', item.tip, 'location-note'));
      const type = navigationAction(item);
      if (type) {
        const button = node('button', type === 'Trash Bin' ? 'Find trash bins' : item.bin === 'recycling' ? 'Find recycling locations' : 'Find nearby recycling centers', 'secondary-button'); button.type = 'button';
        button.onclick = () => { selectTab(false); navigate(type, item); }; card.append(button);
        if (type === 'Recycling Location') card.append(node('p', `Acceptance is unverified. Contact the operator to confirm this material is accepted before bringing it.${/batter(?:y|ies)|lithium/i.test(`${item.name} ${item.material}`) ? ' Batteries must not go in ordinary recycling or trash bins.' : ''}`, 'location-note'));
      } else card.append(node('p', 'BinThere does not currently have a verified appropriate disposal location for this category or item. Check municipal or specialist collection guidance.', 'location-note'));
      $('ai-items').append(card);
    }
    $('ai-results').hidden = false;
  }
  $('ai-form').onsubmit = async event => {
    event.preventDefault(); if (loading || processing) return;
    const question = $('ai-question').value.trim(), place = $('ai-place').value.trim();
    if (!photo && !question) { status('Add a photo, a question, or both.', true); $('ai-question').focus(); return; }
    const ticket = lane.begin(); setLoading(true); $('ai-results').hidden = true;
    const stopProgress = startRecognitionProgress(text => status(text), ticket.current, 'Analyzing with Gemini');
    $('ai-status').scrollIntoView({ block: 'nearest' });
    const body = new FormData(); body.append('question', question); body.append('place', place); if (photo) body.append('image', photo);
    try {
      // Allow model lookup, a 100-second analysis and one bounded malformed-output retry.
      const response = await fetch(`${apiBase}/ai/analyze`, { method: 'POST', body, signal: AbortSignal.any([ticket.signal, AbortSignal.timeout(270000)]) });
      const data = await readRecognitionResponse(response);
      if (!ticket.current()) return;
      render(validateAnalysis(data)); status('Analysis complete. General guidance; confirm local disposal rules.');
      if (!$('ai-view').hidden) $('ai-results').scrollIntoView({ block: 'start' });
    } catch (error) {
      if (ticket.current()) status(error.name === 'TimeoutError' ? 'Analysis timed out. Please retry.' : error.name === 'TypeError' ? 'Cannot reach the AI service. Check your connection and backend.' : error.message, true);
    } finally { stopProgress(); if (ticket.current()) setLoading(false); }
  };
}
