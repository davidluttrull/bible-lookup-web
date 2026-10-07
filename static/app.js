"use strict";

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const CHEV = '<svg class="chev" viewBox="0 0 20 20" aria-hidden="true"><path d="M5 7.5l5 5 5-5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';

let CONFIG = null;
let T_BY_ID = {};
let RENDER_ID = 0;       // bumps on every navigation; stale page loads are dropped
let CHAPTER_NAV = null;  // {prev, next} URLs for the arrow keys on single-passage pages

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch { return null; }
}

function currentTranslation() {
  const p = new URLSearchParams(location.search).get("t");
  const saved = store("bl.t");
  for (const t of [p, saved, CONFIG.default]) if (t && T_BY_ID[t.toUpperCase()]) return t.toUpperCase();
  return CONFIG.translations[0].id;
}

function urlFor({ q, t, all, hl }) {
  const p = new URLSearchParams();
  if (q) p.set("q", q);
  if (t) p.set("t", t);
  if (all) p.set("all", "1");
  if (hl) p.set("hl", hl);
  const s = p.toString().replace(/%3A/g, ":").replace(/%20/g, "+");
  return "/" + (s ? "?" + s : "");
}

function go(params, replace = false) {
  const url = urlFor(params);
  if (replace) history.replaceState(null, "", url);
  else history.pushState(null, "", url);
  render();
  window.scrollTo(0, 0);
}

async function api(path) {
  const r = await fetch(path);
  let body = {};
  try { body = await r.json(); } catch { body = { error: `Server error (${r.status}).` }; }
  return body;
}

/* ------------------------------------------------------------------ header */

function setHeaderTranslation(tid) {
  $("#t").value = tid;
  $("#t-label").textContent = tid;
}

function initHeader() {
  const sel = $("#t");
  sel.innerHTML = CONFIG.translations
    .map((t) => `<option value="${t.id}">${esc(t.id)} — ${esc(t.name)}${t.available ? "" : " (not connected)"}</option>`)
    .join("");
  sel.addEventListener("change", () => {
    const t = sel.value;
    store("bl.t", t);
    $("#t-label").textContent = t;
    const p = new URLSearchParams(location.search);
    if (p.get("q") && !p.get("all")) go({ q: p.get("q"), t, hl: p.get("hl") });
  });

  $("#search").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = $("#q").value.trim();
    if (!q) return $("#q").focus();
    go({ q, t: sel.value });
    $("#q").blur();
  });

  $("#brand").addEventListener("click", (e) => {
    e.preventDefault();
    $("#q").value = "";
    go({});
  });

  document.addEventListener("keydown", (e) => {
    const typing = /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName);
    if (e.key === "/" && !typing) {
      e.preventDefault();
      $("#q").focus();
      $("#q").select();
      return;
    }
    // ← / → : previous / next chapter (Cmd+← etc. are left to the browser)
    if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && !typing && CHAPTER_NAV && !$(".pop")
        && !e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey) {
      const url = e.key === "ArrowLeft" ? CHAPTER_NAV.prev : CHAPTER_NAV.next;
      if (!url) return;
      e.preventDefault();
      CHAPTER_NAV = null;  // one chapter per press, even while the next page loads
      history.pushState(null, "", url);
      render();
      window.scrollTo(0, 0);
    }
  });
}

/* ------------------------------------------------------------------ passage html */

function versesHTML(verses, { hl } = {}) {
  let [h1, h2] = (hl || "").split("-").map(Number);
  if (h1 && !h2) h2 = h1;
  let out = "";
  let open = false;
  const close = () => { if (open) { out += "</p>"; open = false; } };
  verses.forEach((v, i) => {
    if (v.s) { close(); out += `<h3 class="heading">${esc(v.s)}</h3>`; }
    if (v.t) { close(); out += `<p class="title">${esc(v.t)}</p>`; }
    if (!open || v.p || v.v === 1) { close(); out += "<p>"; open = true; }
    const mark = h1 && v.v >= h1 && v.v <= h2 ? " hl" : "";
    // Real spaces after the numbers (not just CSS margins) so plain-text copies read
    // "16 For God…" rather than "16For God…". The verse number's space is non-breaking
    // and sits inside the <sup>, so it's small and never strands a number at a line end.
    // A plain space after the chapter number would be dropped next to the float, so it
    // gets a non-breaking space shrunk to nothing (.ch-sp).
    const num = v.v === 1
      ? `<span class="ch-num">${v.c}</span><span class="ch-sp">&nbsp;</span>`
      : `<sup class="vn">${v.v}&nbsp;</sup>`;
    out += `<span class="v${mark}" id="v${v.c}-${v.v}">${num}${v.h}</span> `;
  });
  close();
  return out;
}

function unavailableHTML(res, tname) {
  const links = [];
  if (res.logos) links.push(`<a class="btn" href="${esc(res.logos)}">Open in Logos</a>`);
  links.push(`<a class="btn" href="${esc(res.bibleGateway)}" target="_blank" rel="noopener">Read on BibleGateway ↗</a>`);
  return `<div class="notice">
    <h2>${esc(tname)} isn’t connected yet</h2>
    <p>${esc(res.unavailable || res.error)}</p>
    <div class="btns">${links.join("")}</div>
  </div>`;
}

/* ------------------------------------------------------------------ views */

// One passage section: toolbar (reference + translation), text, and links.
function blockHTML(res, tid, { hl, afterToolbar = "" } = {}) {
  const t = T_BY_ID[tid];
  const ref = res.ref;
  const toolbar = `<div class="toolbar">
      <div style="position:relative">
        <button class="drop refbtn" aria-haspopup="true" aria-expanded="false">${esc(ref.display)} ${CHEV}</button>
      </div>
      <label class="drop">
        <span>${esc(t.name)}</span>${CHEV}
        <select class="tsel" aria-label="Translation">${CONFIG.translations
          .map((x) => `<option value="${x.id}"${x.id === tid ? " selected" : ""}>${esc(x.name)} (${x.id})${x.available ? "" : " — not connected"}</option>`)
          .join("")}</select>
      </label>
    </div>`;

  let body;
  if (res.verses) {
    body = `<div class="passage">${versesHTML(res.verses, { hl })}</div>`;
  } else if (res.unavailable) {
    body = unavailableHTML(res, t.name);
  } else {
    body = `<p class="error">${esc(res.error)}</p>` + unavailableHTML({ ...res, unavailable: "You can still read it here:" }, t.name).replace(/<h2>.*?<\/h2>/, "");
  }

  const links = [];
  if (!ref.isChapter) {
    const sameCh = ref.c1 === ref.c2;
    links.push(`<a href="${urlFor({ q: ref.chapterQuery, t: tid, hl: sameCh ? `${ref.v1}-${ref.v2}` : null })}" data-nav>Read full chapter</a>`);
  }
  links.push(`<a href="${urlFor({ q: ref.query, all: true })}" data-nav>${esc(ref.display)} in all English translations</a>`);

  return toolbar + afterToolbar + body + (res.verses || res.unavailable ? `<div class="links">${links.join("")}</div>` : "");
}

// Wire up a section's dropdowns. Changing the translation re-runs the whole query.
function bindBlock(el, res, tid, fullQuery, hl) {
  el.querySelector(".tsel").addEventListener("change", (e) => {
    store("bl.t", e.target.value);
    setHeaderTranslation(e.target.value);
    go({ q: fullQuery, t: e.target.value, hl });
  });
  const btn = el.querySelector(".refbtn");
  btn.addEventListener("click", (e) => { e.stopPropagation(); togglePicker(btn, res.ref, tid); });
}

function metaHTML(results) {
  const ok = results.filter((r) => r && r.verses);
  if (!ok.length) return "";
  const open = [];
  const logos = ok.filter((r) => r.logos);
  if (logos.length === 1) open.push(`<a href="${esc(logos[0].logos)}">Open in Logos</a>`);
  else if (logos.length > 1) {
    open.push("Open in Logos: " + logos.map((r) => `<a href="${esc(r.logos)}">${esc(r.ref.display)}</a>`).join(", "));
  }
  const bg = new URL(ok[0].bibleGateway);
  bg.searchParams.set("search", ok.map((r) => r.ref.query).join("; "));
  open.push(`<a href="${esc(bg.toString())}" target="_blank" rel="noopener">BibleGateway</a>`);
  const rights = [...new Set(ok.map((r) => r.copyright).filter(Boolean))];
  return `<div class="meta"><p>${open.join(" · ")}</p>${rights.map((c) => `<p>${esc(c)}</p>`).join("")}</div>`;
}

async function renderPassage(q, tid, hl) {
  if (/[;,]/.test(q)) return renderMulti(q, tid);
  const main = $("#main");
  const id = RENDER_ID;
  main.innerHTML = `<div class="skel"></div><div class="skel"></div><div class="skel s2"></div>`;
  const res = await api(`/api/passage?q=${encodeURIComponent(q)}&t=${tid}`);
  if (id !== RENDER_ID) return;  // the reader has already moved on
  if (!res.ref) {
    main.innerHTML = `<p class="error">${esc(res.error)}</p>`;
    $("#q").value = q;
    document.title = "Bible Lookup";
    return;
  }
  const ref = res.ref;
  $("#q").value = ref.display.replace("–", "-");
  document.title = `${ref.display} (${tid}) – Bible Lookup`;

  const prevUrl = ref.prev ? urlFor({ q: ref.prev, t: tid }) : null;
  const nextUrl = ref.next ? urlFor({ q: ref.next, t: tid }) : null;
  CHAPTER_NAV = { prev: prevUrl, next: nextUrl };

  // previous / next chapter buttons, shown above and below the text on chapter pages
  const chapnav = (where) => !ref.isChapter ? "" : `<nav class="chapnav ${where}" aria-label="Chapter navigation">
      ${prevUrl ? `<a href="${prevUrl}" data-nav title="Previous chapter (← key)" aria-keyshortcuts="ArrowLeft">← ${esc(ref.prev)}</a>` : "<span></span>"}
      ${nextUrl ? `<a href="${nextUrl}" data-nav title="Next chapter (→ key)" aria-keyshortcuts="ArrowRight">${esc(ref.next)} →</a>` : "<span></span>"}
    </nav>`;

  main.innerHTML = `<section class="block">${blockHTML(res, tid, { hl, afterToolbar: chapnav("top") })}</section>`
    + chapnav("bottom") + metaHTML([res]);
  bindBlock(main.querySelector(".block"), res, tid, ref.query, hl);

  if (hl) {
    const first = main.querySelector(".hl");
    if (first) first.scrollIntoView({ block: "center" });
  }
}

// Several passages separated by semicolons or commas: "James 1:5; John 3:16-18, 21".
async function renderMulti(q, tid) {
  const main = $("#main");
  main.innerHTML = `<div class="skel"></div><div class="skel"></div><div class="skel s2"></div>`;
  const parsed = await api(`/api/parse?q=${encodeURIComponent(q)}`);
  if (!parsed.parts) {
    main.innerHTML = `<p class="error">${esc(parsed.error)}</p>`;
    return;
  }
  const parts = parsed.parts;
  const fullQuery = parts.map((p) => p.query || p.input).join("; ");
  $("#q").value = fullQuery;
  document.title = `${fullQuery} (${tid}) – Bible Lookup`;
  main.innerHTML = parts.map((p, i) => `<section class="block" id="blk-${i}">
      ${p.error ? `<p class="error">${esc(p.input)}: ${esc(p.error)}</p>`
                : `<div class="skel"></div><div class="skel"></div><div class="skel s2"></div>`}
    </section>`).join("") + `<div id="multi-meta"></div>`;

  const results = await Promise.all(parts.map(async (p, i) => {
    if (p.error) return null;
    const res = await api(`/api/passage?q=${encodeURIComponent(p.query)}&t=${tid}`);
    const el = $(`#blk-${i}`);
    if (!el) return null;  // navigated away
    if (!res.ref) {
      el.innerHTML = `<p class="error">${esc(p.input)}: ${esc(res.error)}</p>`;
      return null;
    }
    el.innerHTML = blockHTML(res, tid);
    bindBlock(el, res, tid, fullQuery);
    return res;
  }));
  const meta = $("#multi-meta");
  if (meta) meta.outerHTML = metaHTML(results);
}

async function renderCompare(q) {
  const main = $("#main");
  main.innerHTML = `<div class="compare"><h1 id="cmp-title">&nbsp;</h1><div id="cmp-list"></div></div>`;
  const list = $("#cmp-list");
  list.innerHTML = CONFIG.translations
    .map((t) => `<section class="cmp" id="cmp-${t.id}">
        <div class="cmp-head"><a href="#" data-t="${t.id}">${esc(t.id)}</a><span>${esc(t.name)}</span></div>
        <div class="body"><div class="skel"></div><div class="skel s2"></div></div>
      </section>`)
    .join("");

  let titled = false;
  await Promise.all(CONFIG.translations.map(async (t) => {
    const res = await api(`/api/passage?q=${encodeURIComponent(q)}&t=${t.id}`);
    const sec = $(`#cmp-${t.id}`);
    if (!res.ref) {
      main.innerHTML = `<p class="error">${esc(res.error)}</p>`;
      return;
    }
    if (!titled) {
      titled = true;
      $("#cmp-title").textContent = `${res.ref.display} in all English translations`;
      $("#q").value = res.ref.display.replace("–", "-");
      document.title = `${res.ref.display} – all translations – Bible Lookup`;
    }
    if (!sec) return;
    sec.querySelector(".cmp-head a").href = urlFor({ q: res.ref.query, t: t.id });
    sec.querySelector(".cmp-head a").setAttribute("data-nav", "");
    const body = sec.querySelector(".body");
    if (res.verses) {
      body.innerHTML = `<div class="passage">${versesHTML(res.verses)}</div>`;
    } else {
      const links = [];
      if (res.logos) links.push(`<a href="${esc(res.logos)}">Open in Logos</a>`);
      links.push(`<a href="${esc(res.bibleGateway)}" target="_blank" rel="noopener">BibleGateway ↗</a>`);
      body.innerHTML = `<p class="off">${res.unavailable ? "Not connected." : esc(res.error)}${links.join("")}</p>`;
    }
  }));
}

/* ------------------------------------------------------------------ book / chapter picker */

function closePicker() {
  const pop = $(".pop");
  if (pop) pop.remove();
  document.querySelectorAll(".refbtn").forEach((b) => b.setAttribute("aria-expanded", "false"));
}

function togglePicker(btn, ref, tid) {
  const wasOpen = btn.parentElement.querySelector(".pop");
  closePicker();
  if (wasOpen) return;
  btn.setAttribute("aria-expanded", "true");
  const pop = document.createElement("div");
  pop.className = "pop";
  pop.addEventListener("click", (e) => e.stopPropagation());
  btn.parentElement.appendChild(pop);

  const showBooks = () => {
    const group = (from, to) => CONFIG.books.slice(from, to)
      .map((b) => `<button data-b="${b.id}" class="${b.id === ref.book ? "cur" : ""}">${esc(b.name)}</button>`).join("");
    pop.innerHTML = `<h3>Old Testament</h3><div class="books">${group(0, 39)}</div>
                     <h3>New Testament</h3><div class="books">${group(39, 66)}</div>`;
    pop.querySelectorAll("[data-b]").forEach((el) => el.addEventListener("click", () => showChapters(el.dataset.b)));
    const cur = pop.querySelector(".cur");
    if (cur) cur.scrollIntoView({ block: "nearest" });
  };
  const showChapters = (bid) => {
    const b = CONFIG.books.find((x) => x.id === bid);
    if (b.chapters === 1) { closePicker(); return go({ q: `${b.name} 1`, t: tid }); }
    let nums = "";
    for (let c = 1; c <= b.chapters; c++) nums += `<button data-c="${c}">${c}</button>`;
    pop.innerHTML = `<button class="back">← ${esc(b.name)}</button><div class="chaps">${nums}</div>`;
    pop.querySelector(".back").addEventListener("click", showBooks);
    pop.querySelectorAll("[data-c]").forEach((el) => el.addEventListener("click", () => {
      closePicker();
      go({ q: `${b.name} ${el.dataset.c}`, t: tid });
    }));
  };
  showBooks();
}

document.addEventListener("click", closePicker);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePicker(); });

// In-page links navigate without a full reload.
document.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-nav]");
  if (!a || e.metaKey || e.ctrlKey || e.shiftKey) return;
  e.preventDefault();
  history.pushState(null, "", a.getAttribute("href"));
  render();
  if (!new URLSearchParams(location.search).get("hl")) window.scrollTo(0, 0);
});

/* ------------------------------------------------------------------ router */

function render() {
  RENDER_ID++;
  CHAPTER_NAV = null;
  closePicker();
  const p = new URLSearchParams(location.search);
  // stray separators at either end ("Isa. 53:6,") would turn one passage into a list
  const q = (p.get("q") || "").replace(/^[\s,;]+|[\s,;]+$/g, "");
  const tid = currentTranslation();
  setHeaderTranslation(tid);
  const home = !q;
  document.body.classList.toggle("home", home);
  $("#main").hidden = home;
  if (home) {
    document.title = "Bible Lookup";
    $("#q").value = "";
    $("#q").focus();
    return;
  }
  if (p.get("t")) store("bl.t", tid);
  if (p.get("all")) renderCompare(q);
  else renderPassage(q, tid, p.get("hl"));
}

window.addEventListener("popstate", render);

(async function init() {
  CONFIG = await api("/api/config");
  T_BY_ID = Object.fromEntries(CONFIG.translations.map((t) => [t.id, t]));
  initHeader();
  render();
})();
