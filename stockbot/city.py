"""Bot City: the stock bot as a 3D neon city (the City tab).

Each strategy is a district on a ring around the Vault. Every stock it holds is a
building: taller = more money in it, green / red glow = up / down on it, and a
beam over each district shows how that strategy is doing. Trades fire beams and
shockwaves: a buy is a cyan beam, a sale at a profit is a green "PROFIT LOCKED",
a stop-out is a red "STOPPED OUT". The Vault in the middle is the whole bot.

Live: prices from /live every 10 s recolour the buildings and the Vault; new
trades from /city.json (every 20 s) fire their effects as they happen. Replay
plays every trade since the start in about 30 seconds over the bot-vs-SPY line.

Read-only. Drawn in the browser with three.js from a CDN, so the phone needs
internet for the first load (the browser caches it after that).
"""

import calendar
import datetime

import charts
import scorecard
import stockbot

THREE = "0.160.0"


def _x(t):
    """'2026-11-12 09:30:35' (New York wall clock) -> seconds, for ordering on one timeline."""
    try:
        d = datetime.datetime.strptime(str(t)[:19].ljust(19, "0")[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            d = datetime.datetime.strptime(str(t)[:16], "%Y-%m-%d %H:%M")
        except ValueError:
            return None
    return calendar.timegm(d.timetuple())


def data():
    px = stockbot.price_now()
    px.update(charts.live())
    for b in ("SPY", "QQQ"):                     # benchmarks: fall back to the cached daily close
        if not px.get(b):
            rows = charts.bars(b)
            if rows:
                px[b] = rows[-1][4]
    led = [o for o in stockbot.ledger() if o.get("status") in ("filled", "partially_filled")]
    sleeves, net_in, spy_sh, qqq_sh = [], 0.0, 0.0, 0.0
    for o in led:
        try:
            amt = float(o.get("qty") or 0) * float(o.get("price") or 0)
            sg = 1 if o.get("side") == "buy" else -1
            net_in += sg * amt
            if o.get("spy"):
                spy_sh += sg * amt / float(o["spy"])
            if o.get("qqq"):
                qqq_sh += sg * amt / float(o["qqq"])
        except (TypeError, ValueError, ZeroDivisionError):
            continue
    summ, sales = scorecard.summary(px)
    for name in stockbot.SLEEVES:
        hold = stockbot.holdings(name)[0]
        pos = []
        for sym, h in sorted(hold.items(), key=lambda kv: -kv[1]["cost"]):
            p = px.get(sym, h["avg"])
            pos.append({"sym": sym, "qty": h["qty"], "cost": round(h["cost"], 4), "px": p})
        sleeves.append({"name": name, "label": "TQQQ" if name == "tqqq" else name.capitalize(), "pos": pos,
                        "realized": round(summ[name]["realized"], 2), "sales": summ[name]["n"],
                        "won": summ[name]["won"]})
    pnl_of = {(s["sleeve"], s["symbol"], s["time"]): s for s in sales}
    events = []
    for o in led:
        key = (o.get("sleeve"), o.get("symbol"), str(o.get("time", "")))
        s = pnl_of.get(key) if o.get("side") == "sell" else None
        try:
            usd = float(o.get("qty") or 0) * float(o.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if usd < scorecard.DUST:
            continue
        events.append({"id": o.get("order_id") or "%s|%s|%s|%s" % (key + (o.get("side"),)), "t": str(o.get("time", "")),
                       "x": _x(o.get("time")), "sleeve": o.get("sleeve"), "sym": o.get("symbol"), "side": o.get("side"),
                       "usd": round(usd, 2), "pnl": round(s["usd"], 2) if s else None,
                       "reason": s["reason"] if s else None})
    hist = charts.dollars(stockbot.load("history.json", []))
    step = max(1, len(hist) // 400)
    keep = hist[::step] + ([hist[-1]] if hist and (len(hist) - 1) % step else [])
    days = charts.periods(hist, 10)[-10:]
    live = stockbot.load("live.json", {})
    return {"time": stockbot.stamp(), "session": live.get("session"), "net_in": round(net_in, 2),
            "spy_sh": spy_sh, "qqq_sh": qqq_sh, "spy": px.get("SPY"), "qqq": px.get("QQQ"),
            "start": led[0]["time"][:10] if led else None, "sleeves": sleeves, "events": events[-120:],
            "hist": [[p["t"], _x(p["t"]), round(p["bot"], 2), round(p["spy"], 2)] for p in keep],
            "days": [[d["key"], round(d["bot"], 2)] for d in days]}


def page(tabs_html):
    first = charts._json(data())
    return (PAGE.replace("@TABS@", tabs_html).replace("@DATA@", first).replace("@THREE@", THREE))


PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>bot city</title>
<style>
html, body { margin:0; height:100%; background:#07051a; color:#e6edf3; overflow:hidden;
  font-family:-apple-system, Segoe UI, Roboto, sans-serif; -webkit-tap-highlight-color:transparent; }
#c { position:fixed; inset:0; display:block; touch-action:none; }
.top { position:fixed; left:0; right:0; top:0; padding:10px 12px 0; z-index:5; pointer-events:none; }
.top > * { pointer-events:auto; }
.tabs { display:flex; flex-wrap:wrap; gap:5px; margin:0 0 6px; }
.tabs a { padding:4px 9px; border-radius:7px; background:#161b22cc; border:1px solid #30363d; color:#8b949e;
  text-decoration:none; font-size:12px; white-space:nowrap; }
.tabs a.on { color:#e6edf3; border-color:#58a6ff; }
.hud { display:flex; gap:5px; flex-wrap:wrap; align-items:center; }
.pill { font:11px ui-monospace, Menlo, monospace; padding:4px 8px; border-radius:20px; background:#0b0f14cc;
  border:1px solid #30363d; color:#c9d1d9; white-space:nowrap; }
.pill b { color:#e6edf3; } .live { color:#3fb950; } .live::before { content:"\25CF  "; }
button.pill { cursor:pointer; } button.pill.on { border-color:#f0b429; color:#f0b429; }
.days { display:none; align-items:center; gap:6px; }
.days .tot { font-weight:700; }
.days .bars { display:inline-flex; gap:2px; align-items:flex-end; height:12px; }
.days .bars i { display:block; width:5px; border-radius:1px; min-height:2px; }
.lbl { position:fixed; left:0; top:0; z-index:3; transform:translate(-50%, -100%); pointer-events:none;
  font:9px/1.3 ui-monospace, Menlo, monospace; white-space:nowrap; text-align:center; padding:2px 6px;
  border-radius:5px; background:#0b0f14cc; border:1px solid #30363d; }
.lbl b { font-size:10px; letter-spacing:.06em; text-transform:uppercase; margin-right:5px; }
.lbl.vault b { display:block; margin:0; }
.lbl.vault { border-color:#f0b429; background:#1a1305e6; }
.lbl.vault b { color:#f0b429; } .lbl.vault .big { font-size:17px; font-weight:700; }
.toast { position:fixed; left:0; top:0; z-index:6; transform:translate(-50%, -100%); pointer-events:none;
  font:700 11px ui-monospace, Menlo, monospace; padding:4px 8px; border-radius:6px; white-space:nowrap;
  border:1px solid; background:#0b0f14ee; transition:opacity .4s; }
.g { color:#3fb950; } .r { color:#f85149; } .c { color:#39d0ff; } .m { color:#8b949e; }
.toast.g { border-color:#3fb950; box-shadow:0 0 14px #3fb95080; }
.toast.r { border-color:#f85149; box-shadow:0 0 14px #f8514980; }
.toast.c { border-color:#39d0ff; box-shadow:0 0 14px #39d0ff80; }
.chart { position:fixed; left:8px; right:8px; bottom:8px; height:84px; z-index:4; background:#0b0f14c0;
  border:1px solid #30363d; border-radius:8px; }
.chart canvas { width:100%; height:100%; display:block; }
.chart .k { position:absolute; left:8px; top:4px; font:10px ui-monospace, Menlo, monospace; color:#8b949e; }
.card { position:fixed; left:50%; bottom:100px; transform:translateX(-50%); z-index:7; min-width:220px;
  background:#0b0f14f2; border:1px solid #58a6ff; border-radius:10px; padding:10px 12px; display:none;
  font:12px/1.5 ui-monospace, Menlo, monospace; }
.card a { color:#58a6ff; }
.err { position:fixed; inset:120px 20px auto; z-index:9; text-align:center; color:#c9d1d9; display:none;
  font:14px/1.5 -apple-system, sans-serif; }
</style>
<script type="importmap">{"imports":{"three":"https://cdn.jsdelivr.net/npm/three@@THREE@/build/three.module.js",
"three/addons/":"https://cdn.jsdelivr.net/npm/three@@THREE@/examples/jsm/"}}</script>
</head><body>
<canvas id="c"></canvas>
<div class="top">@TABS@
<div class="hud"><span class="pill" id="clock">loading</span><span class="pill" id="vs"></span>
<button class="pill" id="replay">&#9654; replay</button><button class="pill on" id="glow">glow</button>
<button class="pill" id="home">reset view</button><span class="pill days" id="days"></span></div></div>
<div class="chart"><canvas id="ch"></canvas><div class="k" id="chk">bot vs same money in SPY</div></div>
<div class="card" id="card"></div>
<div class="err" id="err">The 3D view couldn't start. It needs internet the first time (for the 3D library) and a
browser with WebGL. Everything else is on the Stocks and Charts tabs.</div>
<script type="application/json" id="d0">@DATA@</script>
<script>setTimeout(function(){ if (!window.CITY_OK) document.getElementById('err').style.display='block'; }, 12000);</script>
<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

let D = JSON.parse(document.getElementById('d0').textContent);
const GREEN = 0x2ee59d, RED = 0xff3b5c, CYAN = 0x39d0ff, GOLD = 0xf0b429, PURPLE = 0x7b5cff;
const $ = id => document.getElementById(id);
const money = v => Math.abs(v) < 0.005 ? '$0.00' : (v < 0 ? '-' : '+') + '$' + (Math.abs(v) >= 1000 ? Math.round(Math.abs(v)).toLocaleString() : Math.abs(v).toFixed(2));
const pct = v => (v >= 0 ? '+' : '') + v.toFixed(2) + '%';

// ---------- renderer, camera, scene ----------
const canvas = $('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
renderer.setSize(innerWidth, innerHeight);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0a0626);
scene.fog = new THREE.FogExp2(0x120a3a, 0.0065);
const camera = new THREE.PerspectiveCamera(60, innerWidth / innerHeight, 0.5, 900);
const HOME = new THREE.Vector3();
function fitHome() {
  camera.fov = innerWidth < innerHeight ? 68 : 55; camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix();
  const half = Math.atan(Math.tan(camera.fov * Math.PI / 360) * camera.aspect);
  const d = Math.min(150, Math.max(50, 31 / Math.tan(half) * 0.84));
  HOME.set(0, d * 0.70, d * 0.70 - 5);
}
fitHome(); camera.position.copy(HOME);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true; controls.dampingFactor = 0.08;
controls.maxPolarAngle = Math.PI * 0.46; controls.minDistance = 14; controls.maxDistance = 190;
controls.autoRotate = true; controls.autoRotateSpeed = 0.35; controls.target.set(0, 3, -5);
controls.addEventListener('start', () => { controls.autoRotate = false; clearTimeout(window._ar);
  window._ar = setTimeout(() => controls.autoRotate = true, 15000); });
scene.add(new THREE.HemisphereLight(0x8a7bff, 0x10082a, 0.9));
const sun = new THREE.DirectionalLight(0xc8b8ff, 0.6); sun.position.set(30, 80, 20); scene.add(sun);

const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(innerWidth / 2, innerHeight / 2), 0.95, 0.55, 0.12);
composer.addPass(bloom); composer.addPass(new OutputPass());
let glow = true;
try { if (localStorage.getItem('cityGlow') === '0') glow = false; } catch (e) {}
const setGlow = v => { glow = v; $('glow').classList.toggle('on', v); try { localStorage.setItem('cityGlow', v ? '1' : '0'); } catch (e) {} };
setGlow(glow);

// ---------- window texture for buildings ----------
function windows(seed) {
  const c = document.createElement('canvas'); c.width = 32; c.height = 64;
  const g = c.getContext('2d'); g.fillStyle = '#000'; g.fillRect(0, 0, 32, 64);
  let s = seed;
  const rnd = () => (s = (s * 9301 + 49297) % 233280) / 233280;
  for (let y = 2; y < 62; y += 4) for (let x = 2; x < 30; x += 5)
    if (rnd() < 0.42) { const b = 150 + rnd() * 105; g.fillStyle = `rgb(${b},${b},${255})`; g.fillRect(x, y, 3, 2); }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.magFilter = THREE.NearestFilter;
  return t;
}
const winTex = windows(7), winTex2 = windows(31);

// ---------- ground: grid, rings ----------
const ground = new THREE.Mesh(new THREE.CircleGeometry(420, 64), new THREE.MeshStandardMaterial({ color: 0x0b0724, roughness: 1 }));
ground.rotation.x = -Math.PI / 2; scene.add(ground);
const grid = new THREE.GridHelper(420, 105, 0x3b2a8a, 0x22184f); grid.position.y = 0.02;
grid.material.transparent = true; grid.material.opacity = 0.35; scene.add(grid);
function ring(r, w, color, op, y) {
  const m = new THREE.Mesh(new THREE.RingGeometry(r - w, r, 128),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: op, side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false }));
  m.rotation.x = -Math.PI / 2; m.position.y = y || 0.05; scene.add(m); return m;
}
ring(34, 0.25, 0x6d5cff, 0.55); ring(36, 0.08, 0x9a8cff, 0.4); ring(12, 0.18, GOLD, 0.6); ring(13.2, 0.05, GOLD, 0.35);

// ---------- background city (instanced) ----------
(function () {
  const N = 900, geo = new THREE.BoxGeometry(1, 1, 1); geo.translate(0, 0.5, 0);
  const mats = [winTex, winTex2].map(t => new THREE.MeshStandardMaterial({ color: 0x1a1240, emissive: 0x9b7bff,
    emissiveMap: t, emissiveIntensity: 1.1, roughness: 0.8 }));
  const meshes = mats.map(m => new THREE.InstancedMesh(geo, m, N / 2));
  const o = new THREE.Object3D(); let s = 3;
  const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
  for (let i = 0; i < N; i++) {
    const a = rnd() * Math.PI * 2, r = 48 + Math.pow(rnd(), 0.7) * 150;
    const h = 2 + Math.pow(rnd(), 2.2) * (r < 80 ? 10 : 26);
    o.position.set(Math.cos(a) * r, 0, Math.sin(a) * r);
    o.scale.set(2 + rnd() * 3, h, 2 + rnd() * 3); o.rotation.y = rnd() * Math.PI; o.updateMatrix();
    meshes[i % 2].setMatrixAt(i >> 1, o.matrix);
  }
  meshes.forEach(m => scene.add(m));
})();

// ---------- the Vault ----------
const vault = new THREE.Group(); scene.add(vault);
const dome = new THREE.Mesh(new THREE.SphereGeometry(4.2, 48, 24, 0, Math.PI * 2, 0, Math.PI / 2),
  new THREE.MeshStandardMaterial({ color: 0x2a1a05, emissive: GOLD, emissiveIntensity: 0.55, roughness: 0.3, metalness: 0.6 }));
vault.add(dome);
const base = new THREE.Mesh(new THREE.CylinderGeometry(5.6, 6.2, 0.8, 48),
  new THREE.MeshStandardMaterial({ color: 0x140c2c, emissive: 0x3b2a8a, emissiveIntensity: 0.6 }));
base.position.y = 0.4; vault.add(base); dome.position.y = 0.8;
function beamMesh(color, h, r, op) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, 16, 1, true),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: op, blending: THREE.AdditiveBlending, depthWrite: false }));
  m.position.y = h / 2; return m;
}
const vaultBeam = beamMesh(GOLD, 160, 0.35, 0.55); vault.add(vaultBeam);
vault.add(beamMesh(0xffffff, 160, 0.12, 0.8));

// ---------- districts ----------
const R = 22, districts = [];
function hexOf(v) { return '#' + v.toString(16).padStart(6, '0'); }
D.sleeves.forEach((s, i) => {
  const a = -Math.PI / 2 + i / D.sleeves.length * Math.PI * 2;
  const g = new THREE.Group(); g.position.set(Math.cos(a) * R, 0, Math.sin(a) * R); scene.add(g);
  const pad = new THREE.Mesh(new THREE.CircleGeometry(6.2, 48), new THREE.MeshBasicMaterial({ color: GREEN,
    transparent: true, opacity: 0.12, blending: THREE.AdditiveBlending, depthWrite: false }));
  pad.rotation.x = -Math.PI / 2; pad.position.y = 0.06; g.add(pad);
  const edge = new THREE.Mesh(new THREE.RingGeometry(6.0, 6.5, 64), new THREE.MeshBasicMaterial({ color: GREEN,
    transparent: true, opacity: 0.85, blending: THREE.AdditiveBlending, side: THREE.DoubleSide, depthWrite: false }));
  edge.rotation.x = -Math.PI / 2; edge.position.y = 0.08; g.add(edge);
  const beam = beamMesh(GREEN, 120, 0.22, 0.45); g.add(beam);
  const lbl = document.createElement('div'); lbl.className = 'lbl'; document.body.appendChild(lbl);
  districts.push({ s, g, pad, edge, beam, lbl, angle: a, buildings: {} });
});
const bGeo = new THREE.BoxGeometry(1, 1, 1); bGeo.translate(0, 0.5, 0);
function layout(d) {
  const pos = d.s.pos, n = pos.length, maxCost = Math.max(...D.sleeves.flatMap(s => s.pos.map(p => p.cost)), 1);
  const cols = Math.ceil(Math.sqrt(Math.max(n, 1))), gap = 2.6;
  const seen = {};
  pos.forEach((p, k) => {
    seen[p.sym] = 1;
    let b = d.buildings[p.sym];
    if (!b) {
      const mat = new THREE.MeshStandardMaterial({ color: 0x120c30, emissive: GREEN, emissiveMap: k % 2 ? winTex : winTex2,
        emissiveIntensity: 1.0, roughness: 0.5, metalness: 0.3 });
      const m = new THREE.Mesh(bGeo, mat); m.userData = { sleeve: d.s.name, sym: p.sym };
      const cap = new THREE.Mesh(new THREE.BoxGeometry(1.08, 0.18, 1.08), new THREE.MeshBasicMaterial({ color: GREEN }));
      d.g.add(m); d.g.add(cap);
      b = d.buildings[p.sym] = { m, cap, flash: 0, grow: 1 };
    }
    const r = Math.floor(k / cols), c = k % cols, w = 1.7;
    const x = (c - (cols - 1) / 2) * gap, z = (r - (Math.ceil(n / cols) - 1) / 2) * gap;
    const h = 1.5 + 13 * Math.sqrt(p.cost / maxCost);
    Object.assign(b, { p, x, z, h, w });
    b.m.position.set(x, 0, z); b.cap.position.set(x, 0, z);
  });
  for (const sym in d.buildings) if (!seen[sym]) { const b = d.buildings[sym]; d.g.remove(b.m); d.g.remove(b.cap); delete d.buildings[sym]; }
}
districts.forEach(layout);

// ---------- live numbers ----------
let PX = {};
const price = p => PX[p.sym] || p.px;
function sleeveNums(d) {
  let value = 0, cost = 0;
  d.s.pos.forEach(p => { value += p.qty * price(p); cost += p.cost; });
  return { value, cost, open: value - cost, total: value - cost + d.s.realized };
}
function refresh() {
  let value = 0;
  districts.forEach(d => {
    const n = sleeveNums(d); value += n.value;
    const col = n.total > 0.005 ? GREEN : n.total < -0.005 ? RED : PURPLE;
    d.edge.material.color.setHex(col); d.pad.material.color.setHex(col); d.beam.material.color.setHex(col);
    d.lbl.innerHTML = '';
    const top = document.createElement('div');
    const b = document.createElement('b'); b.textContent = d.s.label;
    const v = document.createElement('span'); v.className = n.total > 0.005 ? 'g' : n.total < -0.005 ? 'r' : 'm';
    v.textContent = money(n.total); top.append(b, v); d.lbl.appendChild(top);
    const k = document.createElement('div'); k.className = 'm';
    k.textContent = d.s.pos.length + ' held' + (d.s.sales ? ' · ' + d.s.won + '/' + d.s.sales + ' won' : '');
    d.lbl.appendChild(k);
    for (const sym in d.buildings) {
      const bl = d.buildings[sym], p = bl.p, g = price(p) * p.qty - p.cost, r = p.cost ? g / p.cost : 0;
      const c = new THREE.Color(r >= 0 ? GREEN : RED);
      bl.m.material.emissive.copy(c); bl.cap.material.color.copy(c);
      bl.m.material.emissiveIntensity = 0.55 + Math.min(Math.abs(r) * 40, 1.4);
    }
  });
  const total = value - D.net_in, spyNow = PX.SPY || D.spy, qqqNow = PX.QQQ || D.qqq;
  const spy = spyNow ? D.spy_sh * spyNow - D.net_in : null, qqq = qqqNow ? D.qqq_sh * qqqNow - D.net_in : null;
  vaultNums = { total, value, spy, qqq };
  if (!replaying) showVault(total, spy);
  $('vs').innerHTML = '';
  [['bot', total], ['SPY', spy], ['QQQ', qqq]].forEach(([n, v], i) => {
    if (v === null) return;
    const s = document.createElement('span'); s.className = v >= 0 ? 'g' : 'r';
    s.textContent = (i ? '  ' : '') + n + ' ' + money(v); $('vs').appendChild(s);
  });
}
let vaultNums = { total: 0 };
const vlbl = document.createElement('div'); vlbl.className = 'lbl vault'; document.body.appendChild(vlbl);
function showVault(total, spy, when) {
  vlbl.innerHTML = '';
  const b = document.createElement('b'); b.textContent = 'the vault' + (when ? ' · ' + when : ' · since ' + (D.start || '').slice(5));
  const v = document.createElement('div'); v.className = 'big ' + (total >= 0 ? 'g' : 'r'); v.textContent = money(total);
  const k = document.createElement('div'); k.className = 'm';
  k.textContent = D.net_in ? pct(total / D.net_in * 100) + ' on ' + money(D.net_in).slice(1) + (spy !== null && spy !== undefined ? '  ·  SPY ' + money(spy) : '') : '';
  vlbl.append(b, v, k);
  dome.material.emissive.setHex(total >= 0 ? GOLD : 0xff5a3c);
}

// ---------- effects: beams, shockwaves, toasts ----------
const fx = [];
function worldOf(e) {
  const d = districts.find(x => x.s.name === e.sleeve); if (!d) return { d: null, v: new THREE.Vector3() };
  const b = d.buildings[e.sym];
  const v = new THREE.Vector3(b ? b.x : 0, 0, b ? b.z : 0); d.g.localToWorld(v);
  return { d, b, v };
}
function shock(v, color, size) {
  const m = new THREE.Mesh(new THREE.RingGeometry(0.85, 1, 96), new THREE.MeshBasicMaterial({ color, transparent: true,
    opacity: 0.95, side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false }));
  m.rotation.x = -Math.PI / 2; m.position.set(v.x, 0.15, v.z); scene.add(m);
  const fill = new THREE.Mesh(new THREE.CircleGeometry(1, 64), new THREE.MeshBasicMaterial({ color, transparent: true,
    opacity: 0.35, blending: THREE.AdditiveBlending, depthWrite: false }));
  fill.rotation.x = -Math.PI / 2; fill.position.set(v.x, 0.12, v.z); scene.add(fill);
  fx.push({ kind: 'ring', m, fill, t: 0, life: 2.6, size });
}
function beam(v, color) {
  const m = beamMesh(color, 140, 0.9, 0.9); m.position.x = v.x; m.position.z = v.z; m.scale.y = 0.01; scene.add(m);
  const core = beamMesh(0xffffff, 140, 0.25, 1); core.position.x = v.x; core.position.z = v.z; core.scale.y = 0.01; scene.add(core);
  fx.push({ kind: 'beam', m, core, t: 0, life: 3.2 });
}
function toast(v, text, cls) {
  const el = document.createElement('div'); el.className = 'toast ' + cls; el.textContent = text; document.body.appendChild(el);
  const slot = fx.filter(f => f.kind === 'toast' && f.t < 1.5).length % 4;      // stack toasts that land together
  fx.push({ kind: 'toast', el, v: v.clone().setY(18), t: 0, life: 4.2, slot });
}
function fire(e, quiet) {
  const { d, b, v } = worldOf(e);
  if (e.side === 'buy') {
    beam(v, CYAN); shock(v, CYAN, 7);
    if (b) { b.flash = 1; if (replaying) b.grow = Math.max(b.grow, 0.02); }
    if (!quiet) toast(v, 'BOUGHT ' + e.sym + '  $' + Math.round(e.usd).toLocaleString(), 'c');
  } else {
    const p = e.pnl || 0, stop = e.reason === 'stop';
    const col = stop || p < 0 ? RED : GREEN;
    beam(v, col); shock(v, col, stop ? 16 : 11);
    if (!quiet) toast(v, (stop ? 'STOPPED OUT ' : p > 0 ? 'PROFIT LOCKED ' : 'SOLD ') + e.sym + '  ' + money(p), stop || p < 0 ? 'r' : 'g');
  }
  if (d) d.pulse = 1;
}

// ---------- chart strip (bot vs SPY) + day bars ----------
const ch = $('ch'), cg = ch.getContext('2d');
let cursor = null;
function drawChart() {
  const w = ch.clientWidth, h = ch.clientHeight, r = Math.min(devicePixelRatio, 2);
  if (ch.width !== w * r) { ch.width = w * r; ch.height = h * r; }
  cg.setTransform(r, 0, 0, r, 0, 0); cg.clearRect(0, 0, w, h);
  const H = D.hist; if (H.length < 2) { cg.fillStyle = '#8b949e'; cg.font = '11px monospace'; cg.fillText('fills in while the market is open', 10, h / 2 + 8); return; }
  const vals = H.flatMap(p => [p[2], p[3]]).concat([0]);
  let lo = Math.min(...vals), hi = Math.max(...vals); const pad = (hi - lo) * 0.12 || 1; lo -= pad; hi += pad;
  const X = i => 6 + i / (H.length - 1) * (w - 12), Y = v => 18 + (hi - v) / (hi - lo) * (h - 24);
  cg.strokeStyle = '#30363d'; cg.setLineDash([3, 3]); cg.beginPath(); cg.moveTo(6, Y(0)); cg.lineTo(w - 6, Y(0)); cg.stroke(); cg.setLineDash([]);
  [[3, '#898781', 1.2], [2, '#3987e5', 2]].forEach(([k, col, lw]) => {
    cg.strokeStyle = col; cg.lineWidth = lw; cg.beginPath();
    H.forEach((p, i) => i ? cg.lineTo(X(i), Y(p[k])) : cg.moveTo(X(i), Y(p[k]))); cg.stroke();
  });
  const evs = D.events.filter(e => e.x !== null);
  evs.forEach(e => { const i = idxOf(e.x); cg.fillStyle = e.side === 'buy' ? '#39d0ff' : (e.pnl || 0) >= 0 && e.reason !== 'stop' ? '#2ee59d' : '#ff3b5c';
    cg.fillRect(X(i) - 1, h - 6, 2, 4); });
  if (cursor !== null) { const x = X(cursor); cg.strokeStyle = '#f0b429'; cg.lineWidth = 1.5; cg.beginPath(); cg.moveTo(x, 14); cg.lineTo(x, h - 2); cg.stroke(); }
}
function idxOf(x) {
  const H = D.hist; if (!H.length) return 0; if (x <= H[0][1]) return 0; if (x >= H[H.length - 1][1]) return H.length - 1;
  let lo = 0, hi = H.length - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (H[m][1] <= x) lo = m; else hi = m; }
  return lo + (x - H[lo][1]) / Math.max(1, H[hi][1] - H[lo][1]);
}
function drawDays() {
  const el = $('days'); el.innerHTML = '';
  if (!D.days.length) return;
  const tot = D.days.reduce((a, d) => a + d[1], 0), mx = Math.max(...D.days.map(d => Math.abs(d[1])), 0.01);
  const k = document.createElement('span'); k.className = 'm'; k.textContent = D.days.length + ' day' + (D.days.length > 1 ? 's' : '');
  const t = document.createElement('span'); t.className = 'tot ' + (tot >= 0 ? 'g' : 'r'); t.textContent = money(tot);
  const bars = document.createElement('div'); bars.className = 'bars';
  D.days.forEach(d => { const i = document.createElement('i'); i.style.height = (3 + 9 * Math.abs(d[1]) / mx) + 'px';
    i.style.background = d[1] >= 0 ? '#2ee59d' : '#ff3b5c'; i.title = d[0] + ' ' + money(d[1]); bars.appendChild(i); });
  el.append(k, t, bars); el.style.display = 'inline-flex';
}

// ---------- replay ----------
let replaying = false, rp = null;
const REPLAY_S = 30;
$('replay').onclick = () => {
  if (replaying) return stopReplay();
  if (D.hist.length < 2 && !D.events.length) return;
  replaying = true; $('replay').classList.add('on'); $('replay').textContent = '■ stop';
  const evs = D.events.filter(e => e.x !== null).map(e => ({ e, i: idxOf(e.x) })).sort((a, b) => a.i - b.i);
  districts.forEach(d => { for (const s in d.buildings) d.buildings[s].grow = 0.0; });
  const bought = new Set(evs.filter(x => x.e.side === 'buy').map(x => x.e.sleeve + '|' + x.e.sym));
  districts.forEach(d => { for (const s in d.buildings) if (!bought.has(d.s.name + '|' + s)) d.buildings[s].grow = 1; });
  rp = { t0: performance.now(), evs, k: 0, n: Math.max(D.hist.length - 1, 1) };
  controls.autoRotate = true;
};
function stopReplay() {
  replaying = false; rp = null; cursor = null; $('replay').classList.remove('on'); $('replay').textContent = '▶ replay';
  districts.forEach(d => { for (const s in d.buildings) d.buildings[s].grow = 1; }); refresh(); drawChart();
}
function stepReplay(now) {
  const f = Math.max(0, Math.min((now - rp.t0) / 1000 / REPLAY_S, 1)), i = Math.min(f * rp.n, D.hist.length ? D.hist.length - 1 : 0);
  while (rp.k < rp.evs.length && rp.evs[rp.k].i <= i) {
    const burst = rp.evs.filter((x, j) => j >= rp.k && x.i <= i).length;
    fire(rp.evs[rp.k].e, burst > 3); rp.k++;
  }
  const H = D.hist;
  if (H.length) { const a = H[Math.max(0, Math.floor(i))], b = H[Math.min(Math.ceil(i), H.length - 1)], fr = i - Math.floor(i);
    showVault(a[2] + (b[2] - a[2]) * fr, a[3] + (b[3] - a[3]) * fr, a[0].slice(5, 16)); }
  cursor = i; drawChart();
  if (f >= 1) setTimeout(stopReplay, 2500), rp.done = true;
}

// ---------- tap a building ----------
const ray = new THREE.Raycaster(), ptr = new THREE.Vector2(); let down = null;
canvas.addEventListener('pointerdown', e => down = [e.clientX, e.clientY]);
canvas.addEventListener('pointerup', e => {
  if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 8) return;
  ptr.set(e.clientX / innerWidth * 2 - 1, -(e.clientY / innerHeight) * 2 + 1); ray.setFromCamera(ptr, camera);
  const hits = ray.intersectObjects(districts.flatMap(d => Object.values(d.buildings).map(b => b.m)));
  const card = $('card');
  if (!hits.length) { card.style.display = 'none'; return; }
  const u = hits[0].object.userData, d = districts.find(x => x.s.name === u.sleeve), b = d.buildings[u.sym], p = b.p;
  const val = price(p) * p.qty, g = val - p.cost;
  card.innerHTML = '';
  const t = document.createElement('div'); t.innerHTML = '<b></b> <span class="m"></span>';
  t.firstChild.textContent = u.sym; t.lastChild.textContent = d.s.label;
  const l1 = document.createElement('div'); l1.textContent = (+p.qty.toFixed(4)) + ' shares @ $' + price(p).toFixed(2) + ' = $' + val.toFixed(2);
  const l2 = document.createElement('div'); l2.className = g >= 0 ? 'g' : 'r';
  l2.textContent = money(g) + ' (' + pct(p.cost ? g / p.cost * 100 : 0) + ') on $' + p.cost.toFixed(2);
  const a = document.createElement('a'); a.href = '/s?sym=' + encodeURIComponent(u.sym); a.textContent = 'open chart →';
  card.append(t, l1, l2, a); card.style.display = 'block';
  b.flash = 1;
});
$('glow').onclick = () => setGlow(!glow);
$('home').onclick = () => { camera.position.copy(HOME); controls.target.set(0, 3, -5); controls.autoRotate = true; };

// ---------- labels follow the 3D world ----------
const tmp = new THREE.Vector3();
let topY = 0, botY = innerHeight;
function bounds() { topY = document.querySelector('.top').getBoundingClientRect().bottom + 4;
  botY = document.querySelector('.chart').getBoundingClientRect().top - 4;
}
function place(el, v, dy, clamp) {
  tmp.copy(v).project(camera);
  let x = (tmp.x + 1) / 2 * innerWidth, y = (1 - tmp.y) / 2 * innerHeight + (dy || 0);
  const h = el.offsetHeight || 40, w = el.offsetWidth || 80;
  if (clamp) x = Math.max(w / 2 + 4, Math.min(innerWidth - w / 2 - 4, x));
  if (clamp === true) y = Math.max(topY + h, Math.min(botY, y));
  if (tmp.z > 1 || y - h < topY || y > botY || x < -w / 2 || x > innerWidth + w / 2) { el.style.visibility = 'hidden'; return; }
  el.style.visibility = 'visible';
  el.style.transform = `translate(${x}px, ${y}px) translate(-50%, -100%)`;
}

// ---------- loop ----------
const clock = new THREE.Clock(); let frames = 0, fpsT = 0, autoChecked = false;
function loop(now) {
  try { frame(now); } catch (e) { console.error('city frame', e); }
  requestAnimationFrame(loop);
}
function frame(now) {
  const dt = Math.min(clock.getDelta(), 0.1), t = clock.elapsedTime;
  controls.update();
  if (replaying && rp && !rp.done) stepReplay(now);
  dome.rotation.y += dt * 0.2; vaultBeam.material.opacity = 0.45 + Math.sin(t * 2) * 0.12;
  districts.forEach(d => {
    d.beam.material.opacity = 0.22 + Math.sin(t * 1.4 + d.angle * 3) * 0.08 + (d.pulse || 0) * 0.6;
    d.pulse = Math.max(0, (d.pulse || 0) - dt * 0.6);
    for (const s in d.buildings) {
      const b = d.buildings[s];
      const target = replaying ? b.grow : 1;
      if (replaying && b.grow > 0 && b.grow < 1) b.grow = Math.min(1, b.grow + dt * 1.2);
      const gh = Math.max(0.001, b.h * (replaying ? b.grow : target));
      b.m.scale.set(b.w, gh, b.w); b.cap.position.y = gh; b.cap.visible = gh > 0.05;
      if (b.flash > 0) { b.m.material.emissiveIntensity += b.flash * 2.5; b.flash = Math.max(0, b.flash - dt * 1.5); }
    }
    place(d.lbl, tmp.set(0, 0, 0).add(d.g.position).setY(17), 0, 'x');
  });
  place(vlbl, new THREE.Vector3(0, 9, 0), 0);
  for (let i = fx.length - 1; i >= 0; i--) {
    const f = fx[i]; f.t += dt; const k = f.t / f.life;
    if (f.kind === 'ring') { const s = 1 + k * f.size; f.m.scale.set(s, s, s); f.fill.scale.set(s, s, s);
      f.m.material.opacity = 0.95 * (1 - k); f.fill.material.opacity = 0.35 * (1 - k) * (1 - k); }
    if (f.kind === 'beam') { const up = Math.min(1, f.t * 4); f.m.scale.y = f.core.scale.y = up;
      f.m.position.y = f.core.position.y = 70 * up; f.m.material.opacity = 0.9 * (1 - k); f.core.material.opacity = 1 - k; }
    if (f.kind === 'toast') { f.v.y += dt * 2.2; place(f.el, f.v, -f.slot * 30, true); f.el.style.opacity = k > 0.75 ? (1 - k) * 4 : 1; }
    if (k >= 1) {
      if (f.m) { scene.remove(f.m); f.m.geometry.dispose(); f.m.material.dispose(); }
      if (f.fill) { scene.remove(f.fill); f.fill.geometry.dispose(); f.fill.material.dispose(); }
      if (f.core) { scene.remove(f.core); f.core.geometry.dispose(); f.core.material.dispose(); }
      if (f.el) f.el.remove();
      fx.splice(i, 1);
    }
  }
  if (glow) composer.render(); else renderer.render(scene, camera);
  frames++; fpsT += dt;
  if (!autoChecked && fpsT > 6) { autoChecked = true; if (frames / fpsT < 18 && glow) setGlow(false); }
  window.CITY_OK = true;
}

// ---------- data refresh ----------
function sessionText(s) { return !s ? 'market closed' : s === 'regular' ? 'market open' : s === 'closed' ? 'market closed' : s; }
async function pollLive() {
  try {
    const r = await fetch('/live', { cache: 'no-store' }); const d = await r.json();
    PX = Object.assign(PX, d.prices || {}); refresh();
    $('clock').innerHTML = '<span class="live"></span>'; $('clock').firstChild.textContent = 'LIVE · ' + sessionText(d.session) + (d.time ? ' · ' + String(d.time).slice(11, 19) : '');
  } catch (e) { $('clock').textContent = 'offline · last ' + (D.time || '').slice(11, 19); }
}
async function pollCity() {
  try {
    const r = await fetch('/city.json', { cache: 'no-store' }); const n = await r.json();
    const old = new Set(D.events.map(e => e.id));
    const fresh = n.events.filter(e => !old.has(e.id));
    const shape = JSON.stringify(D.sleeves.map(s => s.pos.map(p => p.sym + p.qty)));
    D = n;
    if (JSON.stringify(D.sleeves.map(s => s.pos.map(p => p.sym + p.qty))) !== shape)
      districts.forEach((d, i) => { d.s = D.sleeves[i]; layout(d); });
    else districts.forEach((d, i) => d.s = D.sleeves[i]);
    refresh(); drawChart(); drawDays();
    if (!replaying) fresh.slice(-6).forEach((e, j) => setTimeout(() => fire(e), j * 900));
  } catch (e) {}
}
addEventListener('resize', () => { renderer.setSize(innerWidth, innerHeight); composer.setSize(innerWidth, innerHeight);
  bloom.resolution.set(innerWidth / 2, innerHeight / 2); fitHome(); drawChart(); bounds(); });
refresh(); drawChart(); drawDays(); bounds(); pollLive();
setInterval(pollLive, 10000); setInterval(pollCity, 20000);
requestAnimationFrame(loop);
window.CITY = { fire, D: () => D, districts };
</script></body></html>"""
