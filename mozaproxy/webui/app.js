'use strict';

const routes = [
  ['overview', 'Overview', '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>'],
  ['wheelbase', 'Wheelbase', '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3"/><path d="m3.5 9.5 6 2m11-2-6 2M12 15v6"/>'],
  ['controls', 'Pedals & controls', '<path d="m4 20 2-16h5L9 20Zm10 0 2-16h5l-2 16ZM6 8h4m-5 4h4m8-4h3m-4 4h3"/>'],
  ['profiles', 'Profiles', '<path d="M4 7h16v14H4ZM7 3h10v4M8 11h8m-8 4h5"/>'],
  ['games', 'Games', '<path d="M7 7h10c2 0 3 2 4 6l1 4c.5 3-2 4-4 2l-3-3H9l-3 3c-2 2-4.5 1-4-2l1-4c1-4 2-6 4-6Z"/><path d="M7 10v5m-2.5-2.5h5M16 11h.1M18 14h.1"/>'],
  ['diagnostics', 'Diagnostics', '<path d="M3 12h4l3-8 4 16 3-8h4"/>'],
];
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const own = (obj, key) => Object.prototype.hasOwnProperty.call(obj || {}, key);
const clamp = value => Math.max(0, Math.min(1, Number(value) || 0));
let state = null;
let schema = {groups: [], settings: []};
let schemaError = '';
let token = '';
let online = false;
let route = location.hash.slice(1) || 'overview';
let draft = {};
let applyErrors = {};
let invalidSettings = {};
let busy = false;
let toastTimer;
let pollTimer;
let polling = false;
let stateGeneration = 0;
let structuralKey = '';
let profileName = '';
let profileGame = '';
let deletingProfile = null;
let editingProfile = null;
let relayChoice = 'native';

$('#navigation').innerHTML = routes.map(([id,label,path]) => `<a class="nav-link" href="#${id}" data-route="${id}"><svg viewBox="0 0 24 24" aria-hidden="true">${path}</svg><span>${label}</span></a>`).join('');

function notify(message, error = false) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.classList.toggle('error', error);
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, error ? 9000 : 5000);
}
async function api(path, method = 'GET', body) {
  if (method !== 'GET' && !token) {
    const session = await api('/api/session');
    token = session.token;
  }
  const options = {method, headers: {}, cache: 'no-store'};
  if (method !== 'GET') {
    options.headers['X-Mozaproxy-Token'] = token;
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body ?? {});
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20000);
  options.signal = controller.signal;
  let response;
  try { response = await fetch(path, options); }
  catch (error) { throw new Error(error.name === 'AbortError' ? 'The local app took too long to respond. Try again.' : 'Cannot reach the local app. Check that mozaproxy app is running.'); }
  finally { clearTimeout(timeout); }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 403) token = '';
    throw new Error(data.error || `The request failed (${response.status}). Try again.`);
  }
  return data;
}
function setOnline(value, message = '') {
  online = value;
  document.body.classList.toggle('offline', !value);
  $('#app-connection').textContent = value ? 'Local app connected' : 'Local app offline';
  $('#app-dot').classList.toggle('good', value);
  $('#connection-error').hidden = value;
  if (!value) $('#connection-error').innerHTML = `${escapeHTML(message || 'Waiting for the local app.')} <button type="button" class="button small" data-action="retry">Retry connection</button>`;
}
function signature() {
  if (!state) return '';
  return JSON.stringify({connected:state.device?.connected, axes:(state.device?.axes || []).map(a=>[a.code,a.label]), buttons:(state.device?.buttons || []).map(b=>b.code), hardware:[state.hardware?.connected,state.hardware?.port,state.hardware?.conflict,state.hardware?.error], relay:[state.relay?.running,state.relay?.profile], profiles:state.profiles, active:state.active_profile, games:state.games, diagnostics:state.diagnostics?.items});
}
async function poll() {
  if (polling) return;
  if (busy) {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(poll, 200);
    return;
  }
  const generation = stateGeneration;
  polling = true;
  try {
    const next = await api('/api/state');
    if (generation !== stateGeneration || busy) return;
    state = next;
    const wasOnline = online;
    setOnline(true);
    const key = signature();
    if (!structuralKey || key !== structuralKey || !wasOnline) {
      // Avoid removing a control beneath the pointer or keyboard during editing.
      if (!$('#content').contains(document.activeElement) || !document.activeElement.matches('input,select,button')) { structuralKey = key; render(); }
    }
    updateLive();
    updateControls();
  } catch (error) {
    if (generation === stateGeneration && !busy) { setOnline(false, error.message); updateLive(); updateControls(); }
  }
  finally {
    polling = false;
    clearTimeout(pollTimer);
    pollTimer = setTimeout(poll, document.hidden ? 2500 : 200);
  }
}
function heading(title, description, actions = '') {
  return `<div class="page-heading"><div><h1>${title}</h1><p class="page-description">${description}</p></div>${actions ? `<div class="heading-actions">${actions}</div>` : ''}</div>`;
}
function badge(text, kind = '') { return `<span class="badge ${kind}">${escapeHTML(text)}</span>`; }
function statusKind(status) {
  const value = String(status || '').toLowerCase();
  if (/incorrect|error|fail|conflict|missing/.test(value)) return 'bad';
  if (/experimental|pending|untested|warn|unresolved|partial/.test(value)) return 'warning';
  if (/confirmed|ready|connected|ok|pass|available|running/.test(value)) return 'good';
  return '';
}
function deviceAxes() { return state?.device?.axes || []; }
function steeringAxis() { return deviceAxes().find(a => /steer|wheel|ABS_X$/i.test(a.label || '') || a.code === 0 || a.code === 'ABS_X') || deviceAxes()[0]; }
function pedalAxis(type) {
  const patterns = {throttle:/^throttle$|accelerat|gas|ABS_Z$/i, brake:/brake|ABS_RZ$/i, clutch:/clutch|ABS_THROTTLE$/i};
  return deviceAxes().find(a => patterns[type].test(a.label || '') || patterns[type].test(String(a.code)));
}
function pedalDisplay() {
  return `<div class="pedals">${['throttle','brake','clutch'].map(type => `<div class="pedal-channel"><div class="pedal-meter" data-pedal-meter="${type}" role="meter" aria-label="${type} travel" aria-valuemin="0" aria-valuemax="100" aria-valuetext="No reading"><div class="pedal-fill" data-pedal-fill="${type}"></div></div><img src="/pedal.svg" class="pedal-art" alt="" width="56" height="106"><span class="pedal-name">${type[0].toUpperCase()+type.slice(1)}</span><span class="pedal-value" data-pedal-value="${type}" data-live>—</span></div>`).join('')}</div>`;
}
function renderOverview() {
  const hardware = state.hardware || {};
  const active = (state.profiles || []).find(p=>p.id===state.active_profile);
  return heading('Overview', 'Your wheel, inputs and driving setup.', `<a class="button" href="#wheelbase">Tune wheelbase <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><path d="M3 13 13 3M4 3h9v9"/></svg></a>`) +
    `<div class="overview-bench"><section class="steering-panel" aria-labelledby="steering-title"><div class="section-title"><h2 id="steering-title">Steering</h2><span class="section-note" id="steering-range">Range not read</span></div><div class="steering-stage unavailable" id="steering-stage"><span class="dial-mark dial-left">LEFT</span><span class="dial-mark dial-center">CENTER</span><span class="dial-mark dial-right">RIGHT</span><img src="/wheel.svg" alt="Steering wheel position" class="wheel-face" id="wheel-face" width="280" height="280"></div><div class="steering-measure"><span class="measurement" id="steering-value" data-live>—</span><span class="measurement-unit" id="steering-unit">position</span></div><p class="steering-hint" id="steering-hint">Waiting for wheel input</p></section><section class="pedal-panel" aria-labelledby="pedal-title"><div class="section-title"><h2 id="pedal-title">Pedal travel</h2><a href="#controls" class="section-link">All inputs</a></div>${pedalDisplay()}</section><div class="bench-footer"><span><span class="status-dot" id="input-dot"></span><span id="input-status">Waiting for device</span></span><span>Input monitor · no motor output</span></div></div>
    <div class="overview-lower"><section><div class="section-heading"><h2>Device connection</h2><a class="section-link" href="#diagnostics">Diagnostics</a></div><dl class="detail-list"><div><dt>Input device</dt><dd id="overview-device">${escapeHTML(state.device?.name || 'Not detected')}</dd></div><div><dt>Hardware settings</dt><dd>${badge(hardware.connected ? 'Connected' : 'Not connected',hardware.connected?'good':'')}</dd></div><div><dt>Force feedback</dt><dd>${escapeHTML((state.device?.effects || []).length ? `${state.device.effects.length} FFB capabilities` : 'No capabilities read')}</dd></div><div><dt>Selected profile</dt><dd>${escapeHTML(active?.name || 'None selected')}</dd></div></dl><p class="inline-note">Read hardware settings before tuning. Selecting a profile prepares values; Apply writes them to the device.</p></section><section><div class="section-heading"><h2>Game relay</h2>${badge(state.relay?.running?'Running':'Stopped',state.relay?.running?'good':'')}</div><p class="inline-note">Both options create a virtual input device. Keep the relay stopped for direct Assetto Corsa and ACC use.</p>${relayForm()}<p class="inline-note">Check <a href="#games">game compatibility</a> before choosing a route.</p></section></div>`;
}
function relayForm() {
  const running = state.relay?.running;
  const selectedProfile = running ? state.relay.profile : relayChoice;
  return `<div class="relay-form"><div class="form-field"><label for="relay-profile">Relay device</label><select id="relay-profile" ${running?'disabled':''}><option value="native" ${selectedProfile==='native'?'selected':''}>Full input mapping</option><option value="compact" ${selectedProfile==='compact'?'selected':''}>Compact R9 compatibility</option></select></div><button class="button ${running?'':'primary'}" data-action="${running?'relay-stop':'relay-start'}" data-mutation>${running?'Stop relay':'Start relay'}</button></div>`;
}
function hardwareToolbar() {
  const h = state.hardware || {};
  return `${h.conflict ? `<div class="alert error" role="alert"><strong>Another app owns the device.</strong><p>${escapeHTML(typeof h.conflict==='string'?h.conflict:'Close Boxflat or the other settings app before connecting.')}</p></div>` : ''}${h.error ? `<div class="alert error" role="alert">${escapeHTML(h.error)}</div>` : ''}<div class="hardware-toolbar"><div><strong>${h.connected?'Hardware settings connected':'Connect to read device settings'}</strong><div class="hardware-detail">${escapeHTML(h.connected ? h.port || 'Serial connection active' : 'Input monitoring works independently of this connection.')}</div></div><div class="toolbar-actions"><button class="button ${h.connected?'':'primary'}" data-action="hardware-connect" data-mutation>${h.connected?'Read device settings':'Connect hardware'}</button>${h.connected?'<button class="button" data-action="hardware-disconnect" data-mutation>Disconnect</button>':''}</div></div>`;
}
function settingValue(setting) {
  return own(draft,setting.id) ? draft[setting.id] : (state.hardware?.values || {})[setting.id];
}
function humanValue(setting, value) {
  if (value === undefined || value === null) return 'Not read';
  const choice = (setting.choices || []).find(c=>String(c.value)===String(value));
  if (choice) return choice.label;
  if (setting.type === 'boolean') return value ? 'On' : 'Off';
  return `${value}${setting.unit ? ` ${setting.unit}` : ''}`;
}
function settingRow(s) {
  const id = escapeHTML(s.id), value = settingValue(s), confirmed = (state.hardware?.values || {})[s.id];
  const pending = own(draft,s.id);
  let control;
  if (s.type === 'select' || s.type === 'boolean' || s.choices?.length) {
    const choices = s.type==='boolean' && !s.choices?.length ? [{value:false,label:'Off'},{value:true,label:'On'}] : s.choices || [];
    control = `<select id="setting-${id}" data-setting="${id}" aria-describedby="description-${id} confirmed-${id}"><option value="" ${value===undefined?'selected':''} disabled>Choose a value</option>${choices.map(c=>`<option value="${escapeHTML(JSON.stringify(c.value))}" ${JSON.stringify(c.value)===JSON.stringify(value)?'selected':''}>${escapeHTML(c.label)}</option>`).join('')}</select>`;
  } else {
    const min = Number.isFinite(s.min)?s.min:0, max=Number.isFinite(s.max)?s.max:100, step=s.step || 1;
    control = `<input type="range" min="${min}" max="${max}" step="${step}" value="${value ?? min}" data-setting="${id}" data-range="${id}" aria-label="${escapeHTML(s.label)}" aria-describedby="description-${id} confirmed-${id}" ${value===undefined?'aria-valuetext="Not read; adjust to prepare a value"':''}><div class="number-unit"><input type="number" id="setting-${id}" data-setting="${id}" data-number="${id}" min="${min}" max="${max}" step="${step}" value="${escapeHTML(own(invalidSettings,s.id)?invalidSettings[s.id].value:value ?? '')}" placeholder="—" aria-label="${escapeHTML(s.label)} ${escapeHTML(s.unit || '')}" aria-describedby="description-${id} confirmed-${id}">${s.unit ? `<span>${escapeHTML(s.unit)}</span>` : ''}</div>`;
  }
  return `<div class="setting-row"><div><label class="setting-name" for="setting-${id}">${escapeHTML(s.label)}<span class="pending-chip" data-pending="${id}" ${pending?'':'hidden'}>Draft</span></label><p class="setting-description" id="description-${id}">${escapeHTML(s.description || '')}</p></div><div class="setting-controls">${control}<div class="setting-confirmed ${applyErrors[s.id]?'error':''}" id="confirmed-${id}" data-confirmed="${id}">${applyErrors[s.id]?escapeHTML(applyErrors[s.id]):`On device: ${escapeHTML(humanValue(s,confirmed))}`}</div></div></div>`;
}
function settingsGroups(forControls) {
  const settings = schema.settings.filter(s => /pedal|wheel$|rim|handbrake|shifter/.test(s.group || '') === forControls);
  if (schemaError) return `<div class="alert error">${escapeHTML(schemaError)} <button class="button small" data-action="retry-schema">Reload settings</button></div>`;
  if (!settings.length) return '<div class="empty-state"><h2>No settings available</h2><p>This device does not expose settings for this section. Live input monitoring is still available.</p></div>';
  const groupIds = [...new Set(settings.map(s=>s.group))];
  return groupIds.map(id => `<section class="setting-group"><div class="section-heading"><h2>${escapeHTML(schema.groups.find(g=>g.id===id)?.label || id || 'Device settings')}</h2><span class="section-note">Confirmed values shown below each control</span></div>${settings.filter(s=>s.group===id).map(settingRow).join('')}</section>`).join('');
}
function applyBar() {
  return `<div class="apply-bar"><div><p id="draft-count">${Object.keys(draft).length?`${Object.keys(draft).length} unapplied setting${Object.keys(draft).length===1?'':'s'}`:'No unapplied changes'}</p><p class="muted" id="apply-hint">${state.hardware?.connected?'Apply writes to your connected device.':'Connect hardware to apply. You can still save a profile.'}</p></div><div class="toolbar-actions"><button class="button quiet" data-action="discard" id="discard-draft">Discard</button><a class="button" href="#profiles">Save profile</a><button class="button primary" data-action="apply" id="apply-draft" data-mutation>Apply to device</button></div></div>`;
}
function renderWheelbase() {
  return heading('Wheelbase', 'Tune steering and force feedback. Changes stay in draft until you apply.') + hardwareToolbar() + settingsGroups(false) + applyBar();
}
function renderControls() {
  return heading('Pedals & controls', 'Watch every input and configure supported controls.') + `<section class="plain-section"><div class="section-heading"><h2>Live axes</h2><span class="section-note">Raw device input</span></div>${deviceAxes().length ? `<table class="input-table"><thead><tr><th scope="col">Axis</th><th scope="col">Position</th><th scope="col">Raw value</th><th scope="col">Range</th></tr></thead><tbody>${deviceAxes().map(a=>`<tr><td>${escapeHTML(a.label || a.code)}</td><td><div class="axis-bar" role="meter" aria-label="${escapeHTML(a.label || a.code)}" aria-valuemin="0" aria-valuemax="100" data-axis-meter="${escapeHTML(a.code)}"><span data-axis-bar="${escapeHTML(a.code)}"></span></div></td><td data-axis-raw="${escapeHTML(a.code)}">—</td><td>${escapeHTML(a.min)}…${escapeHTML(a.max)}</td></tr>`).join('')}</tbody></table>` : '<div class="empty-state"><p>No axes detected. Connect the wheel and check input permissions in Diagnostics.</p></div>'}</section><section class="plain-section"><div class="section-heading"><h2>Buttons & paddles</h2><span class="section-note">Press a control to identify it</span></div><div class="button-grid">${(state.device?.buttons || []).map(b=>`<span class="input-button" data-input-button="${escapeHTML(b.code)}" title="${escapeHTML(b.label)}" aria-label="${escapeHTML(b.label)}: released">${escapeHTML(b.label || b.code)}</span>`).join('') || '<p class="muted">No buttons reported by the device.</p>'}</div></section>` + hardwareToolbar() + settingsGroups(true) + applyBar();
}
function profileSettings() {
  const base=editingProfile ? state.profiles.find(p=>p.id===editingProfile)?.settings || {} : state.hardware?.values || {};
  return {...base,...draft};
}
function renderProfiles() {
  const profiles = state.profiles || [];
  const settings = profileSettings();
  return heading('Profiles', 'Save a setup, then load its values into draft when you need them.') + `<div class="profiles-layout"><section><div class="section-heading"><h2>Saved setups</h2><span class="section-note">${profiles.length} saved</span></div>${profiles.map(p=>`<article class="profile-row"><div class="profile-row-heading"><h3>${escapeHTML(p.name)}</h3>${p.id===state.active_profile?badge('Selected','good'):''}</div><p class="profile-meta">${escapeHTML((state.games || []).find(g=>g.id===p.game_id)?.name || 'Any game')} · ${Object.keys(p.settings || {}).length} settings</p><div class="profile-actions"><button class="button small" data-action="profile-load" data-id="${escapeHTML(p.id)}" data-mutation>Load into draft</button><button class="button small quiet" data-action="profile-edit" data-id="${escapeHTML(p.id)}">Edit</button><button class="button small quiet danger" data-action="profile-delete-request" data-id="${escapeHTML(p.id)}">Delete</button></div>${deletingProfile===p.id?`<div class="delete-confirm"><span>Delete this saved profile?</span><button class="button small danger" data-action="profile-delete" data-id="${escapeHTML(p.id)}" data-mutation>Delete profile</button><button class="button small quiet" data-action="delete-cancel">Cancel</button></div>`:''}</article>`).join('') || '<div class="empty-state"><h2>Your first setup starts here</h2><p>Read the device settings or adjust values in Wheelbase, then give the setup a name and save it.</p><a class="button" href="#wheelbase">Open wheelbase settings</a></div>'}</section><section><div class="section-heading"><h2>${editingProfile?'Edit profile':'Save current setup'}</h2>${editingProfile?'<button class="button small quiet" data-action="profile-new">New profile</button>':''}</div>${Object.keys(invalidSettings).length?'<div class="alert error" role="alert">Correct the invalid values in <a href="#wheelbase">Wheelbase</a> or <a href="#controls">Pedals &amp; controls</a> before saving.</div>':''}<form id="profile-form"><div class="form-field"><label for="profile-name">Profile name</label><input type="text" id="profile-name" name="name" maxlength="80" placeholder="e.g. FH5 · road cars" value="${escapeHTML(profileName)}" required></div><div class="form-field"><label for="profile-game">Game</label><select id="profile-game"><option value="">Any game</option>${(state.games || []).map(g=>`<option value="${escapeHTML(g.id)}" ${profileGame===g.id?'selected':''}>${escapeHTML(g.name)}</option>`).join('')}</select></div><div class="draft-summary"><p>${Object.keys(settings).length} settings will be saved.</p><p class="muted">${editingProfile?'Includes this profile’s values plus your draft changes.':'Includes confirmed device values plus your draft changes.'} Saving does not write to hardware.</p>${Object.keys(settings).length?`<details class="profile-value-details"><summary>Review values</summary><dl class="draft-list">${Object.entries(settings).map(([id,value])=>{const s=schema.settings.find(s=>s.id===id);return `<dt>${escapeHTML(s?.label || id)}${own(draft,id)?' · draft':''}</dt><dd>${escapeHTML(s?humanValue(s,value):value)}</dd>`;}).join('')}</dl></details>`:''}</div><button class="button primary" type="submit" data-mutation ${!Object.keys(settings).length?'disabled data-empty="true"':''}>${editingProfile?'Update profile':'Save profile'}</button></form></section></div>`;
}
function renderGames() {
  return heading('Games', 'The tested routes, known issues and launch options for your library.') + `<div class="alert">Only FH5 has confirmed in-game force feedback. Compatibility notes describe observed behavior, not a guarantee.</div><section>${(state.games || []).map(g=>`<article class="game-row"><div class="game-monogram" aria-hidden="true">${escapeHTML(g.abbr || g.name.slice(0,3))}</div><div><div class="game-name"><h2>${escapeHTML(g.name)}</h2>${badge(g.status,statusKind(g.status))}</div><p class="game-detail">${escapeHTML(g.detail)}</p><div class="game-statuses"><span>Input: ${escapeHTML(g.input_status || 'Not tested')}</span><span>FFB: ${escapeHTML(g.ffb_status || 'Not tested')}</span></div></div><div class="game-launch">${g.launch_options?`<div class="launch-label">Steam launch options</div><code class="launch-options">${escapeHTML(g.launch_options)}</code><button class="button small" data-action="copy-launch" data-id="${escapeHTML(g.id)}">Copy launch options</button>`:'<p class="game-detail">No launch override configured.</p>'}</div></article>`).join('') || '<div class="empty-state"><h2>No game routes available</h2><p>Reconnect to the local app to load compatibility notes.</p></div>'}</section><p class="inline-note">Launch options are copied as text. Start and stop the relay separately in <a href="#overview">Overview</a>.</p>`;
}
function renderDiagnostics() {
  return heading('Diagnostics', 'Connection checks and relay output from this session.', '<a class="button" href="/api/diagnostics/export" download="mozaproxy-diagnostics.json">Export report</a>') + `<section class="plain-section"><div class="section-heading"><h2>System checks</h2><span class="section-note">Current app state</span></div>${(state.diagnostics?.items || []).map(item=>`<div class="diagnostic-row"><strong>${escapeHTML(item.label)}</strong><div>${badge(item.status,statusKind(item.status))}</div><p>${escapeHTML(item.detail)}</p></div>`).join('') || '<div class="empty-state"><p>The local app has not reported diagnostics yet.</p></div>'}</section><section class="plain-section"><div class="section-heading"><h2>Device details</h2></div><dl class="detail-list"><div><dt>Input path</dt><dd>${escapeHTML(state.device?.path || 'Not detected')}</dd></div><div><dt>Settings port</dt><dd>${escapeHTML(state.hardware?.port || 'Not connected')}</dd></div><div><dt>FFB effect slots</dt><dd>${escapeHTML(state.device?.slots ?? 'Not read')}</dd></div><div><dt>Supported effects</dt><dd>${escapeHTML((state.device?.effects || []).join(', ') || 'Not read')}</dd></div><div><dt>Relay process</dt><dd>${escapeHTML(state.relay?.running ? `PID ${state.relay.pid} · ${state.relay.profile}` : 'Stopped')}</dd></div></dl></section><section><div class="section-heading"><h2>Relay log</h2><span class="section-note">Recent output</span></div><pre class="log-view" id="relay-log" tabindex="0">${escapeHTML((state.relay?.log || []).join('\n') || 'No relay output yet. Start a relay from Overview when your game requires it.')}</pre><p class="inline-note">The export contains device, settings and recent relay diagnostics. It excludes environment variables and secrets.</p></section>`;
}
function render() {
  if (!routes.some(r=>r[0]===route)) route='overview';
  $$('[data-route]').forEach(el=>{if(el.dataset.route===route)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
  document.title = `${routes.find(r=>r[0]===route)[1]} · Mozaproxy`;
  if (!state) return;
  const renderers = {overview:renderOverview,wheelbase:renderWheelbase,controls:renderControls,profiles:renderProfiles,games:renderGames,diagnostics:renderDiagnostics};
  $('#content').innerHTML=renderers[route]();
  updateLive();
  updateControls();
}
function updateLive() {
  if (!state) return;
  const device=state.device || {}, h=state.hardware || {}, available=online && device.connected;
  $('#device-title').textContent=device.name || 'No wheel detected';
  $('#device-connection').textContent=available?'Input connected':online?'Disconnected':'Offline';
  $('#device-connection').className=`badge ${available?'good':''}`;
  $('#relay-status').textContent=state.relay?.running?`Relay running · ${state.relay.profile}`:'Relay stopped';
  $('#last-update').textContent=online?'State updated just now':'Connection interrupted';
  const axis=steeringAxis();
  if ($('#wheel-face')) {
    const hasReading=available && axis && Number.isFinite(axis.value);
    const normalized=hasReading ? clamp(axis.value)*2-1 : null;
    const rotation=Number(h.values?.rotation);
    const angle=normalized===null?null:normalized*(Number.isFinite(rotation)&&rotation>0?rotation/2:90);
    $('#steering-stage').classList.toggle('unavailable',!hasReading);
    $('#wheel-face').style.setProperty('--rotation',`${angle || 0}deg`);
    $('#steering-value').textContent=normalized===null?'—':Number.isFinite(rotation)&&rotation>0?`${angle>=0?'+':''}${angle.toFixed(1)}°`:`${normalized>=0?'+':''}${(normalized*100).toFixed(1)}%`;
    $('#steering-unit').textContent=Number.isFinite(rotation)&&rotation>0?'from center':'from center';
    $('#steering-range').textContent=Number.isFinite(rotation)&&rotation>0?`${rotation}° range`:'Range not read';
    $('#steering-hint').textContent=hasReading?(Number.isFinite(rotation)&&rotation>0?'Angle from input and confirmed wheel range':'Normalized input · read settings for degrees'):'No live steering reading';
    $('#input-status').textContent=available?'Receiving device input':'Connect your wheel to monitor inputs';
    $('#input-dot').classList.toggle('good',available);
  }
  ['throttle','brake','clutch'].forEach(type=>{
    const axis=pedalAxis(type),hasReading=available && axis && Number.isFinite(axis.value),value=hasReading?Math.round(clamp(axis.value)*100):null;
    const fill=$(`[data-pedal-fill="${type}"]`), label=$(`[data-pedal-value="${type}"]`), meter=$(`[data-pedal-meter="${type}"]`);
    if(fill)fill.style.setProperty('--pedal-scale',String((value || 0)/100));
    if(label)label.textContent=value===null?'—':`${value}%`;
    if(meter){meter.setAttribute('aria-valuetext',value===null?'No reading':`${value}%`);if(value===null)meter.removeAttribute('aria-valuenow');else meter.setAttribute('aria-valuenow',value);}
  });
  deviceAxes().forEach(axis=>{
    const matching=(key)=>$$(`[${key}]`).find(el=>el.getAttribute(key)===String(axis.code));
    const bar=matching('data-axis-bar'),raw=matching('data-axis-raw'),meter=matching('data-axis-meter');
    const value=available?Math.round(clamp(axis.value)*100):0;
    if(bar)bar.style.setProperty('--travel',`${value}%`);
    if(raw)raw.textContent=available?axis.raw:'—';
    if(meter){if(available)meter.setAttribute('aria-valuenow',value);else meter.removeAttribute('aria-valuenow');meter.setAttribute('aria-valuetext',available?`${value}%`:'No reading');}
  });
  (device.buttons || []).forEach(button=>{
    const el=$$('[data-input-button]').find(el=>el.dataset.inputButton===String(button.code));
    if(el){const pressed=available && button.pressed;el.classList.toggle('pressed',Boolean(pressed));el.setAttribute('aria-label',`${button.label || button.code}: ${pressed?'pressed':'released'}`);}
  });
  $$('[data-confirmed]').forEach(el=>{
    const id=el.dataset.confirmed,setting=schema.settings.find(s=>s.id===id);
    if(setting){const error=invalidSettings[id]?.message || applyErrors[id];el.textContent=error || `On device: ${humanValue(setting,h.values?.[id])}`;el.classList.toggle('error',Boolean(error));}
  });
  if($('#relay-log')) {
    const el=$('#relay-log'),atBottom=el.scrollTop+el.clientHeight>=el.scrollHeight-12;
    const value=(state.relay?.log || []).join('\n') || 'No relay output yet. Start a relay from Overview when your game requires it.';
    if(el.textContent!==value){el.textContent=value;if(atBottom)el.scrollTop=el.scrollHeight;}
  }
}
function updateControls() {
  $$('[data-mutation]').forEach(el=>el.disabled=busy || !online || el.dataset.empty==='true');
  const count=Object.keys(draft).length;
  const invalidCount=Object.keys(invalidSettings).length;
  $$('[data-number]').forEach(el=>el.setAttribute('aria-invalid',String(own(invalidSettings,el.dataset.number))));
  const saveButton=$('#profile-form button[type="submit"]');
  if(saveButton && invalidCount)saveButton.disabled=true;
  if($('#draft-count'))$('#draft-count').textContent=invalidCount?`Fix ${invalidCount} invalid setting${invalidCount===1?'':'s'}`:count?`${count} unapplied setting${count===1?'':'s'}`:'No unapplied changes';
  if($('#discard-draft'))$('#discard-draft').disabled=(!count && !invalidCount) || busy;
  if($('#apply-draft'))$('#apply-draft').disabled=Boolean(invalidCount) || !count || busy || !online || !state?.hardware?.connected || Boolean(state?.hardware?.conflict) || Boolean(state?.hardware?.busy);
  $$('[data-action="hardware-connect"],[data-action="hardware-disconnect"]').forEach(el=>el.disabled=busy || !online || Boolean(state?.hardware?.busy));
  $$('[data-pending]').forEach(el=>el.hidden=!own(draft,el.dataset.pending));
}
async function mutate(action) {
  if(busy)return;
  stateGeneration++;
  busy=true;
  clearTimeout(pollTimer);
  updateControls();
  try{await action();}
  catch(error){notify(error.message,true);}
  finally{busy=false;await poll();render();}
}
function recordSetting(element) {
  const id=element.dataset.setting,setting=schema.settings.find(s=>s.id===id);
  if(!setting)return;
  let value;
  if(element.tagName==='SELECT')value=JSON.parse(element.value);
  else {
    value=Number(element.value);
    if(element.value==='' || !element.validity.valid || !Number.isFinite(value)) {
      invalidSettings[id]={value:element.value,message:`Enter a value from ${setting.min ?? 0} to ${setting.max ?? 100}${setting.step?`, in steps of ${setting.step}`:''}.`};
      updateControls();updateLive();return;
    }
  }
  delete invalidSettings[id];
  if(!editingProfile && JSON.stringify(value)===JSON.stringify(state.hardware?.values?.[id]))delete draft[id];
  else draft[id]=value;
  delete applyErrors[id];
  $$('[data-setting]').filter(el=>el.dataset.setting===id && el!==element).forEach(el=>el.value=el.tagName==='SELECT'?JSON.stringify(value):value);
  if(element.type==='range')element.removeAttribute('aria-valuetext');
  updateControls();updateLive();
}

document.addEventListener('input',event=>{
  if(event.target.matches('[data-setting]'))recordSetting(event.target);
  if(event.target.id==='profile-name')profileName=event.target.value;
});
document.addEventListener('change',event=>{
  if(event.target.matches('select[data-setting]'))recordSetting(event.target);
  if(event.target.id==='profile-game')profileGame=event.target.value;
  if(event.target.id==='relay-profile')relayChoice=event.target.value;
});
document.addEventListener('submit',event=>{
  if(event.target.id!=='profile-form')return;
  event.preventDefault();
  if(Object.keys(invalidSettings).length){notify('Correct the invalid settings before saving.',true);return;}
  const name=profileName.trim();
  if(!name)return;
  const settings=profileSettings();
  if(!Object.keys(settings).length){notify('Read hardware settings or adjust a setting before saving.',true);return;}
  mutate(async()=>{
    const body={name,game_id:profileGame || null,settings};
    if(editingProfile)body.id=editingProfile;
    await api('/api/profiles','POST',body);
    notify(editingProfile?'Profile updated. Device settings are unchanged.':'Profile saved. Device settings are unchanged.');
    profileName='';profileGame='';editingProfile=null;
  });
});
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-action]');
  if(!button || button.disabled)return;
  const action=button.dataset.action,id=button.dataset.id;
  if(action==='retry'){poll();return;}
  if(action==='retry-schema'){loadSchema().then(render);return;}
  if(action==='discard'){draft={};applyErrors={};invalidSettings={};editingProfile=null;profileName='';profileGame='';render();notify('Draft discarded. Device settings are unchanged.');return;}
  if(action==='profile-delete-request'){deletingProfile=id;render();return;}
  if(action==='delete-cancel'){deletingProfile=null;render();return;}
  if(action==='profile-new'){editingProfile=null;profileName='';profileGame='';render();return;}
  if(action==='profile-edit') {
    const profile=state.profiles.find(p=>p.id===id);if(!profile)return;
    editingProfile=id;profileName=profile.name;profileGame=profile.game_id || '';draft={...profile.settings};applyErrors={};invalidSettings={};render();$('#profile-name').focus();return;
  }
  if(action==='copy-launch') {
    const options=state.games.find(g=>g.id===id)?.launch_options;
    if(options)navigator.clipboard.writeText(options).then(()=>notify('Launch options copied. Paste them into Steam game properties.')).catch(()=>notify('Clipboard access failed. Select and copy the launch options shown above.',true));
    return;
  }
  mutate(async()=>{
    if(action==='hardware-connect') {
      const result=await api('/api/hardware/connect','POST',{});
      state.hardware=result;
      if(result.error || result.conflict)throw new Error(result.error || result.conflict);
      const count=Object.keys(result.values || {}).length;
      if(result.connected && count)notify(`${count} device settings read. Your draft is preserved.`);
      else throw new Error(result.connected?'The port opened, but no device settings were confirmed. Check Diagnostics.':'Hardware did not connect. Check Diagnostics.');
    } else if(action==='hardware-disconnect') {
      state.hardware=await api('/api/hardware/disconnect','POST',{});
      notify('Hardware settings disconnected.');
    } else if(action==='apply') {
      if(Object.keys(invalidSettings).length)throw new Error('Correct the invalid settings before applying.');
      const requested={...draft};
      const result=await api('/api/hardware/apply','POST',{settings:requested});
      applyErrors=result.errors || {};
      state.hardware.values=result.values || {};
      let confirmed=0;
      const adjusted=[];
      for(const [key,value] of Object.entries(requested)) {
        if(!applyErrors[key] && own(result.applied,key) && own(result.values,key)) {
          if(JSON.stringify(draft[key])===JSON.stringify(value))delete draft[key];
          confirmed++;
          if(JSON.stringify(result.values[key])!==JSON.stringify(value)){const setting=schema.settings.find(s=>s.id===key);adjusted.push(`${setting?.label || key}: ${setting?humanValue(setting,result.values[key]):result.values[key]}`);}
        } else if(!applyErrors[key])applyErrors[key]='Device has not confirmed this value. Read settings before trying again.';
      }
      notify(`${confirmed} setting${confirmed===1?'':'s'} confirmed by the device.${adjusted.length?` Device precision: ${adjusted.join(', ')}.`:''}${Object.keys(applyErrors).length?' Unconfirmed changes remain in draft.':''}`,Boolean(Object.keys(applyErrors).length));
    } else if(action==='relay-start') {
      const result=await api('/api/relay/start','POST',{profile:relayChoice});
      if(result.running)notify('Relay started.');else throw new Error(result.error || 'Relay did not start. Check Diagnostics.');
    } else if(action==='relay-stop') {
      const result=await api('/api/relay/stop','POST',{});
      if(!result.running)notify('Relay stopped.');else throw new Error('Relay is still running. Check Diagnostics.');
    } else if(action==='profile-load') {
      const profile=state.profiles.find(p=>p.id===id);if(!profile)return;
      await api(`/api/profiles/${encodeURIComponent(id)}/activate`,'POST',{});
      draft={...profile.settings};applyErrors={};invalidSettings={};editingProfile=null;profileName='';profileGame='';
      notify(`${profile.name} loaded into draft. Apply in Wheelbase to write to the device.`);
    } else if(action==='profile-delete') {
      await api(`/api/profiles/${encodeURIComponent(id)}`,'DELETE',{});
      deletingProfile=null;if(editingProfile===id){editingProfile=null;profileName='';profileGame='';}
      notify('Profile deleted. Device settings are unchanged.');
    }
  });
});
window.addEventListener('hashchange',()=>{route=location.hash.slice(1)||'overview';render();window.scrollTo(0,0);$('#content').focus({preventScroll:true});});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll();});
async function loadSchema() {
  try{schema=await api('/api/schema');schemaError='';}
  catch(error){schemaError=`Settings could not be loaded. ${error.message}`;}
}
async function init() {
  await Promise.allSettled([loadSchema(),api('/api/session').then(session=>{token=session.token;})]);
  render();await poll();
}
init();
