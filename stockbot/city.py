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
    raw = [p for p in stockbot.load("history.json", []) if float(p.get("in") or 0) > 0 and p.get("t")]
    hist = charts.dollars(raw)
    step = max(1, len(hist) // 400)
    idx = list(range(0, len(hist), step)) + ([len(hist) - 1] if hist and (len(hist) - 1) % step else [])
    keep = [hist[i] for i in idx]
    lines = {n: [raw[i].get(n) for i in idx] for n in stockbot.SLEEVES}       # each strategy's % on its own money
    days = charts.periods(hist, 10)[-10:]
    live = stockbot.load("live.json", {})
    return {"time": stockbot.stamp(), "session": live.get("session"), "net_in": round(net_in, 2),
            "spy_sh": spy_sh, "qqq_sh": qqq_sh, "spy": px.get("SPY"), "qqq": px.get("QQQ"),
            "start": led[0]["time"][:10] if led else None, "sleeves": sleeves, "events": events[-120:],
            "hist": [[p["t"], _x(p["t"]), round(p["bot"], 2), round(p["spy"], 2)] for p in keep],
            "days": [[d["key"], round(d["bot"], 2)] for d in days], "lines": lines}


def stock(sym):
    """One stock for the tap-a-building panel: ~4 months of daily closes, your fills and your levels."""
    rows = charts.bars(sym)[-90:]
    levels, marks, sleeves = charts.levels_for(sym)
    first = rows[0][0] if rows else ""
    return {"sym": sym, "sleeves": sleeves, "rows": [[r[0], round(r[4], 2)] for r in rows],
            "marks": [{"day": m["day"], "side": m["side"], "price": round(m["price"], 2), "qty": round(m["qty"], 4),
                       "sleeves": m["sleeves"]} for m in marks if m["day"] >= first],
            "levels": [[round(p, 2), label] for p, label, _ in levels if p]}


def page(tabs_html):
    """The City tab."""
    first = charts._json(data())
    return (PAGE.replace("@TABS@", tabs_html).replace("@DATA@", first).replace("@THREE@", THREE))


PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>bot city</title>
<style>
html, body { margin:0; height:100%; background:#120a5e; color:#e6edf3; overflow:hidden;
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
.panel { position:fixed; left:6px; right:6px; bottom:6px; height:46vh; min-height:250px; z-index:8; display:none;
  background:#0b0f14f5; border:1px solid #58a6ff; border-radius:12px; padding:8px 10px; box-sizing:border-box;
  font:11px/1.4 ui-monospace, Menlo, monospace; flex-direction:column; box-shadow:0 0 24px #58a6ff40; }
.panel .ph { display:flex; justify-content:space-between; align-items:flex-start; gap:8px; }
.panel .ph b { font-size:14px; letter-spacing:.05em; text-transform:uppercase; }
.panel .ph .x { font-size:18px; line-height:1; padding:2px 8px; cursor:pointer; color:#8b949e; border:1px solid #30363d;
  border-radius:6px; background:none; }
.panel .tape { min-height:16px; margin:4px 0 2px; font-weight:700; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.panel canvas { flex:1; width:100%; min-height:0; display:block; }
.panel .pf { display:flex; justify-content:space-between; align-items:center; gap:8px; margin-top:4px; color:#8b949e; }
.panel .pf a { color:#58a6ff; }
.lbl.tap { pointer-events:auto; cursor:pointer; }
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
<div class="panel" id="panel"><div class="ph"><div><b id="pt"></b> <span class="m" id="ps"></span><div id="pv"></div></div>
<button class="x" id="px">&times;</button></div><div class="tape" id="ptape"></div><canvas id="pc"></canvas>
<div class="pf"><button class="pill" id="pr">&#9654; replay</button><span id="pk"></span><a id="pl" href="#"></a></div></div>
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
const BG = 0x120a5e;
scene.background = new THREE.Color(BG);
scene.fog = new THREE.Fog(BG, 150, 380);
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
scene.add(new THREE.HemisphereLight(0xffffff, 0x3a2a90, 1.1));          // only the Vault dome is lit; the rest is flat colour
const sun = new THREE.DirectionalLight(0xffffff, 1.5); sun.position.set(30, 60, 40); scene.add(sun);

const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(innerWidth / 2, innerHeight / 2), 0.36, 0.35, 0.72);
composer.addPass(bloom); composer.addPass(new OutputPass());
let glow = true;
try { if (localStorage.getItem('cityGlow') === '0') glow = false; } catch (e) {}
const setGlow = v => { glow = v; $('glow').classList.toggle('on', v); try { localStorage.setItem('cityGlow', v ? '1' : '0'); } catch (e) {} };
setGlow(glow);

// ---------- window texture for buildings ----------
function windows(seed) {
  const c = document.createElement('canvas'); c.width = 128; c.height = 256;
  const g = c.getContext('2d'); g.fillStyle = '#0c0640'; g.fillRect(0, 0, 128, 256);
  let s = seed;
  const rnd = () => (s = (s * 9301 + 49297) % 233280) / 233280;
  for (let y = 8; y < 248; y += 32) for (let x = 8; x < 120; x += 32)
    if (rnd() < 0.55) { g.fillStyle = rnd() < 0.8 ? '#ffffff' : '#bfd0ff'; g.fillRect(x, y, 18, 14); }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  t.wrapS = t.wrapT = THREE.RepeatWrapping; t.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
  return t;
}
const winTex = windows(7), winTex2 = windows(31);
function tall(tex, rows) { const t = tex.clone(); t.repeat.set(1, rows); t.needsUpdate = true; return t; }
// light that fades out as it goes up, for beams
const fadeTex = (() => { const c = document.createElement('canvas'); c.width = 4; c.height = 128; const g = c.getContext('2d');
  const gr = g.createLinearGradient(0, 128, 0, 0); gr.addColorStop(0, '#ffffff'); gr.addColorStop(0.35, '#9a9a9a'); gr.addColorStop(1, '#000000');
  g.fillStyle = gr; g.fillRect(0, 0, 4, 128); return new THREE.CanvasTexture(c); })();

// ---------- ground: grid, rings ----------
const ground = new THREE.Mesh(new THREE.CircleGeometry(420, 64), new THREE.MeshBasicMaterial({ color: 0x180c78 }));
ground.rotation.x = -Math.PI / 2; scene.add(ground);
const grid = new THREE.GridHelper(420, 105, 0x3a2bd0, 0x2a1ca6); grid.position.y = 0.02;
grid.material.transparent = true; grid.material.opacity = 0.45; scene.add(grid);
function ring(r, w, color, op, y) {
  const m = new THREE.Mesh(new THREE.RingGeometry(r - w, r, 128),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: op, side: THREE.DoubleSide, depthWrite: false }));
  m.rotation.x = -Math.PI / 2; m.position.y = y || 0.05; scene.add(m); return m;
}
ring(33.5, 0.2, 0xdcd6ff, 0.6); ring(11.4, 0.2, GOLD, 0.9); ring(12.6, 0.1, GOLD, 0.4);
// little lights that run round the outer ring
const traffic = new THREE.Group(); scene.add(traffic);
(function () {
  const geo = new THREE.BoxGeometry(1.3, 0.1, 0.34), mat = new THREE.MeshBasicMaterial({ color: 0xffffff });
  for (let i = 0; i < 22; i++) { const a = i / 22 * Math.PI * 2 + (i % 3) * 0.05, m = new THREE.Mesh(geo, mat);
    m.position.set(Math.cos(a) * 33.4, 0.12, Math.sin(a) * 33.4); m.rotation.y = -a + Math.PI / 2; traffic.add(m); }
})();

// ---------- background city (instanced) ----------
(function () {
  const N = 900, geo = new THREE.BoxGeometry(1, 1, 1); geo.translate(0, 0.5, 0);
  const o = new THREE.Object3D(); let s = 3;
  const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
  const buckets = [[], [], []];
  for (let i = 0; i < N; i++) {
    const a = rnd() * Math.PI * 2, r = 56 + Math.pow(rnd(), 0.7) * 150;
    const h = 2 + Math.pow(rnd(), 2.2) * (r < 80 ? 10 : 26);
    o.position.set(Math.cos(a) * r, 0, Math.sin(a) * r);
    o.scale.set(2 + rnd() * 3, h, 2 + rnd() * 3); o.rotation.y = rnd() * Math.PI; o.updateMatrix();
    buckets[h < 6 ? 0 : h < 14 ? 1 : 2].push(o.matrix.clone());
  }
  buckets.forEach((list, k) => {
    if (!list.length) return;
    const m = new THREE.InstancedMesh(geo, new THREE.MeshBasicMaterial({ color: 0x6f66cf, map: tall(k % 2 ? winTex : winTex2, [1, 2, 4][k]) }), list.length);
    list.forEach((mx, i) => m.setMatrixAt(i, mx)); scene.add(m);
  });
})();

// ---------- the Vault ----------
const vault = new THREE.Group(); scene.add(vault);
const dome = new THREE.Mesh(new THREE.SphereGeometry(3.9, 48, 24, 0, Math.PI * 2, 0, Math.PI / 2),
  new THREE.MeshStandardMaterial({ color: 0xf2b84a, emissive: 0x553400, roughness: 0.42, metalness: 0.15 }));
vault.add(dome);
const base = new THREE.Mesh(new THREE.CylinderGeometry(6.0, 6.3, 0.5, 64), new THREE.MeshBasicMaterial({ color: 0x2c1cc0 }));
base.position.y = 0.25; vault.add(base);
const stripes = (() => { const c = document.createElement('canvas'); c.width = 256; c.height = 8; const g = c.getContext('2d');
  for (let i = 0; i < 32; i++) { g.fillStyle = i % 2 ? '#7a1f1a' : '#f5c95e'; g.fillRect(i * 8, 0, 8, 8); }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.magFilter = THREE.NearestFilter; return t; })();
const drum = new THREE.Mesh(new THREE.CylinderGeometry(4.1, 4.1, 1.7, 48, 1, true), new THREE.MeshBasicMaterial({ map: stripes }));
drum.position.y = 0.5 + 0.85; vault.add(drum);
const lip = new THREE.Mesh(new THREE.CylinderGeometry(4.35, 4.35, 0.22, 48), new THREE.MeshBasicMaterial({ color: 0xffe9a8 }));
lip.position.y = 2.2; vault.add(lip); dome.position.y = 2.3;
function beamMesh(color, h, r, op) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, 16, 1, true),
    new THREE.MeshBasicMaterial({ color, map: fadeTex, transparent: true, opacity: op, blending: THREE.AdditiveBlending, depthWrite: false }));
  m.position.y = h / 2; return m;
}
const vaultBeam = beamMesh(GOLD, 150, 0.42, 0.34); vaultBeam.position.y += 6; vault.add(vaultBeam);
const vaultCore = beamMesh(0xfff4d0, 150, 0.09, 0.9); vaultCore.position.y += 6; vault.add(vaultCore);

// ---------- districts ----------
const R = 22, districts = [];
function hexOf(v) { return '#' + v.toString(16).padStart(6, '0'); }
D.sleeves.forEach((s, i) => {
  const a = -Math.PI / 2 + i / D.sleeves.length * Math.PI * 2;
  const g = new THREE.Group(); g.position.set(Math.cos(a) * R, 0, Math.sin(a) * R); scene.add(g);
  const pad = new THREE.Mesh(new THREE.CircleGeometry(6.6, 64), new THREE.MeshBasicMaterial({ color: 0x22139a }));
  pad.rotation.x = -Math.PI / 2; pad.position.y = 0.04; g.add(pad);
  const edge = new THREE.Mesh(new THREE.RingGeometry(6.38, 6.6, 96), new THREE.MeshBasicMaterial({ color: GREEN,
    side: THREE.DoubleSide }));
  edge.rotation.x = -Math.PI / 2; edge.position.y = 0.07; g.add(edge);
  const beam = beamMesh(GREEN, 60, 0.3, 0); beam.visible = false; g.add(beam);
  const lbl = document.createElement('div'); lbl.className = 'lbl tap'; document.body.appendChild(lbl);
  pad.userData = { district: s.name };
  const dd = { s, g, pad, edge, beam, lbl, angle: a, buildings: {} };
  lbl.addEventListener('click', () => openSleeve(dd));
  districts.push(dd);
});
const bGeo = new THREE.BoxGeometry(1, 1, 1); bGeo.translate(0, 0.5, 0);
const edgeGeo = new THREE.EdgesGeometry(bGeo);
function layout(d) {
  const pos = d.s.pos, n = pos.length, maxCost = Math.max(...D.sleeves.flatMap(s => s.pos.map(p => p.cost)), 1);
  const cols = Math.ceil(Math.sqrt(Math.max(n, 1))), gap = 2.6;
  const seen = {};
  pos.forEach((p, k) => {
    seen[p.sym] = 1;
    let b = d.buildings[p.sym];
    if (!b) {
      const mat = new THREE.MeshBasicMaterial({ map: tall(k % 2 ? winTex : winTex2, 1) });
      const m = new THREE.Mesh(bGeo, mat); m.userData = { sleeve: d.s.name, sym: p.sym };
      const cap = new THREE.Mesh(new THREE.BoxGeometry(1.05, 0.22, 1.05), new THREE.MeshBasicMaterial({ color: GREEN }));
      const edges = new THREE.LineSegments(edgeGeo, new THREE.LineBasicMaterial({ color: GREEN, transparent: true, opacity: 0.9 }));
      m.add(edges); d.g.add(m); d.g.add(cap);
      b = d.buildings[p.sym] = { m, cap, edges, flash: 0, grow: 1, base: new THREE.Color(0xffffff) };
    }
    const r = Math.floor(k / cols), c = k % cols, w = 1.7;
    const x = (c - (cols - 1) / 2) * gap, z = (r - (Math.ceil(n / cols) - 1) / 2) * gap;
    const h = 1.5 + 13 * Math.sqrt(p.cost / maxCost);
    Object.assign(b, { p, x, z, h, w });
    b.m.material.map.repeat.set(1, Math.max(1, Math.round(h / 4.5)));
    b.m.position.set(x, 0, z); b.cap.position.set(x, 0, z); b.cap.scale.set(w, 1, w);
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
    const col = n.total > 0.005 ? GREEN : n.total < -0.005 ? RED : 0xbdb2ff;
    d.edge.material.color.setHex(col); d.beam.material.color.setHex(col);
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
      bl.cap.material.color.copy(c); bl.edges.material.color.copy(c);
      bl.base.setHex(0xffffff).lerp(c, 0.22); bl.m.material.color.copy(bl.base);
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
  dome.material.color.setHex(total >= 0 ? 0xf2b84a : 0xff6a4c); dome.material.emissive.setHex(total >= 0 ? 0x553400 : 0x5a1408);
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
  const m = new THREE.Mesh(new THREE.RingGeometry(0.93, 1, 96), new THREE.MeshBasicMaterial({ color, transparent: true,
    opacity: 0.9, side: THREE.DoubleSide, depthWrite: false }));
  m.rotation.x = -Math.PI / 2; m.position.set(v.x, 0.15, v.z); scene.add(m);
  const fill = new THREE.Mesh(new THREE.CircleGeometry(1, 64), new THREE.MeshBasicMaterial({ color, transparent: true,
    opacity: 0.14, blending: THREE.AdditiveBlending, depthWrite: false }));
  fill.rotation.x = -Math.PI / 2; fill.position.set(v.x, 0.12, v.z); scene.add(fill);
  fx.push({ kind: 'ring', m, fill, t: 0, life: 2.6, size });
}
function beam(v, color) {
  const m = beamMesh(color, 140, 0.32, 0.5); m.position.x = v.x; m.position.z = v.z; m.scale.y = 0.01; scene.add(m);
  const core = beamMesh(0xffffff, 140, 0.09, 0.9); core.position.x = v.x; core.position.z = v.z; core.scale.y = 0.01; scene.add(core);
  fx.push({ kind: 'beam', m, core, t: 0, life: 3.2 });
}
function toast(v, text, cls) {
  const el = document.createElement('div'); el.className = 'toast ' + cls; el.textContent = text; document.body.appendChild(el);
  fx.push({ kind: 'toast', el, v: v.clone().setY(18), t: 0, life: 4.2 });
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
  const hits = ray.intersectObjects(districts.flatMap(d => Object.values(d.buildings).map(b => b.m)), false);
  if (hits.length) {
    const u = hits[0].object.userData, d = districts.find(x => x.s.name === u.sleeve);
    d.buildings[u.sym].flash = 1; return openStock(d, u.sym);
  }
  const pads = ray.intersectObjects(districts.map(d => d.pad));
  if (pads.length) return openSleeve(districts.find(d => d.s.name === pads[0].object.userData.district));
  closePanel();
});

// ---------- the panel: watch a strategy (or one stock) trade ----------
const P = { open: false, kind: null, pts: [], marks: [], levels: [], t0: 0, prog: 1, unit: '%' };
const pc = $('pc'), pg = pc.getContext('2d');
let fly = null;
function flyTo(pos, target) { fly = { p0: camera.position.clone(), t0: controls.target.clone(), p1: pos, t1: target, t: 0 }; controls.autoRotate = false; clearTimeout(window._ar); }
function focus(d) {
  const o = d.g.position, out = o.clone().setY(0).normalize();
  flyTo(new THREE.Vector3(o.x + out.x * 20, 26, o.z + out.z * 20 + 4), new THREE.Vector3(o.x, -6, o.z));
}
function showPanel() { P.open = true; $('panel').style.display = 'flex'; $('card').style.display = 'none';
  document.querySelector('.chart').style.display = 'none'; bounds(); playPanel(); }
function closePanel() {
  if (!P.open) return; P.open = false; $('panel').style.display = 'none'; document.querySelector('.chart').style.display = 'block';
  bounds(); drawChart(); flyTo(HOME.clone(), new THREE.Vector3(0, 3, -5)); setTimeout(() => { if (!P.open) controls.autoRotate = true; }, 1500);
}
function playPanel() { P.t0 = performance.now(); P.prog = 0; P.last = -1; $('ptape').textContent = ''; }
$('px').onclick = closePanel; $('pr').onclick = playPanel;
function evText(e) {
  if (e.side === 'buy') return ['▲ BOUGHT ' + e.sym + '  $' + Math.round(e.usd).toLocaleString(), 'c'];
  const p = e.pnl || 0, stop = e.reason === 'stop';
  return ['▼ ' + (stop ? 'STOPPED OUT ' : p > 0 ? 'PROFIT LOCKED ' : 'SOLD ') + e.sym + '  ' + money(p), stop || p < 0 ? 'r' : 'g'];
}
function openSleeve(d) {
  const line = (D.lines || {})[d.s.name] || [], H = D.hist;
  P.kind = 'sleeve'; P.unit = '%'; P.levels = [];
  P.pts = []; H.forEach((h, i) => { if (line[i] !== null && line[i] !== undefined) P.pts.push({ x: i, v: line[i], t: h[0].slice(5, 16) }); });
  const evs = D.events.filter(e => e.sleeve === d.s.name && e.x !== null);
  P.marks = evs.map(e => { const [text, cls] = evText(e); return { x: idxOf(e.x), side: e.side, cls, text: e.t.slice(5, 16) + '  ' + text }; });
  const n = sleeveNums(d);
  $('pt').textContent = d.s.label; $('ps').textContent = 'bot trading · ' + evs.length + ' trade' + (evs.length === 1 ? '' : 's');
  $('pv').className = n.total > 0.005 ? 'g' : n.total < -0.005 ? 'r' : 'm';
  $('pv').textContent = money(n.total) + ' total · banked ' + money(d.s.realized) + ' · open ' + money(n.open);
  $('pk').textContent = d.s.pos.length ? d.s.pos.map(p => p.sym).join(' ') : 'holding nothing, waiting for a setup';
  $('pl').textContent = ''; $('pl').removeAttribute('href');
  focus(d); showPanel();
}
async function openStock(d, sym) {
  const p = d.buildings[sym].p, val = price(p) * p.qty, g = val - p.cost;
  P.kind = 'stock'; P.unit = '$'; P.pts = []; P.marks = []; P.levels = [];
  $('pt').textContent = sym; $('ps').textContent = d.s.label + ' · loading';
  $('pv').className = g >= 0 ? 'g' : 'r';
  $('pv').textContent = money(g) + ' (' + pct(p.cost ? g / p.cost * 100 : 0) + ') · ' + (+p.qty.toFixed(3)) + ' sh @ $' + price(p).toFixed(2);
  $('pk').textContent = 'daily closes, about 4 months'; $('pl').textContent = 'full chart →'; $('pl').href = '/s?sym=' + encodeURIComponent(sym);
  focus(d); showPanel();
  try {
    const r = await fetch('/city.json?sym=' + encodeURIComponent(sym), { cache: 'no-store' }); const k = await r.json();
    if (!P.open || $('pt').textContent !== sym) return;
    P.pts = k.rows.map((row, i) => ({ x: i, v: row[1], t: row[0].slice(5) }));
    if (P.pts.length && PX[sym]) P.pts[P.pts.length - 1].v = PX[sym];
    P.marks = k.marks.map(m => { let i = k.rows.findIndex(row => row[0] >= m.day); if (i < 0) i = k.rows.length - 1;
      return { x: i, side: m.side, v: m.price, cls: m.side === 'buy' ? 'c' : 'g',
        text: m.day.slice(5) + '  ' + (m.side === 'buy' ? '▲ BOUGHT ' : '▼ SOLD ') + (+m.qty.toFixed(3)) + ' @ $' + m.price.toFixed(2) + ' (' + m.sleeves.join(', ') + ')' }; });
    P.levels = k.levels;
    $('ps').textContent = d.s.label + ' · ' + P.marks.length + ' trade' + (P.marks.length === 1 ? '' : 's') + ' on this chart';
    playPanel();
  } catch (e) { $('ps').textContent = d.s.label + ' · chart not available'; }
}
function drawPanel(now) {
  const w = pc.clientWidth, h = pc.clientHeight, r = Math.min(devicePixelRatio, 2);
  if (!w || !h) return;
  if (pc.width !== Math.round(w * r) || pc.height !== Math.round(h * r)) { pc.width = Math.round(w * r); pc.height = Math.round(h * r); }
  pg.setTransform(r, 0, 0, r, 0, 0); pg.clearRect(0, 0, w, h); pg.font = '10px ui-monospace, Menlo, monospace';
  const pts = P.pts;
  if (pts.length < 2) { pg.fillStyle = '#8b949e'; pg.fillText(P.kind === 'stock' ? 'loading the chart' : 'no history for this strategy yet', 8, h / 2); return; }
  P.prog = Math.max(0, Math.min(1, (now - P.t0) / 6000));
  const x0 = pts[0].x, x1 = pts[pts.length - 1].x, vals = pts.map(p => p.v).concat(P.marks.filter(m => m.v).map(m => m.v))
    .concat(P.unit === '%' ? [0] : P.levels.map(l => l[0]).filter(v => v > Math.min(...pts.map(p => p.v)) * 0.9 && v < Math.max(...pts.map(p => p.v)) * 1.1));
  let lo = Math.min(...vals), hi = Math.max(...vals); const pad = (hi - lo) * 0.12 || 1; lo -= pad; hi += pad;
  const R = 52, X = x => 4 + (Math.min(Math.max(x, x0), x1) - x0) / Math.max(1e-9, x1 - x0) * (w - R - 8), Y = v => 6 + (hi - v) / (hi - lo) * (h - 22);
  const fmt = v => P.unit === '%' ? pct(v) : '$' + v.toFixed(2);
  pg.strokeStyle = '#1f2630'; pg.fillStyle = '#7d8590'; pg.lineWidth = 1;
  for (let k = 0; k <= 3; k++) { const v = lo + (hi - lo) * k / 3, y = Y(v); pg.beginPath(); pg.moveTo(4, y); pg.lineTo(w - R, y); pg.stroke(); pg.fillText(fmt(v), w - R + 4, y + 3); }
  if (P.unit === '%') { pg.strokeStyle = '#3d444d'; pg.beginPath(); pg.moveTo(4, Y(0)); pg.lineTo(w - R, Y(0)); pg.stroke(); }
  P.levels.forEach(([v, label]) => { if (v <= lo || v >= hi) return; pg.strokeStyle = label === 'stop' ? '#ff3b5c' : label === 'tgt' ? '#2ee59d' : '#8b949e';
    pg.setLineDash([4, 3]); pg.beginPath(); pg.moveTo(4, Y(v)); pg.lineTo(w - R, Y(v)); pg.stroke(); pg.setLineDash([]);
    pg.fillStyle = pg.strokeStyle; pg.fillText(label, 6, Y(v) - 3); });
  pg.fillStyle = '#7d8590'; pg.fillText(pts[0].t, 4, h - 3); const tl = pts[pts.length - 1].t; pg.fillText(tl, w - R - pg.measureText(tl).width, h - 3);
  const cur = x0 + (x1 - x0) * P.prog; let last = pts[0];
  const up = pts[pts.length - 1].v >= pts[0].v;
  pg.strokeStyle = P.unit === '%' ? '#3987e5' : up ? '#2ee59d' : '#ff3b5c'; pg.lineWidth = 2; pg.lineJoin = 'round'; pg.beginPath();
  for (let i = 0; i < pts.length; i++) {
    const p = pts[i];
    if (p.x <= cur || i === 0) { i ? pg.lineTo(X(p.x), Y(p.v)) : pg.moveTo(X(p.x), Y(p.v)); last = p; }
    else { const q = pts[i - 1], f = (cur - q.x) / Math.max(1e-9, p.x - q.x); last = { x: cur, v: q.v + (p.v - q.v) * f, t: q.t }; pg.lineTo(X(cur), Y(last.v)); break; }
  }
  pg.stroke();
  let shown = -1;
  P.marks.forEach((m, i) => {
    if (m.x > cur && P.prog < 1) return; shown = i;
    const x = X(m.x), near = pts.reduce((a, p) => Math.abs(p.x - m.x) < Math.abs(a.x - m.x) ? p : a, pts[0]), y = Y(m.v || near.v);
    const col = m.cls === 'c' ? '#39d0ff' : m.cls === 'g' ? '#2ee59d' : '#ff3b5c', dir = m.side === 'buy' ? 1 : -1;
    pg.fillStyle = col; pg.strokeStyle = '#0b0f14'; pg.lineWidth = 1.5; pg.beginPath();
    pg.moveTo(x, y + dir * 5); pg.lineTo(x - 5, y + dir * 14); pg.lineTo(x + 5, y + dir * 14); pg.closePath(); pg.fill(); pg.stroke();
  });
  if (shown !== P.last && shown >= 0) { P.last = shown; const m = P.marks[shown]; const tp = $('ptape'); tp.className = 'tape ' + m.cls; tp.textContent = m.text; }
  const cx = X(last.x), cy = Y(last.v);
  pg.fillStyle = '#e6edf3'; pg.beginPath(); pg.arc(cx, cy, 3.5, 0, 7); pg.fill();
  pg.fillStyle = '#0b0f14'; pg.fillRect(w - R + 1, cy - 8, R - 2, 16); pg.fillStyle = '#e6edf3'; pg.font = 'bold 10px ui-monospace, Menlo, monospace'; pg.fillText(fmt(last.v), w - R + 4, cy + 3);
}
$('glow').onclick = () => setGlow(!glow);
$('home').onclick = () => { if (P.open) return closePanel(); fly = null; camera.position.copy(HOME); controls.target.set(0, 3, -5); controls.autoRotate = true; };

// ---------- labels follow the 3D world ----------
const tmp = new THREE.Vector3();
let topY = 0, botY = innerHeight;
function bounds() { topY = document.querySelector('.top').getBoundingClientRect().bottom + 4;
  botY = (P.open ? $('panel') : document.querySelector('.chart')).getBoundingClientRect().top - 4;
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

// toasts that land together stack upwards instead of sitting on top of each other
const placed = [];
function placeToast(el, v) {
  tmp.copy(v).project(camera);
  const w = el.offsetWidth || 130, h = el.offsetHeight || 24;
  const x = Math.max(w / 2 + 4, Math.min(innerWidth - w / 2 - 4, (tmp.x + 1) / 2 * innerWidth));
  let y = Math.max(topY + h, Math.min(botY, (1 - tmp.y) / 2 * innerHeight));
  for (let n = 0; n < 14; n++) {
    const hit = placed.find(r => Math.abs(r.x - x) < (r.w + w) / 2 + 6 && y > r.y - r.h - 4 && y - h < r.y + 4);
    if (!hit) break; y = hit.y - hit.h - 5;
  }
  if (tmp.z > 1 || y - h < topY) { el.style.visibility = 'hidden'; return; }
  placed.push({ x, y, w, h }); el.style.visibility = 'visible';
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
  if (fly) { fly.t = Math.min(1, fly.t + dt / 0.9); const k = fly.t * fly.t * (3 - 2 * fly.t);
    camera.position.lerpVectors(fly.p0, fly.p1, k); controls.target.lerpVectors(fly.t0, fly.t1, k); if (fly.t >= 1) fly = null; }
  controls.update();
  if (replaying && rp && !rp.done) stepReplay(now);
  if (P.open) drawPanel(now);
  traffic.rotation.y -= dt * 0.12; vaultBeam.material.opacity = 0.3 + Math.sin(t * 2) * 0.06; placed.length = 0;
  districts.forEach(d => {
    d.beam.material.opacity = (d.pulse || 0) * 0.45; d.beam.visible = d.pulse > 0.01;
    d.pulse = Math.max(0, (d.pulse || 0) - dt * 0.6);
    for (const s in d.buildings) {
      const b = d.buildings[s];
      const target = replaying ? b.grow : 1;
      if (replaying && b.grow > 0 && b.grow < 1) b.grow = Math.min(1, b.grow + dt * 1.2);
      const gh = Math.max(0.001, b.h * (replaying ? b.grow : target));
      b.m.scale.set(b.w, gh, b.w); b.cap.position.y = gh; b.cap.visible = gh > 0.05;
      if (b.flash > 0) { b.flash = Math.max(0, b.flash - dt * 1.5); b.m.material.color.copy(b.base).multiplyScalar(1 + b.flash * 1.6); }
    }
    place(d.lbl, tmp.set(0, 0, 0).add(d.g.position).setY(17), 0, 'x');
  });
  place(vlbl, new THREE.Vector3(0, 9, 0), 0);
  for (let i = fx.length - 1; i >= 0; i--) {
    const f = fx[i]; f.t += dt; const k = f.t / f.life;
    if (f.kind === 'ring') { const s = 1 + k * f.size; f.m.scale.set(s, s, s); f.fill.scale.set(s, s, s);
      f.m.material.opacity = 0.9 * (1 - k); f.fill.material.opacity = 0.14 * (1 - k) * (1 - k); }
    if (f.kind === 'beam') { const up = Math.min(1, f.t * 4); f.m.scale.y = f.core.scale.y = up;
      f.m.position.y = f.core.position.y = 70 * up; f.m.material.opacity = 0.5 * (1 - k); f.core.material.opacity = 0.9 * (1 - k); }
    if (f.kind === 'toast') { f.v.y += dt * 2.2; placeToast(f.el, f.v); f.el.style.opacity = k > 0.75 ? (1 - k) * 4 : 1; }
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
window.CITY = { fire, D: () => D, districts, openSleeve, openStock, closePanel, P };
</script></body></html>"""
