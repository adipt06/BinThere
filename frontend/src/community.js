import { startRecognitionProgress, readRecognitionResponse } from './recognition_feedback.js';
import { validCoordinate } from './state.js';

// Photos stay in browser/server memory; only classification and confirmed coordinates persist.
export function initializeCommunity({ apiBase, published }) {
  const $ = id => document.getElementById(id);
  let recognition = null, location = null, photoURL = null, photoController = null;
  let photoVersion = 0, locationVersion = 0, addressController = null, submitting = false, recognizing = false;
  const message = text => { $('community-status').textContent = text; };
  const photoMessage = text => { $('community-photo-status').textContent = text; message(text); };
  const update = () => { $('community-publish').disabled = submitting || !recognition || !location; };
  function selected(value) {
    location = value; $('community-public').checked = false;
    $('community-location').textContent = value ? `${value.name} (${value.coordinates[1].toFixed(5)}, ${value.coordinates[0].toFixed(5)}) — confirm this is the facility location.` : 'Choose the facility location using GPS or an address.';
    update();
  }
  async function request(path, options = {}, timeout = 15000) {
    const response = await fetch(apiBase + path, { credentials: 'include', ...options,
      signal: options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(timeout)]) : AbortSignal.timeout(timeout) });
    const data = await readRecognitionResponse(response);
    return data;
  }
  function resetPhoto() {
    photoVersion++; photoController?.abort(); recognition = null; recognizing = false;
    $('community-photo-status').textContent = '';
    $('community-recognize').disabled = false; $('community-cancel').hidden = true;
    $('community-recognition').textContent = '';
    if (photoURL) URL.revokeObjectURL(photoURL);
    photoURL = null; $('community-preview').hidden = true; $('community-preview').removeAttribute('src'); update();
  }
  $('community-file').onchange = () => {
    resetPhoto();
    const file = $('community-file').files[0];
    if (!file) return;
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || !file.size || file.size > 8 * 1024 * 1024) {
      $('community-file').value = ''; photoMessage('Choose a nonempty JPEG, PNG or WebP photo up to 8 MB. Convert HEIC photos first.');
      $('community-photo-status').scrollIntoView({ block: 'nearest' }); return;
    }
    photoURL = URL.createObjectURL(file); $('community-preview').src = photoURL; $('community-preview').hidden = false;
    message('Photo selected. Identify the facility before publishing.');
  };
  $('community-cancel').onclick = () => { resetPhoto(); photoMessage('Photo recognition cancelled.'); };
  $('community-photo-form').onsubmit = async event => {
    event.preventDefault(); const file = $('community-file').files[0]; if (!file || recognizing) return;
    recognizing = true;
    photoController?.abort(); photoController = new AbortController(); const version = ++photoVersion;
    recognition = null; update(); $('community-recognize').disabled = true; $('community-cancel').hidden = false;
    const stopProgress = startRecognitionProgress(photoMessage, () => version === photoVersion, 'Identifying the facility with Gemini');
    $('community-photo-status').scrollIntoView({ block: 'nearest' });
    try {
      const body = new FormData(); body.append('image', file);
      const data = await request('/community/recognize', { method: 'POST', body, signal: photoController.signal }, 270000);
      if (version !== photoVersion) return;
      if (!data.recognition || typeof data.recognition.description !== 'string') throw new Error('Invalid recognition response.');
      $('community-recognition').textContent = `${data.recognition.facility_type}: ${data.recognition.description}`;
      if (data.recognition_token) {
        recognition = data.recognition_token; $('community-name').value = data.recognition.suggested_name;
        photoMessage('Facility identified. Choose its location, then confirm it is public and publish.');
      } else photoMessage('The photo does not clearly show a supported facility. Try a clearer photo of the bin, restroom sign or recycling center.');
    } catch (error) {
      if (version === photoVersion) {
        photoMessage(error.name === 'TimeoutError' ? 'Recognition timed out. Your photo is kept; please retry.' : error.name === 'AbortError' ? 'Recognition cancelled.' : error.name === 'TypeError' ? 'Cannot reach the recognition service. Your photo is kept; check your connection and retry.' : error.message);
        if (!$('community-view').hidden) $('community-photo-status').scrollIntoView({ block: 'nearest' });
      }
    }
    finally { stopProgress(); if (version === photoVersion) { recognizing = false; $('community-recognize').disabled = false; $('community-cancel').hidden = true; update(); } }
  };
  $('community-gps').onclick = () => {
    const version = ++locationVersion; addressController?.abort(); $('community-address-results').replaceChildren(); selected(null);
    if (!navigator.geolocation) return message('GPS is unavailable. Search for the facility address instead.');
    message('Finding your current location…');
    navigator.geolocation.getCurrentPosition(position => {
      if (version !== locationVersion) return;
      const coordinates = [position.coords.longitude, position.coords.latitude];
      if (!validCoordinate(coordinates)) return message('GPS returned an invalid location. Use an address instead.');
      selected({ coordinates, name: `Current GPS location${Number.isFinite(position.coords.accuracy) ? ` (accuracy ±${Math.round(position.coords.accuracy)} m)` : ''}`, source: 'gps' });
      message('Check that you are standing at the facility before publishing.');
    }, () => { if (version === locationVersion) message('Could not get GPS. Allow location access or enter the facility address.'); }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
  };
  $('community-address').oninput = () => {
    locationVersion++; addressController?.abort(); selected(null); $('community-address-results').replaceChildren();
  };
  $('community-address-form').onsubmit = async event => {
    event.preventDefault(); const version = ++locationVersion; selected(null); $('community-address-results').replaceChildren();
    addressController?.abort(); addressController = new AbortController(); message('Looking up the facility address…');
    try {
      const data = await request(`/community/address-search?${new URLSearchParams({ q: $('community-address').value })}`, { signal: addressController.signal });
      if (version !== locationVersion) return;
      if (!Array.isArray(data.results) || data.results.some(r => !validCoordinate(r.coordinates) || typeof r.address_token !== 'string' || typeof r.name !== 'string')) throw new Error('Invalid address response.');
      for (const result of data.results) {
        const button = document.createElement('button'); button.type = 'button'; button.textContent = result.name;
        button.onclick = () => { if (version === locationVersion) { selected({ ...result, source: 'address' }); message('Address selected. Confirm that it is the facility location.'); } };
        $('community-address-results').append(button);
      }
      const attribution = document.createElement('p'); attribution.className = 'location-note'; attribution.textContent = data.attribution || '© Mapbox and its suppliers'; $('community-address-results').append(attribution);
      message(data.results.length ? 'Choose the matching address below.' : 'No matching address. Try a complete street address or GPS.');
    } catch (error) { if (version === locationVersion && error.name !== 'AbortError') message(error.message); }
  };
  $('community-publish-form').onsubmit = async event => {
    event.preventDefault(); if (!recognition || !location || submitting) return;
    const submittedLocation = location; submitting = true; update(); message('Publishing the community facility…');
    try {
      const result = await request('/community/facilities', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        recognition_token: recognition, name: $('community-name').value.trim(), latitude: location.coordinates[1], longitude: location.coordinates[0],
        location_source: location.source, address_token: location.address_token || null, public_access_confirmed: $('community-public').checked
      }) });
      recognition = null; resetPhoto(); $('community-file').value = ''; selected(null);
      await published(result.facility, submittedLocation);
      message('Published! The facility is labeled as a community submission. It will be hidden after the reporting threshold is reached.');
    } catch (error) { message(error.message); }
    finally { submitting = false; update(); }
  };
  update();
}

export function appendCommunityReport(container, facility, { apiBase, refreshed, removed }) {
  if (facility.source?.kind !== 'community') return;
  const form = document.createElement('form'); form.className = 'community-report';
  const label = document.createElement('label'); label.textContent = 'Report a problem';
  const select = document.createElement('select'); select.setAttribute('aria-label', 'Facility report reason');
  for (const [value, text] of [['not_here', 'Facility is not here'], ['fraudulent', 'Fraudulent listing'], ['not_public', 'Not publicly accessible']]) {
    const option = document.createElement('option'); option.value = value; option.textContent = text; select.append(option);
  }
  const button = document.createElement('button'); button.type = 'submit'; button.className = 'secondary-button'; button.textContent = 'Submit facility report';
  const status = document.createElement('p'); status.className = 'location-note'; status.setAttribute('role', 'status');
  status.textContent = `${facility.report_count || 0} reports. Hidden after ${facility.report_threshold || 3} distinct browser reports.`;
  label.append(select); form.append(label, button, status); container.append(form);
  form.onsubmit = async event => {
    event.preventDefault(); button.disabled = true;
    try {
      const response = await fetch(`${apiBase}/community/facilities/${encodeURIComponent(facility.id)}/reports`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason: select.value }), signal: AbortSignal.timeout(15000)
      });
      const data = await response.json(); if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Report failed. Please retry.');
      status.textContent = data.removed ? 'Facility removed from discovery after reaching the report threshold.' : `Report received (${data.report_count}/${data.report_threshold}).`;
      if (data.removed) removed(facility); await refreshed();
    } catch (error) { status.textContent = error.message; button.disabled = false; }
  };
}
