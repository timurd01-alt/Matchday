// Matchday reels -- every frame is draw(t), a pure function of time.
//
// Layout respects TikTok's overlay: the caption, buttons and progress bar sit
// over roughly the bottom 330px and right 120px, so nothing that must be read
// is drawn there.
(function () {
  'use strict';
  const W = 1080, H = 1920;
  const BG = '#070a0f', INK = '#f3f6ef', LIME = '#defa10', MUTED = '#a3adb9',
    PANEL = '#10161d', RULE = '#29323c', WIN = '#3ad17a', LOSS = '#ff5d6c';
  const canvas = document.getElementById('reel');
  const ctx = canvas.getContext('2d');
  const images = new Map();
  let colors = {};
  let spec = null;
  let timeline = [];
  let brand = null;

  // ----------------------------------------------------------------- helpers
  const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
  const ease = (v) => 1 - Math.pow(1 - clamp(v), 3);
  const easeInOut = (v) => { v = clamp(v); return v < 0.5 ? 4 * v * v * v : 1 - Math.pow(-2 * v + 2, 3) / 2; };
  // 0 -> 1 over [start, start+len] of the scene's local time.
  const ramp = (u, start, len) => ease((u - start) / len);

  function load(src) {
    if (!images.has(src)) {
      images.set(src, new Promise((resolve) => {
        const im = new Image();
        im.onload = () => resolve(im);
        im.onerror = () => resolve(null);
        im.src = src;
      }));
    }
    return images.get(src);
  }

  function display(t, x, y, size, max, color = INK, align = 'center') {
    ctx.fillStyle = color; ctx.textAlign = align; ctx.textBaseline = 'middle';
    ctx.font = `800 ${size}px Matchday`;
    while (ctx.measureText(t).width > max && size > 12) { size--; ctx.font = `800 ${size}px Matchday`; }
    ctx.fillText(t, x, y);
  }

  function body(t, x, y, size, max, color = INK, align = 'center') {
    ctx.fillStyle = color; ctx.textAlign = align; ctx.textBaseline = 'middle';
    ctx.font = `700 ${size}px Arial`;
    while (ctx.measureText(t).width > max && size > 14) { size--; ctx.font = `700 ${size}px Arial`; }
    ctx.fillText(t, x, y);
  }

  // Wrap body copy onto at most `lines` lines inside `max` px.
  function paragraph(t, x, y, size, max, color = MUTED, lines = 3, lead = 1.35) {
    ctx.font = `700 ${size}px Arial`;
    const words = String(t || '').split(/\s+/).filter(Boolean);
    const out = [];
    let line = '';
    for (const w of words) {
      const next = line ? line + ' ' + w : w;
      if (ctx.measureText(next).width > max && line) { out.push(line); line = w; } else line = next;
    }
    if (line) out.push(line);
    if (out.length > lines) { out.length = lines; out[lines - 1] = out[lines - 1].replace(/\s*\S*$/, '') + '…'; }
    out.forEach((l, i) => body(l, x, y + i * size * lead, size, max, color));
  }

  function contain(im, x, y, w, h) {
    if (!im) return false;
    const s = Math.min(w / im.width, h / im.height);
    ctx.drawImage(im, x + (w - im.width * s) / 2, y + (h - im.height * s) / 2, im.width * s, im.height * s);
    return true;
  }

  function teamColor(team) {
    const key = String(team || '').toLowerCase().replace(/[^a-z0-9]/g, '');
    return colors[key] || '#30343b';
  }

  // A team mark, or its initials when the school has no committed artwork.
  function mark(team, name, x, y, w, h) {
    const im = team && imagesSync.get(team);
    if (contain(im, x, y, w, h)) return;
    ctx.fillStyle = '#1b232e';
    ctx.beginPath(); ctx.arc(x + w / 2, y + h / 2, Math.min(w, h) * 0.42, 0, Math.PI * 2); ctx.fill();
    const initials = String(name || '?').split(/\s+/).slice(0, 2).map((p) => p[0]).join('');
    display(initials, x + w / 2, y + h / 2 + 4, Math.min(w, h) * 0.32, w * 0.7);
  }

  function panel(team, x, y, w, h, alpha = 1) {
    ctx.save(); ctx.globalAlpha *= alpha;
    ctx.fillStyle = teamColor(team); ctx.fillRect(x, y, w, h);
    const g = ctx.createLinearGradient(x, y, x, y + h);
    g.addColorStop(0, 'rgba(0,0,0,.25)'); g.addColorStop(0.55, 'rgba(0,0,0,.52)'); g.addColorStop(1, 'rgba(0,0,0,.77)');
    ctx.fillStyle = g; ctx.fillRect(x, y, w, h);
    ctx.restore();
  }

  function rule(y, w = 960, x = 60, color = RULE) { ctx.fillStyle = color; ctx.fillRect(x, y, w, 2); }

  // ----------------------------------------------------------------- chrome
  function chrome(t) {
    ctx.fillStyle = BG; ctx.fillRect(0, 0, W, H);
    // Progress across the whole reel.
    ctx.fillStyle = RULE; ctx.fillRect(60, 96, 960, 6);
    ctx.fillStyle = LIME; ctx.fillRect(60, 96, 960 * clamp(t / spec.duration), 6);
    // Brand row.
    if (brand) {
      ctx.save(); ctx.beginPath(); ctx.arc(108, 172, 44, 0, Math.PI * 2); ctx.clip();
      ctx.drawImage(brand, 64, 128, 88, 88); ctx.restore();
    }
    display('MATCHDAY TERMINAL', 172, 174, 40, 520, INK, 'left');
    body(spec.label || '', 1020, 174, 26, 300, LIME, 'right');
    rule(238);
  }

  // Fade a scene in over its first 0.3s and out over its last 0.25s.
  function sceneAlpha(u, dur, first, last) {
    const a = first ? 1 : clamp(u / 0.3);
    const b = last ? 1 : clamp((dur - u) / 0.25);
    return Math.min(a, b);
  }

  // ----------------------------------------------------------------- scenes
  const scenes = {
    intro(s, u) {
      const a = ramp(u, 0, 0.6), b = ramp(u, 0.35, 0.6);
      ctx.save(); ctx.globalAlpha *= a;
      ctx.translate(0, (1 - a) * 40);
      if (brand) {
        ctx.save(); ctx.beginPath(); ctx.arc(540, 640, 210, 0, Math.PI * 2); ctx.clip();
        ctx.drawImage(brand, 330, 430, 420, 420); ctx.restore();
      }
      ctx.restore();
      ctx.save(); ctx.globalAlpha *= b; ctx.translate(0, (1 - b) * 30);
      display(s.title, 540, 1000, 104, 960, LIME);
      if (s.subtitle) body(s.subtitle.toUpperCase(), 540, 1100, 38, 900, INK);
      if (s.kicker) body(s.kicker, 540, 1170, 30, 900, MUTED);
      ctx.restore();
    },

    rank_batch(s, u) {
      display(s.heading, 60, 330, 72, 960, LIME, 'left');
      if (s.subheading) body(s.subheading, 62, 400, 28, 950, MUTED, 'left');
      s.rows.forEach((r, i) => {
        const p = ramp(u, 0.15 + i * 0.12, 0.45);
        const y = 460 + i * 196;
        ctx.save(); ctx.globalAlpha *= p; ctx.translate((1 - p) * 220, 0);
        ctx.fillStyle = PANEL; ctx.fillRect(60, y, 960, 176);
        ctx.fillStyle = teamColor(r.team); ctx.fillRect(60, y, 10, 176);
        display(String(r.rank), 150, y + 90, 76, 140, LIME);
        mark(r.team, r.name, 230, y + 18, 150, 140);
        display(r.name, 410, y + 72, 54, 420, INK, 'left');
        if (r.sub) body(r.sub, 412, y + 126, 28, 420, MUTED, 'left');
        if (r.value) display(r.value, 990, y + 90, 56, 200, INK, 'right');
        ctx.restore();
      });
    },

    rank_hero(s, u) {
      const p = ramp(u, 0, 0.5), q = ramp(u, 0.25, 0.5);
      panel(s.team, 60, 300, 960, 1180, 0.9 * p);
      ctx.save(); ctx.globalAlpha *= p;
      display('#' + s.rank, 120, 400, 150, 420, LIME, 'left');
      ctx.restore();
      ctx.save(); ctx.globalAlpha *= q;
      const grow = 0.85 + 0.15 * q;
      const lw = 560 * grow, lh = 470 * grow;
      mark(s.team, s.name, 540 - lw / 2, 560 + (470 - lh) / 2, lw, lh);
      display(s.name, 540, 1150, 96, 900, INK);
      if (s.value) display(s.value, 540, 1270, 64, 900, LIME);
      if (s.sub) body(s.sub, 540, 1360, 34, 900, INK);
      ctx.restore();
    },

    matchup(s, u) {
      display(s.heading, 60, 330, 64, 960, LIME, 'left');
      if (s.kickoff) body(s.kickoff, 62, 396, 30, 950, INK, 'left');
      const sides = [[s.away, 450], [s.home, 830]];
      sides.forEach(([side, y], i) => {
        const p = ramp(u, 0.1 + i * 0.15, 0.5);
        ctx.save(); ctx.globalAlpha *= p; ctx.translate((i ? 1 : -1) * (1 - p) * 200, 0);
        panel(side.team, 60, y, 960, 330);
        mark(side.team, side.name, 100, y + 30, 300, 270);
        if (side.rank) display('#' + side.rank, 440, y + 90, 48, 140, LIME, 'left');
        display(side.name, 440, y + (side.rank ? 175 : 150), 64, 540, INK, 'left');
        if (side.sub) body(side.sub, 442, y + 250, 28, 540, INK, 'left');
        ctx.restore();
      });
      const v = ramp(u, 0.35, 0.4);
      ctx.save(); ctx.globalAlpha *= v;
      ctx.fillStyle = BG; ctx.beginPath(); ctx.arc(540, 805, 56, 0, Math.PI * 2); ctx.fill();
      display(s.home_away_word || 'AT', 540, 808, 40, 90, INK);
      ctx.restore();
      if (s.pick) bars(s, u, 1215);
      if (s.note) paragraph(s.note, 540, 1500, 30, 900, MUTED, 2);
    },

    upset(s, u) {
      display(s.heading, 60, 330, 72, 960, LIME, 'left');
      if (s.kickoff) body(s.kickoff, 62, 400, 30, 950, INK, 'left');
      const p = ramp(u, 0.1, 0.5);
      ctx.save(); ctx.globalAlpha *= p; ctx.translate(0, (1 - p) * 60);
      panel(s.dog.team, 60, 450, 960, 520);
      body('THE UNDERDOG', 540, 500, 30, 900, LIME);
      mark(s.dog.team, s.dog.name, 290, 530, 500, 300);
      display(s.dog.name, 540, 900, 80, 900, INK);
      ctx.restore();
      const q = ramp(u, 0.45, 0.4);
      ctx.save(); ctx.globalAlpha *= q;
      body('vs ' + s.favorite.name.toUpperCase() + (s.favorite.rank ? ' (#' + s.favorite.rank + ')' : ''), 540, 1020, 36, 900, INK);
      ctx.restore();
      bars({ pick_name: s.dog.name, model_pct: s.model_pct, market_pct: s.market_pct }, u, 1110);
      const g = ramp(u, 1.6, 0.5);
      ctx.save(); ctx.globalAlpha *= g;
      display('+' + s.gap.toFixed(1) + ' PTS MORE THAN THE MARKET', 540, 1420, 44, 940, LIME);
      ctx.restore();
    },

    stat(s, u) {
      display(s.heading, 60, 330, 72, 960, LIME, 'left');
      if (s.subheading) body(s.subheading, 62, 400, 28, 950, MUTED, 'left');
      s.rows.forEach((r, i) => {
        const p = ramp(u, 0.2 + i * 0.35, 0.5);
        const y = 470 + i * 330;
        ctx.save(); ctx.globalAlpha *= p; ctx.translate(0, (1 - p) * 40);
        ctx.fillStyle = PANEL; ctx.fillRect(60, y, 960, 300);
        body(r.label.toUpperCase(), 100, y + 60, 30, 880, MUTED, 'left');
        display(r.value, 100, y + 160, 110, 880, r.color || INK, 'left');
        if (r.sub) body(r.sub, 100, y + 252, 30, 880, INK, 'left');
        ctx.restore();
      });
    },

    results(s, u) {
      display(s.heading, 60, 330, 72, 960, LIME, 'left');
      if (s.subheading) body(s.subheading, 62, 400, 30, 950, INK, 'left');
      s.rows.forEach((r, i) => {
        const p = ramp(u, 0.2 + i * 0.3, 0.45);
        const y = 470 + i * 260;
        ctx.save(); ctx.globalAlpha *= p; ctx.translate((1 - p) * 200, 0);
        ctx.fillStyle = PANEL; ctx.fillRect(60, y, 960, 236);
        const won = r.result === 'won';
        ctx.fillStyle = won ? WIN : LOSS; ctx.fillRect(60, y, 12, 236);
        mark(r.team, r.name, 100, y + 28, 200, 180);
        display(r.name, 330, y + 80, 56, 470, INK, 'left');
        if (r.sub) body(r.sub, 332, y + 150, 28, 470, MUTED, 'left');
        display(won ? 'HIT' : 'MISS', 990, y + 118, 60, 180, won ? WIN : LOSS, 'right');
        ctx.restore();
      });
    },

    outro(s, u) {
      const a = ramp(u, 0, 0.6), b = ramp(u, 0.3, 0.6);
      ctx.save(); ctx.globalAlpha *= a;
      display(s.headline, 540, 520, 92, 960, LIME);
      if (s.subline) body(s.subline, 540, 620, 36, 940, INK);
      ctx.restore();
      ctx.save(); ctx.globalAlpha *= b;
      if (brand) {
        ctx.save(); ctx.beginPath(); ctx.arc(540, 870, 150, 0, Math.PI * 2); ctx.clip();
        ctx.drawImage(brand, 390, 720, 300, 300); ctx.restore();
      }
      display('MATCHDAYTERMINAL.COM', 540, 1110, 64, 960, INK);
      body('Free research. Every pick graded in public.', 540, 1190, 32, 940, MUTED);
      if (s.note) paragraph(s.note, 540, 1300, 32, 880, MUTED, 3);
      ctx.restore();
    },
  };

  // Model vs market as two bars for the same side.
  function bars(s, u, y) {
    const p = easeInOut((u - 0.5) / 0.9);
    body((s.pick_label || s.pick_name || '').toUpperCase(), 540, y, 34, 940, INK);
    const rows = [['MODEL', s.model_pct, LIME], ['MARKET', s.market_pct, '#7c8794']];
    rows.forEach(([label, pct, color], i) => {
      if (typeof pct !== 'number') return;
      const yy = y + 50 + i * 90;
      body(label, 60, yy + 30, 28, 180, MUTED, 'left');
      ctx.fillStyle = PANEL; ctx.fillRect(220, yy, 640, 60);
      ctx.fillStyle = color; ctx.fillRect(220, yy, 640 * (pct / 100) * p, 60);
      display((pct * p).toFixed(1) + '%', 1020, yy + 32, 48, 150, color === LIME ? LIME : INK, 'right');
    });
  }

  // ----------------------------------------------------------------- api
  const imagesSync = new Map();

  function draw(t) {
    t = clamp(t, 0, spec.duration);
    chrome(t);
    let i = timeline.findIndex((sc) => t < sc.end);
    if (i < 0) i = timeline.length - 1;
    const sc = timeline[i];
    const u = t - sc.start;
    ctx.save();
    ctx.globalAlpha = sceneAlpha(u, sc.dur, i === 0, i === timeline.length - 1);
    scenes[sc.type](sc, u);
    ctx.restore();
  }

  window.REEL = {
    async load(next) {
      spec = next;
      let start = 0;
      timeline = spec.scenes.map((sc) => {
        if (!scenes[sc.type]) throw new Error('unknown scene ' + sc.type);
        const entry = Object.assign({}, sc, { start, end: start + sc.dur });
        start += sc.dur;
        return entry;
      });
      spec.duration = start;
      const [palette, logo] = await Promise.all([
        fetch('team-colors.json').then((r) => r.json()),
        load('brand.png'),
        document.fonts.load('800 40px Matchday'),
      ]);
      colors = Object.fromEntries(Object.entries(palette).map(([k, v]) => [k.toLowerCase().replace(/[^a-z0-9]/g, ''), v]));
      brand = logo;
      const teams = new Set();
      JSON.stringify(spec, (k, v) => { if (k === 'team' && v) teams.add(v); return v; });
      await Promise.all([...teams].map(async (team) => imagesSync.set(team, await load('logos/' + team + '.png'))));
      const missing = [...teams].filter((team) => !imagesSync.get(team));
      return { duration: spec.duration, missing };
    },
    // JPEG frames for a batch of times; JPEG keeps the browser-to-encoder hop fast.
    frames(times, quality = 0.93) {
      return times.map((t) => { draw(t); return canvas.toDataURL('image/jpeg', quality); });
    },
    draw,
  };
})();
