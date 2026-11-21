'use strict';

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const h = html => { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; };
const clone = o => JSON.parse(JSON.stringify(o));
const stable = o => o === null || typeof o !== 'object' ? JSON.stringify(o)
  : Array.isArray(o) ? '[' + o.map(stable).join(',') + ']'
  : '{' + Object.keys(o).sort().map(k => JSON.stringify(k) + ':' + stable(o[k])).join(',') + '}';

let S = null;
let cfg = null;
let applied = null;
let curCar = null;
let lastStatus = null;
const built = {};
const ui = {};

const PAGES = [['game', 'Game'], ['cars', 'Cars'], ['nitro', 'Nitro'], ['police', 'Police & Heat'],
               ['copfly', 'CopFly'], ['world', 'No stopping'], ['profiles', 'Profiles']];
const api = () => window.pywebview.api;

function fmt(v) {
  v = Number(v);
  if (Math.abs(v) >= 100) return v.toFixed(0);
  return String(+v.toFixed(2));
}
function toPos(v, d) {
  v = Math.min(Math.max(v, d.lo), d.hi);
  return d.log ? Math.log(v / d.lo) / Math.log(d.hi / d.lo) : (v - d.lo) / (d.hi - d.lo);
}
function fromPos(p, d) {
  let v;
  if (d.log) {
    v = d.lo * Math.pow(d.hi / d.lo, p);
    const mag = Math.pow(10, Math.floor(Math.log10(v))) / 10;
    v = Math.round(v / mag) * mag;
  } else {
    v = d.lo + p * (d.hi - d.lo);
    if (d.integer) v = Math.round(v);
    else if (d.step) v = Math.round(v / d.step) * d.step;
  }
  return +v.toFixed(4);
}

function knob(def, value, onChange, opts = {}) {
  const el = h(`<div class="knob">
      <div><div class="knob-label">${esc(def.label)}</div><div class="knob-help">${esc(def.help)}</div></div>
      <div class="seg${opts.heat ? ' heat' : ''}"><div class="bar"></div><div class="fill"></div>
        ${def.stock != null ? '<div class="stock" title="stock"></div>' : ''}<input type="range" min="0" max="1000" step="1"></div>
      <div class="num"><input type="text" spellcheck="false"><span>${esc(opts.unit ?? '×')}</span></div></div>`);
  const range = $('input[type=range]', el), num = $('.num input', el), seg = $('.seg', el);
  if (def.stock != null) seg.style.setProperty('--s', (toPos(def.stock, def) * 100) + '%');
  const mark = v => el.classList.toggle('changed', !opts.noMark && def.stock != null && Math.abs(v - def.stock) > 1e-9);
  const set = (v, notify) => {
    el.value = v;
    const p = toPos(v, def);
    seg.style.setProperty('--p', (p * 100) + '%');
    range.value = Math.round(p * 1000);
    if (document.activeElement !== num) num.value = fmt(v);
    mark(v);
    if (notify) onChange(v);
  };
  range.addEventListener('input', () => {
    const v = fromPos(range.value / 1000, def);
    el.value = v;
    seg.style.setProperty('--p', (range.value / 10) + '%');
    num.value = fmt(v);
    mark(v);
    onChange(v);
  });
  const typed = () => {
    let v = parseFloat(num.value.replace(',', '.'));
    if (isNaN(v)) { num.value = fmt(el.value); return; }
    if (def.clamp || def.integer) v = Math.min(Math.max(v, def.lo), def.hi);
    if (def.integer) v = Math.round(v);
    num.value = fmt(v);
    if (v !== el.value) set(v, true);
  };
  num.addEventListener('change', typed);
  num.addEventListener('keydown', e => { if (e.key === 'Enter') { typed(); num.blur(); } });
  el.set = v => set(v, false);
  set(value, false);
  return el;
}

function sw(text, checked, onChange, cls = '') {
  const el = h(`<label class="sw ${cls}"><input type="checkbox"><span class="track"></span><span class="txt">${esc(text)}</span></label>`);
  const i = $('input', el);
  i.checked = !!checked;
  i.addEventListener('change', () => onChange(i.checked));
  el.set = v => { i.checked = !!v; };
  el.disable = d => el.classList.toggle('disabled', !!d);
  el.label = t => { $('.txt', el).textContent = t; };
  return el;
}

function btn(text, cls, onClick) {
  const b = h(`<button class="btn ${cls || ''}">${esc(text)}</button>`);
  b.addEventListener('click', onClick);
  return b;
}

function shell(id, title, sub) {
  const el = h(`<section class="page" id="p-${id}"><div class="page-head"><div class="page-title">${esc(title)}</div>
     <div class="page-sub">${esc(sub)}</div></div><div class="scroll"></div></section>`);
  $('#main').append(el);
  return $('.scroll', el);
}
const label = t => h(`<div class="section-label">${esc(t)}</div>`);

function toast(kind, title, lines = [], notes = []) {
  const el = h(`<div class="toast ${kind === 'err' ? 'err' : ''}"><div class="tt">${esc(title)}</div>
     ${lines.length ? '<ul>' + lines.map(l => '<li>' + esc(l) + '</li>').join('') + '</ul>' : ''}
     ${notes.map(n => '<div class="tn">' + esc(n) + '</div>').join('')}</div>`);
  $('#toasts').append(el);
  const close = () => { el.classList.add('out'); setTimeout(() => el.remove(), 300); };
  el.addEventListener('click', close);
  setTimeout(close, kind === 'err' ? 9000 : 6500 + 400 * notes.length);
}

function confirmBox(title, text, okText = 'Yes', danger = false) {
  return new Promise(res => {
    const m = $('#modal');
    m.innerHTML = '';
    const box = h(`<div class="modal-box"><div class="tt">${esc(title)}</div><p>${esc(text)}</p>
       <div class="row"><button class="btn" data-a="0">Cancel</button>
       <button class="btn ${danger ? 'danger' : 'primary'}" data-a="1">${esc(okText)}</button></div></div>`);
    m.append(box);
    m.hidden = false;
    box.addEventListener('click', e => {
      const a = e.target.closest('[data-a]');
      if (!a) return;
      m.hidden = true;
      res(a.dataset.a === '1');
    });
  });
}

function loadState(st) {
  S = st;
  cfg = clone(S.cfg);
  applied = !S.game.ok ? null : S.needsApply ? '' : stable(S.cfg);
  if (!S.cars.some(c => c.id === curCar)) curCar = null;
  for (const id of Object.keys(built)) REFRESH[id]();
  changed();
  if (S.notice) toast('ok', 'Backup updated', [S.notice]);
}

function changed() {
  const dirty = applied !== null && stable(cfg) !== applied;
  const tuned = Object.values(cfg.cars).filter(c => c.enabled).length;
  const nitro = Object.values(cfg.cars).filter(c => c.nitro).length;
  const sum = `${tuned} car${tuned === 1 ? '' : 's'} tuned &middot; ${nitro} unlimited nitro`;
  $('#applyState').innerHTML = !S.game.ok ? '<span class="st dirty">Select your game folder</span>'
    : dirty ? `<span class="st dirty">&#9679; Changes not applied</span><br>${sum}`
    : `<span class="st clean">&#10003; Game is up to date</span><br>${sum}`;
  try { api().set_dirty(dirty); } catch (e) { }
}

const carEntry = id => (cfg.cars[id] ||= { enabled: false, knobs: {}, nitro: false });
const carName = id => (S.cars.find(c => c.id === id) || { name: id }).name;

function buildNav() {
  PAGES.forEach(([id, text], i) => {
    const el = h(`<div class="nav-item" data-id="${id}"><span class="num">0${i + 1}</span><span class="lbl">${esc(text)}</span></div>`);
    el.addEventListener('click', () => show(id));
    $('#nav').append(el);
  });
}
function show(id) {
  $$('.nav-item').forEach(n => n.classList.toggle('active', n.dataset.id === id));
  if (!built[id]) { BUILD[id](); built[id] = true; }
  REFRESH[id]();
  $$('.page').forEach(p => p.classList.toggle('active', p.id === 'p-' + id));
}

const BUILD = {}, REFRESH = {};
BUILD.game = () => {
  const s = shell('game', 'Game', 'Point the studio at your NFS Most Wanted (2005) folder. Your original files are backed up '
    + 'once, the first time you press Apply, and are always one click away.');
  const p = h('<div class="panel"><div class="path-row"><div class="path" id="gamePath"></div></div></div>');
  const row = $('.path-row', p);
  row.append(btn('Browse', '', async () => gotState(await api().browse())),
             btn('Auto-detect', '', async () => gotState(await api().autodetect())));
  s.append(p, label('Checklist'));
  ui.status = h('<div class="status-grid"></div>');
  s.append(ui.status);
  const act = h('<div class="row" style="margin-top:18px"></div>');
  act.append(btn('Open game folder', '', () => api().open_folder()),
             btn('Restore original game files', 'danger', restore));
  s.append(act);
};
REFRESH.game = async () => {
  $('#gamePath').textContent = S.game.path || 'No game folder selected';
  ui.status.innerHTML = '<div class="note">Checking&hellip;</div>';
  lastStatus = await api().status();
  ui.status.innerHTML = '';
  for (const c of lastStatus) {
    const el = h(`<div class="status ${c.state}"><div class="led"></div><div class="grow"><div class="t">${esc(c.title)}</div>
       <div class="d">${esc(c.text)}</div></div></div>`);
    if (c.link) el.append(btn('Get it', 'small', () => api().open_url(c.link)));
    ui.status.append(el);
  }
};
function gotState(r) {
  if (!r) return;
  if (r.error) { toast('err', 'Game folder', [r.error]); return; }
  loadState(r);
  toast('ok', 'Game folder set', [r.game.path]);
}
async function restore() {
  if (!S.game.ok) return;
  if (!await confirmBox('Restore originals?', 'Puts the original car data back: car tunes, nitro, police and spike mods are '
      + 'removed. Add-on cars, CopFly and heat settings stay as they are.', 'Restore', true)) return;
  const r = await api().restore();
  if (!r.ok) { toast('err', 'Not restored', [r.error]); return; }
  loadState(r.state);
  toast('ok', 'Original car data restored');
}

BUILD.cars = () => {
  const page = h(`<section class="page" id="p-cars"><div class="page-head"><div class="page-title">Cars</div>
     <div class="page-sub">Pick a car, switch tuning on and move the sliders. The white tick is stock (1.0). Every tune also
     applies to the car's fully upgraded version.</div></div><div class="cars-layout"></div></section>`);
  $('#main').append(page);
  const lay = $('.cars-layout', page);
  const col = h('<div class="car-col"><div class="car-tools"><input class="search" placeholder="Search cars..."></div><div class="car-list"></div></div>');
  ui.search = $('.search', col);
  ui.search.addEventListener('input', renderCarList);
  ui.onlyModded = sw('Only modded cars', false, renderCarList, 'mini');
  $('.car-tools', col).append(ui.onlyModded);
  ui.carList = $('.car-list', col);
  const ed = h('<div class="editor scroll"></div>');
  lay.append(col, ed);

  const head = h(`<div class="panel"><div class="car-head"><div>
       <div class="car-name" id="carName"></div><div class="car-id" id="carId"></div><div class="note" id="carShared"></div>
       <div class="car-ctrl" id="carCtrl"></div><div class="note warn" id="carNitroNote" style="margin-top:10px"></div>
     </div><div class="stats" id="carStats"></div></div></div>`);
  ed.append(head);
  ui.tune = sw('Tune this car', false, v => { if (!curCar) return; carEntry(curCar).enabled = v; carChanged(); });
  ui.nitro = sw('Unlimited nitro', false, v => { if (!curCar) return; carEntry(curCar).nitro = v; carChanged(); }, 'nos');
  ui.preset = h(`<select class="preset"><option value="">Load a preset&hellip;</option>${Object.keys(S.presets).filter(p => p !== 'Stock')
    .map(p => `<option>${esc(p)}</option>`).join('')}</select>`);
  ui.preset.addEventListener('change', () => { if (ui.preset.value) applyPreset(ui.preset.value); });
  $('#carCtrl', head).append(ui.tune, ui.nitro, ui.preset, btn('Reset to stock', 'small', () => applyPreset('Stock')));
  ui.stats = [['power', 'Power'], ['gearing', 'Top-speed gearing'], ['grip', 'Grip'], ['brakes', 'Brakes']].map(([k, t]) => {
    const el = h(`<div class="stat"><div class="sl"><span>${t}</span><b></b></div><div class="meter"><i></i><u></u></div></div>`);
    $('#carStats', head).append(el);
    return [k, el];
  });

  ui.knobs = {};
  for (const adv of [false, true]) {
    ed.append(label(adv ? 'Advanced handling' : 'Performance'));
    for (const k of S.knobs.filter(k => k.advanced === adv)) {
      const def = { ...k, stock: 1 };
      const el = knob(def, 1, v => {
        if (!curCar) return;
        const e = carEntry(curCar);
        e.knobs[k.key] = v;
        if (!e.enabled && v !== 1) { e.enabled = true; ui.tune.set(true); }
        carChanged(false);
      });
      ui.knobs[k.key] = el;
      ed.append(el);
    }
  }
};
REFRESH.cars = () => {
  if (!S.cars.length) {
    ui.carList.innerHTML = '<div class="note" style="padding:14px">Select your game folder on the Game page first.</div>';
    $('#carName').textContent = 'No game';
    return;
  }
  if (!curCar) curCar = (S.cars.find(c => (cfg.cars[c.id] || {}).enabled) || S.cars[0]).id;
  selectCar(curCar);
};
function renderCarList() {
  const q = ui.search.value.trim().toLowerCase();
  const only = $('input', ui.onlyModded).checked;
  ui.carList.innerHTML = '';
  for (const c of S.cars) {
    const e = cfg.cars[c.id] || {};
    if (q && !c.name.toLowerCase().includes(q) && !c.id.includes(q)) continue;
    if (only && !(e.enabled || e.nitro)) continue;
    const el = h(`<div class="car${c.id === curCar ? ' sel' : ''}"><span class="nm">${esc(c.name)}</span>
       ${e.enabled ? '<span class="badge tuned">TUNED</span>' : ''}${e.nitro ? '<span class="badge nos">NOS</span>' : ''}</div>`);
    el.addEventListener('click', () => selectCar(c.id));
    ui.carList.append(el);
  }
}
function selectCar(id) {
  curCar = id;
  const car = S.cars.find(c => c.id === id);
  const e = cfg.cars[id] || { enabled: false, knobs: {}, nitro: false };
  $('#carName').textContent = car.name;
  $('#carId').textContent = 'Internal name: ' + car.id;
  const notes = [];
  if (car.garage) notes.push('Not one of the race cars: it is listed because it is in your garage.');
  if (car.shared.length) notes.push('Shares tuning data with ' + car.shared.join(', ') + ': tuning one changes both.');
  if (car.traffic && car.traffic.length) notes.push('Traffic uses the same data, so these get the same tune: ' + car.traffic.join(', ') + '.');
  $('#carShared').textContent = notes.join(' ');
  ui.tune.set(e.enabled);
  ui.nitro.set(e.nitro && car.nitro);
  ui.nitro.disable(!car.nitro);
  $('#carNitroNote').textContent = !car.nitro ? (car.garage ? 'Unlimited nitro is not possible for this vehicle.'
      : 'Unlimited nitro is not possible for this car on its own: use "Unlimited nitro for every racer" on the Nitro page.')
    : car.via ? `Unlimited nitro here also turns it on for the ${car.via} (the game data links them).` : '';
  for (const [k, el] of Object.entries(ui.knobs)) el.set(e.knobs[k] ?? 1);
  ui.preset.value = '';
  updateStats();
  renderCarList();
}
function updateStats() {
  const e = cfg.cars[curCar] || { knobs: {} };
  for (const [k, el] of ui.stats) {
    const def = S.knobs.find(x => x.key === k), v = e.knobs[k] ?? 1;
    $('b', el).textContent = '×' + fmt(v);
    $('u', el).style.setProperty('--p', Math.max(4, toPos(v, def) * 100) + '%');
  }
}
function carChanged(relist = true) {
  updateStats();
  changed();
  if (relist) renderCarList();
  else { const sel = $('.car.sel', ui.carList); if (sel && !$('.badge.tuned', sel) && cfg.cars[curCar]?.enabled) renderCarList(); }
  if (built.nitro) REFRESH.nitro();
}
function applyPreset(name) {
  const e = carEntry(curCar), car = S.cars.find(c => c.id === curCar);
  e.knobs = clone(S.presets[name]);
  e.enabled = name !== 'Stock';
  if (S.presetNitro.includes(name) && car.nitro) e.nitro = true;
  selectCar(curCar);
  changed();
  if (built.nitro) REFRESH.nitro();
  if (name !== 'Stock') toast('ok', name, [`Loaded on the ${car.name}. Press Apply to put it in the game.`]);
}

BUILD.nitro = () => {
  const s = shell('nitro', 'Nitro', 'Unlimited nitro never runs out. Turn it on per car, or for every racer at once (AI opponents too).');
  ui.boost = knob({ label: 'Nitro boost strength', help: 'Extra power while the nitro is on. The white tick is the best stock nitro. '
      + 'Applies to every car with unlimited nitro.', lo: 1, hi: 6, step: 0.1, stock: 1, clamp: true }, 3,
    v => { cfg.nitro.boost = v; changed(); }, { noMark: true });
  const all = h('<div class="panel"></div>');
  ui.allRacers = sw('Unlimited nitro for every racer (AI opponents too)', false, v => { cfg.nitro.all_racers = v; changed(); }, 'nos');
  all.append(ui.allRacers);
  ui.nitroGrid = h('<div class="nitro-grid"></div>');
  s.append(ui.boost, all, label('Per car'), ui.nitroGrid,
           h('<div class="note" style="margin-top:12px">Linked cars share one nitro entry in the game data, so both get it. '
             + 'Greyed-out cars cannot have their own: use the switch for every racer.</div>'));
};
REFRESH.nitro = () => {
  ui.boost.set(cfg.nitro.boost ?? 3);
  ui.allRacers.set(cfg.nitro.all_racers);
  ui.nitroGrid.innerHTML = '';
  for (const c of S.cars) {
    const e = cfg.cars[c.id] || {};
    const item = h('<div class="nitro-item"></div>');
    const t = sw(c.name, e.nitro && c.nitro, v => {
      carEntry(c.id).nitro = v;
      changed();
      if (built.cars && curCar === c.id) selectCar(c.id); else if (built.cars) renderCarList();
    }, 'mini nos');
    t.disable(!c.nitro);
    item.append(t);
    if (!c.nitro) item.append(h('<span class="sub">not possible for this car</span>'));
    else if (c.via) item.append(h(`<span class="sub">also turns it on for the ${esc(c.via)}</span>`));
    ui.nitroGrid.append(item);
  }
};

BUILD.police = () => {
  const s = shell('police', 'Police & Heat', 'Tougher cop cars, tires that survive spike strips and heat levels up to 10.');
  ui.lightbar = h('<div class="lightbar">' + '<i></i>'.repeat(12) + '</div>');
  const p = h(`<div class="panel"><div class="row"><div class="grow" id="polTop"></div></div>
     <div class="note" style="margin-top:8px">Every pursuit cop car (Crown Vic, GTO, Corvette, Rhino SUV, Cross) gets faster, grippier
     and brakes harder. Keep it moderate so the AI can still drive them.</div></div>`);
  ui.police = sw('Tougher police cars', false, v => { cfg.police.enabled = v; policeChanged(); });
  $('#polTop', p).append(ui.police);
  $('.row', p).append(btn('Load "Harder Cops"', 'small', () => {
    cfg.police.knobs = clone(S.presets['Harder Cops']);
    cfg.police.enabled = true;
    REFRESH.police();
    changed();
  }));
  s.append(ui.lightbar, p);
  ui.polKnobs = {};
  for (const k of S.knobs.filter(k => !k.advanced)) {
    const el = knob({ ...k, stock: 1 }, 1, v => {
      cfg.police.knobs[k.key] = v;
      if (!cfg.police.enabled && v !== 1) { cfg.police.enabled = true; ui.police.set(true); }
      policeChanged();
    });
    ui.polKnobs[k.key] = el;
    s.append(el);
  }
  const sp = h(`<div class="panel" style="margin-top:14px"><div class="note" style="margin-top:8px">Spike strips no longer pop your
     tires (applies to AI racers too).</div></div>`);
  ui.spike = sw('Spike-proof tires', false, v => { cfg.police.no_puncture = v; changed(); });
  sp.prepend(ui.spike);
  s.append(label('Tires'), sp, label('Heat'));
  ui.heat = h('<div></div>');
  s.append(ui.heat);
};
function policeChanged() {
  ui.lightbar.classList.toggle('on', !!cfg.police.enabled);
  changed();
}
REFRESH.police = () => {
  ui.police.set(cfg.police.enabled);
  ui.lightbar.classList.toggle('on', !!cfg.police.enabled);
  for (const [k, el] of Object.entries(ui.polKnobs)) el.set(cfg.police.knobs[k] ?? 1);
  ui.spike.set(cfg.police.no_puncture);
  ui.heat.innerHTML = '';
  if (!S.extraOptions || !cfg.heat) {
    const p = h(`<div class="panel"><div class="row"><div class="grow"><div class="h2">Heat levels</div>
       <div class="note">Heat above 5 needs the free "NFSMW Extra Options" plugin by ExOpts Team. Put it in your game's scripts
       folder, then reopen the studio.</div></div></div></div>`);
    $('.row', p).append(btn('Get Extra Options', 'primary', () => api().open_url(S.links.extra_options)));
    ui.heat.append(p);
    return;
  }
  const hp = h(`<div class="panel"><div class="note">Saved in the Extra Options settings. In free roam press <b>F7</b>, then
     <b>PageUp</b> to raise the heat.</div><div class="row" style="margin-top:12px;gap:28px" id="heatSw"></div>
     <div class="pips" id="pips"></div></div>`);
  const sOv = sw('Override heat levels', cfg.heat.override, v => { cfg.heat.override = v; changed(); });
  const sAc = sw('Pursuit action mode', cfg.heat.action_mode, v => { cfg.heat.action_mode = v; changed(); });
  $('#heatSw', hp).append(sOv, sAc);
  const pips = $('#pips', hp);
  const drawPips = () => {
    pips.innerHTML = '';
    for (let i = 1; i <= 10; i++) {
      const on = i >= cfg.heat.min && i <= cfg.heat.max;
      pips.append(h(`<i class="${on ? 'on l' + Math.ceil(i / 2) : ''}">${i}</i>`));
    }
  };
  const def = { lo: 1, hi: 10, integer: true, clamp: true };
  const kMin = knob({ ...def, label: 'Minimum heat', help: 'The lowest heat level of every pursuit.' }, cfg.heat.min, v => {
    cfg.heat.min = v;
    if (v > cfg.heat.max) { cfg.heat.max = v; kMax.set(v); }
    drawPips(); changed();
  }, { heat: true, unit: 'LVL' });
  const kMax = knob({ ...def, label: 'Maximum heat', help: '10 = the most aggressive police the game has.' }, cfg.heat.max, v => {
    cfg.heat.max = v;
    if (v < cfg.heat.min) { cfg.heat.min = v; kMin.set(v); }
    drawPips(); changed();
  }, { heat: true, unit: 'LVL' });
  drawPips();
  ui.heat.append(hp, kMin, kMax);
};

BUILD.copfly = () => {
  const s = shell('copfly', 'CopFly', 'Ram a cop car and it gets launched into the air. Your car must really touch the cop (front, rear '
    + 'or side) at speed, and the harder you hit, the higher it flies.');
  const hero = h(`<div class="hero"><div class="lightbar" style="margin-bottom:14px">${'<i></i>'.repeat(12)}</div>
     <div class="row"><div class="grow"><div class="hero-title">Cop<span>Fly</span></div>
     <div class="hero-tag">RAM IT &middot; LAUNCH IT &middot; REPEAT</div><div class="chips" id="cfChips"></div></div>
     <div id="cfBtns" class="row"></div></div></div>`);
  ui.cfLight = $('.lightbar', hero);
  $('#cfBtns', hero).append(btn('Defaults', 'small', () => { cfg.copfly.settings = {}; for (const d of S.copflyDefs) cfg.copfly.settings[d.key] = d.default; REFRESH.copfly(); changed(); }),
                            btn('Open log', 'small', async () => { if (!await api().open_log()) toast('err', 'No log yet', ['It is written while you play with CopFly installed.']); }));
  const inst = h('<div class="panel"></div>');
  ui.cfInstall = sw('Install CopFly', false, v => { cfg.copfly.installed = v; ui.cfLight.classList.toggle('on', v); changed(); });
  inst.append(ui.cfInstall);
  s.append(hero, inst, label('Settings'));
  ui.cf = {};
  for (const d of S.copflyDefs) {
    let el;
    if (d.kind === 'bool') {
      el = h(`<div class="panel flat"><div class="note" style="margin-top:6px">${esc(d.help)}</div></div>`);
      const t = sw(d.label, false, v => { cfg.copfly.settings[d.key] = v ? 1 : 0; changed(); });
      el.prepend(t);
      el.set = v => t.set(+v);
    } else {
      el = knob({ ...d, stock: d.default, clamp: true }, d.default, v => { cfg.copfly.settings[d.key] = v; changed(); }, { unit: '' });
    }
    ui.cf[d.key] = el;
    s.append(el);
  }
};
REFRESH.copfly = async () => {
  ui.cfInstall.set(cfg.copfly.installed);
  ui.cfLight.classList.toggle('on', !!cfg.copfly.installed);
  for (const d of S.copflyDefs) ui.cf[d.key].set(cfg.copfly.settings?.[d.key] ?? d.default);
  const chips = $('#cfChips');
  if (!S.game.ok) { chips.innerHTML = ''; return; }
  const st = lastStatus || await api().status();
  lastStatus = st;
  const pick = t => st.find(x => x.title.startsWith(t)) || {};
  const cf = pick('CopFly'), ld = pick('ASI loader');
  chips.innerHTML = `<span class="chip ${cf.state === 'ok' ? 'ok' : 'bad'}">speed.exe v1.3 ${cf.state === 'ok' ? '&#10003;' : '&#10007;'}</span>
    <span class="chip ${ld.state === 'ok' ? 'ok' : 'warn'}">ASI loader ${ld.state === 'ok' ? '&#10003;' : 'missing'}</span>`;
};

const NOSTOP = [
  ['keep_cops', 'Police cars', 'Ramming or getting rammed by cop cars no longer slows you down: your car keeps the speed it '
    + 'had just before the hit, and the cop gets shoved out of the way.'],
  ['keep_traffic', 'Traffic cars', 'Crashing into traffic (and other racers) no longer slows you down: you keep your speed '
    + 'and the other car gets shoved out of the way.'],
  ['no_stopping', 'Obstacles', 'Poles, trees, signs, hydrants, parking meters, fences, benches, parked cars and other props '
    + 'break off the moment you touch them and weigh almost nothing. The heavy pursuit-breaker parts stay as they are, so '
    + 'pursuit breakers still crush cops. Spike strips are not changed.'],
  ['keep_walls', 'Walls', 'Hitting a wall at an angle no longer slows you down: you slide along it at full speed. A head-on '
    + 'hit still stops you, because the car cannot drive through the wall.'],
];
BUILD.world = () => {
  const s = shell('world', 'No stopping', 'Crash into things without losing speed. Switch on what you want, then press Apply.');
  ui.nostop = {};
  for (const [key, title, text] of NOSTOP) {
    const p = h(`<div class="panel" style="margin-bottom:14px"><div class="note" style="margin-top:8px">${esc(text)}</div></div>`);
    const t = sw(title, false, v => { cfg.world[key] = v; changed(); });
    p.prepend(t);
    ui.nostop[key] = t;
    s.append(p);
  }
  s.append(h(`<div class="note">Police cars, traffic cars and walls use the CopFly plugin, which the studio installs for you
     (launching cops stays as set on the CopFly page). They need the v1.3 speed.exe and an ASI loader, like CopFly.</div>`));
};
REFRESH.world = () => {
  for (const [key] of NOSTOP) ui.nostop[key].set(!!(cfg.world && cfg.world[key]));
};

BUILD.profiles = () => {
  const s = shell('profiles', 'Profiles', 'Save your whole setup to a file and share it, or load someone else\'s. Loading only changes '
    + 'what you see here: press Apply to put it in the game.');
  const p = h('<div class="panel"><div class="row"></div></div>');
  $('.row', p).append(
    btn('Save setup to file', 'primary', async () => { const n = await api().save_profile(cfg); if (n) toast('ok', 'Setup saved', [n]); }),
    btn('Load setup from file', '', async () => {
      const r = await api().load_profile();
      if (!r) return;
      if (r.error) { toast('err', 'Not loaded', [r.error]); return; }
      useConfig(r.cfg, r.name);
    }));
  s.append(p, label('Built-in setups'));
  for (const b of S.builtins) {
    const c = h(`<div class="panel"><div class="profile"><div class="grow"><div class="h2">${esc(b.name)}</div>
       <div class="note">${esc(b.desc)}</div></div></div></div>`);
    $('.profile', c).append(btn('Load', 'primary', async () => useConfig(await api().builtin(b.name), b.name)));
    s.append(c);
  }
};
REFRESH.profiles = () => {};
function useConfig(newCfg, name) {
  if (newCfg.heat == null && cfg.heat) newCfg.heat = cfg.heat;
  if (!S.extraOptions) newCfg.heat = null;
  cfg = newCfg;
  for (const id of Object.keys(built)) if (id !== 'game') REFRESH[id]();
  changed();
  toast('ok', name + ' loaded', ['Press APPLY TO GAME to put it in the game.']);
}

async function doApply() {
  if (!S.game.ok) { toast('err', 'No game folder', ['Select your NFS Most Wanted folder first.']); show('game'); return; }
  const b = $('#applyBtn');
  b.classList.add('busy');
  $('span', b).textContent = 'APPLYING…';
  let r;
  try { r = await api().apply(cfg); } finally { b.classList.remove('busy'); $('span', b).textContent = 'APPLY TO GAME'; }
  if (!r.ok) { toast('err', 'Not applied', [r.error]); return; }
  lastStatus = null;
  loadState(r.state);
  b.classList.remove('pulse'); void b.offsetWidth; b.classList.add('pulse');
  toast('ok', 'Mods installed', r.lines, r.notes);
}

async function start() {
  try {
    const st = await api().get_state();
    buildNav();
    $('#ver').innerHTML = 'v' + esc(st.app.version) + (st.app.repo ? ' &middot; <a id="repo">GitHub</a>' : '');
    if (st.app.repo) $('#repo').addEventListener('click', () => api().open_url(st.app.repo));
    S = st;
    loadState(st);
    show(st.game.ok ? 'cars' : 'game');
    $('#applyBtn').addEventListener('click', doApply);
    document.addEventListener('keydown', e => { if (e.ctrlKey && e.key === 's') { e.preventDefault(); doApply(); } });
    setTimeout(() => $('#splash').classList.add('gone'), 350);
  } catch (e) {
    $('#splashMsg').textContent = 'Something went wrong: ' + e;
  }
}
if (window.__MOCK__) window.pywebview = { api: window.__MOCK__ };
if (window.pywebview && window.pywebview.api && window.pywebview.api.get_state) start();
else window.addEventListener('pywebviewready', start);
