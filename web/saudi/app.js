/* FLOPO Trait Atlas: a browser over the SPARQL endpoint next to this page ("sparql"). */
"use strict";

const FB = "http://phenomebrowser.net/flopo/browse#";
const TAXON = "http://phenomebrowser.net/flopo/taxon/";
// Relative to the page, so the atlas runs at / (development) and under /flopo/ (public).
const ENDPOINT = new URL("sparql", document.baseURI).href;
const SUMMARY = new URL("summary.json", document.baseURI).href;
const INATURALIST = new URL("inaturalist.json", document.baseURI).href;
// The endpoint predefines no prefixes; queries get the declarations they do not make themselves.
const PREFIXES = {
  fb: FB,
  flopoann: "http://phenomebrowser.net/flopo/annotation/",
  obo: "http://purl.obolibrary.org/obo/",
  rdfs: "http://www.w3.org/2000/01/rdf-schema#",
  rdf: "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
  owl: "http://www.w3.org/2002/07/owl#",
  skos: "http://www.w3.org/2004/02/skos/core#",
  oboInOwl: "http://www.geneontology.org/formats/oboInOwl#",
  dcterms: "http://purl.org/dc/terms/",
  sio: "http://semanticscience.org/resource/",
  prov: "http://www.w3.org/ns/prov#",
  dwc: "http://rs.tdwg.org/dwc/terms/",
  geo: "http://www.opengis.net/ont/geosparql#",
  xsd: "http://www.w3.org/2001/XMLSchema#",
};
function withPrefixes(query) {
  const declared = new Set([...query.matchAll(/PREFIX\s+([\w-]*):/gi)].map((m) => m[1]));
  // IRIs and strings may contain "x:" or "#"; drop them, then comments, before looking for uses.
  const body = query.replace(/<[^<>\s]*>/g, " ").replace(/"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'/g, " ").replace(/#[^\n]*/g, "");
  const missing = Object.entries(PREFIXES).filter(([p]) => !declared.has(p) && new RegExp(`(^|[^\\w:.-])${p}:`).test(body));
  return missing.map(([p, iri]) => `PREFIX ${p}: <${iri}>\n`).join("") + query;
}
const sparqlUrl = (query, extra = {}) => ENDPOINT + "?" + new URLSearchParams({ query: withPrefixes(query), ...extra });
document.getElementById("endpoint")?.replaceChildren(ENDPOINT);
// The skip link must not change the address (the address is the page): it moves the focus to the page.
document.getElementById("skip")?.addEventListener("click", (e) => { e.preventDefault(); document.getElementById("view").focus(); });
const view = document.getElementById("view");
const cache = new Map();

/* ---------------------------------------------------------------- helpers */
async function requestJson(url, options = {}) {
  // These are read-only requests. Retry one interrupted connection or transient service failure.
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const response = await fetch(url, options);
      if (!response.ok) {
        const error = new Error((await response.text()) || `Trait service returned HTTP ${response.status}`);
        error.transient = [429, 502, 503, 504].includes(response.status);
        throw error;
      }
      return await response.json();
    } catch (error) {
      const network = error instanceof TypeError || error.name === "NetworkError";
      if (attempt || (!network && !error.transient)) throw error;
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  }
}
async function sparql(query) {
  // GET where the URL stays short: the firewall in front of phenomebrowser.net resets POST bodies
  // that contain GROUP_CONCAT (an SQL-injection signature), but lets the same query through as GET.
  const accept = { Accept: "application/sparql-results+json" };
  const url = sparqlUrl(query);
  const json = url.length <= 6000
    ? await requestJson(url, { headers: accept })
    : await requestJson(ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded", ...accept },
        body: new URLSearchParams({ query: withPrefixes(query) }),
      });
  if (json.boolean !== undefined) return [{ result: String(json.boolean) }];
  return json.results.bindings.map((b) => Object.fromEntries(Object.entries(b).map(([k, v]) => [k, v.value])));
}
async function cached(key, fn) {
  if (!cache.has(key)) {
    const pending = Promise.resolve().then(fn).catch((error) => {
      if (cache.get(key) === pending) cache.delete(key);
      throw error;
    });
    cache.set(key, pending);
  }
  return cache.get(key);
}
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const iriLiteral = (iri) => `<${iri.replace(/[<>"{}|^`\\\s]/g, "")}>`;
const taxonKey = (iri) => iri.startsWith(TAXON) ? iri.slice(TAXON.length) : iri;
const taxonHref = (iri) => `#/taxon/${encodeURIComponent(taxonKey(iri))}`;
const local = (iri) => iri.replace(/^.*[#/]/, "");
const curie = (iri) => local(iri).replace("_", ":");
const n = (x) => Number(x).toLocaleString("en");
const OBO = "http://purl.obolibrary.org/obo/";
const isObo = (iri) => iri.startsWith(OBO);
const termHref = (iri) => `#/term/${curie(iri)}`;
const SITE = "FLOPO Trait Atlas";
const setTitle = (text) => { document.title = text ? `${text} · ${SITE}` : SITE; };
const sourceClass = (label) => (/collenette/i.test(label) ? "collenette" : /ncvc/i.test(label) ? "ncvc" : "");
const inaturalistData = () => cached("inaturalist", () => requestJson(INATURALIST));
// The block is shown only for a taxon with a confirmed match; without one it would be an empty box.
function inaturalistPanel(entry, label, generated) {
  if (!entry || entry.status !== "matched") return "";
  const id = Number(entry.id);
  if (!Number.isSafeInteger(id) || id <= 0) return "";
  const allowedLicenses = new Set(["cc0", "cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nc-sa"]);
  const pictures = (entry.photos || []).filter((p) => allowedLicenses.has(p.license) && /^https:\/\//.test(p.url));
  return `<section class="inat-panel" aria-label="iNaturalist images and observations"><h2>iNaturalist</h2>
    <p><a href="https://www.inaturalist.org/taxa/${id}" target="_blank" rel="noopener"><i>${esc(entry.inat_name)}</i></a>
      <span class="muted">(${esc(entry.rank)})</span></p>
    <div class="inat-gallery">${pictures.map((p) => `<figure>
      <a href="https://www.inaturalist.org/photos/${Number(p.id)}" target="_blank" rel="noopener"><img src="${esc(p.url)}" alt="${esc(entry.inat_name)} — iNaturalist taxon photograph" loading="lazy" referrerpolicy="no-referrer"></a>
      <figcaption>${esc(p.attribution)} · <a href="${p.license === "cc0" ? "https://creativecommons.org/publicdomain/zero/1.0/" : `https://creativecommons.org/licenses/${p.license.slice(3)}/4.0/`}" target="_blank" rel="noopener">${esc(p.license.toUpperCase())}</a></figcaption>
    </figure>`).join("")}</div>
    ${pictures.length ? `<p class="muted">These photographs illustrate the taxon. The traits below come from floras and have not been verified in each image.</p>` : `<p class="muted">No reusable photograph in this catalogue snapshot.</p>`}
    <p><a href="https://www.inaturalist.org/observations?taxon_id=${id}" target="_blank" rel="noopener">View observations (${n(entry.observations_count)} at last update)</a>
      · <a href="https://www.inaturalist.org/observations?taxon_id=${id}&photos=true&quality_grade=research" target="_blank" rel="noopener">Research-grade photo observations</a></p>
    ${generated ? `<p class="muted inat-updated">Catalogue updated ${esc(generated.slice(0, 10))}.</p>` : ""}</section>`;
}
function html(strings, ...values) {
  return strings.reduce((out, s, i) => out + s + (i < values.length ? values[i] : ""), "");
}
function setView(content) {
  view.innerHTML = content;
  view.focus({ preventScroll: true });
}
function heat(value, max) {
  if (!value) return "transparent";
  const t = Math.sqrt(value / max);
  return `color-mix(in srgb, var(--ochre) ${Math.round(12 + t * 78)}%, var(--paper))`;
}
// Ontology terms open the atlas's own page for the term (#/term/PO:0009046); other IRIs open outside.
function termLink(iri, label) {
  if (!iri) return esc(label);
  if (isObo(iri)) return `<a href="${esc(termHref(iri))}" title="${esc(curie(iri))}">${esc(label)}</a>`;
  return `<a href="${esc(iri)}" target="_blank" rel="noopener" title="${esc(local(iri))}">${esc(label)}</a>`;
}
function highlight(context, text) {
  if (!context) return `<span class="quote">${esc(text)}</span>`;
  const i = context.indexOf(text);
  if (i < 0) return `<span class="quote">${esc(context)}</span>`;
  return `<span class="quote">${esc(context.slice(0, i))}<mark>${esc(text)}</mark>${esc(context.slice(i + text.length))}</span>`;
}

/* ---------------------------------------------------------------- shared data */
const groups = () =>
  cached("groups", async () => {
    const rows = await sparql(`SELECT ?g ?type (SAMPLE(?l) AS ?label) (SAMPLE(?o) AS ?order) WHERE {
      ?g a ?type ; rdfs:label ?l ; fb:order ?o . FILTER(?type IN (fb:OrganGroup, fb:TraitGroup)) } GROUP BY ?g ?type`);
    const pick = (type) => rows.filter((r) => r.type === FB + type).sort((a, b) => a.order - b.order);
    return { organs: pick("OrganGroup"), traits: pick("TraitGroup"), label: Object.fromEntries(rows.map((r) => [r.g, r.label])) };
  });
const summary = () => cached("summary", () => requestJson(SUMMARY));
// Site-wide counts, answered once per release by tools/atlas_precompute.py; the query is the fallback.
const precomputed = (name) =>
  cached("pre-" + name, async () => {
    try {
      return await requestJson(new URL(`precomputed/${name}.json`, document.baseURI).href);
    } catch (e) {
      const queries = await cached("pre-queries", () => requestJson(new URL("precomputed-queries.json", document.baseURI).href));
      return sparql(queries[name]);
    }
  });
const sources = () =>
  cached("sources", () => sparql(`SELECT ?s (SAMPLE(?l) AS ?label) (SAMPLE(?t) AS ?title) WHERE { ?s a fb:Source ; rdfs:label ?l ; <http://purl.org/dc/terms/title> ?t } GROUP BY ?s`));

// Short column names for the narrow fingerprint of a taxon; the full name stays as a tooltip.
const SHORT_TRAIT = { "Size and measurements": "Size", "Surface and hairs": "Surface", "Arrangement and position": "Position", "Habit and life cycle": "Habit", "Presence of structures": "Presence", "Structure and texture": "Structure", "Other qualities": "Other" };
function atlasTable(cells, organs, traits, { link = true, caption = "", short = false } = {}) {
  const max = Math.max(1, ...cells.map((c) => +c.value));
  const lookup = new Map(cells.map((c) => [c.og + "|" + c.tg, c]));
  const usedOrgans = organs.filter((o) => cells.some((c) => c.og === o.g));
  const usedTraits = traits.filter((t) => cells.some((c) => c.tg === t.g));
  return html`<table class="atlas">
    ${caption ? `<caption>${caption}</caption>` : ""}
    <thead><tr><th></th>${usedTraits.map((t) => `<th scope="col" title="${esc(t.label)}">${esc(short ? SHORT_TRAIT[t.label] || t.label : t.label)}</th>`).join("")}</tr></thead>
    <tbody>${usedOrgans
      .map(
        (o) => `<tr><th scope="row">${esc(o.label)}</th>${usedTraits
          .map((t) => {
            const c = lookup.get(o.g + "|" + t.g);
            if (!c) return `<td><span class="empty">·</span></td>`;
            const style = `background:${heat(+c.value, max)}`;
            const title = `${o.label}, ${t.label}: ${c.title}`;
            return link
              ? `<td><a style="${style}" title="${esc(title)}" href="#/traits/${local(o.g)}/${local(t.g)}">${n(c.value)}</a></td>`
              : `<td><span style="${style}" title="${esc(title)}">${n(c.value)}</span></td>`;
          })
          .join("")}</tr>`
      )
      .join("")}</tbody></table>`;
}

/* ---------------------------------------------------------------- overview */
async function overview() {
  setView(`<p class="loading">Loading the atlas…</p>`);
  const [g, s, src, cells] = await Promise.all([
    groups(),
    summary(),
    sources(),
    precomputed("atlas"),
  ]);
  const keys = Object.keys(s).filter((k) => s[k] && s[k].phenotype_rows !== undefined);
  // Records that failed a check are kept for the record but are not traits: they are not counted.
  const usable = (sk) => (sk.assertions || 0) - (sk.gate_blocked || 0);
  const records = keys.reduce((a, k) => a + usable(s[k]), 0);
  const rows = keys.reduce((a, k) => a + (s[k].phenotype_rows || 0), 0);
  const formal = keys.reduce((a, k) => a + (s[k].rows_formalized || 0), 0);
  const occurrences = keys.reduce((a, k) => a + (s[k].occurrences || 0), 0);
  const atlasCells = cells.map((c) => ({ ...c, value: c.taxa, title: `${n(c.taxa)} taxa, ${n(c.n)} records` }));
  const srcRows = keys
    .map((k) => {
      const meta = src.find((x) => x.s.endsWith("/" + k)) || { label: k, title: k };
      const sk = s[k];
      const share = sk.phenotype_rows ? sk.rows_formalized / sk.phenotype_rows : 0;
      return `<div class="source-row">
        <div><b>${esc(meta.label)}</b><br><span class="muted">${esc(meta.title)}</span><br>
          <span class="muted num">${n(s.taxa.per_source[k] || 0)} taxa, ${n(usable(sk))} trait records, ${n(sk.occurrences || 0)} place records</span></div>
        <div><div class="bar" title="${Math.round(share * 100)}% of transcribed statements are FLOPO annotations"><i style="width:${share * 100}%"></i></div>
          <span class="muted num">${n(sk.rows_formalized)} of ${n(sk.phenotype_rows)} transcribed trait statements annotated (${Math.round(share * 100)}%)</span></div>
      </div>`;
    })
    .join("");
  setView(html`
    <section class="hero">
      <h1>Plant traits across floras</h1>
      <form class="hero-search" id="home-form" role="search" autocomplete="off">
        <label for="home-search">Search ${n(s.taxa.taxa)} taxa and their traits</label>
        <div class="hero-row">
          <input id="home-search" type="search" placeholder="A plant, a family or a trait: Vachellia tortilis, Lamiaceae, yellow flower" aria-controls="home-results" aria-describedby="home-hint" autocomplete="off">
          <button type="submit">Search</button>
        </div>
        <p class="muted" id="home-hint">Scientific names, families, and trait words such as “glabrous leaf”.</p>
        <div id="home-results" class="home-results" aria-live="polite"></div>
      </form>
      <div class="starters">
        <a class="starter" href="#/taxon/ipni-520167-1"><b>Read one plant in many floras</b><span><i class="sci">Tamarindus indica</i> is described in 14 floras. Open it to see the statements side by side.</span></a>
        <a class="starter" href="#/compare/ipni-520167-1/ipni-491231-1"><b>Compare two plants</b><span><i class="sci">Tamarindus indica</i> and <i class="sci">Delonix regia</i>, trait by trait.</span></a>
        <a class="starter" href="#/identify"><b>Name a plant from its traits</b><span>Say what you see, such as flower colour and leaf shape, and get a ranked list of taxa.</span></a>
      </div>
    </section>
    <section class="intro">
      <div>
        <p class="lede">Explore annotated plant traits from ${n(keys.length)} flora sources. Each annotation links a taxon,
          a FLOPO phenotype built from a Plant Ontology part and a PATO quality, and its source sentence.
          Most floras are included in full; the <a href="#/coverage">coverage</a> page gives the numbers for each, and the <a href="#/map">map</a> shows where the taxa are recorded.</p>
        <div class="figures">
          <div class="figure"><b class="num">${n(s.taxa.taxa)}</b><span>taxa, ${s.taxa.with_ipni !== undefined ? `${n(s.taxa.with_ipni)} with an IPNI name` : `${n(s.taxa.with_wfo)} with a recorded WFO mapping`}</span></div>
          <div class="figure"><b class="num">${n(records)}</b><span>trait annotations</span></div>
          <div class="figure"><b class="num">${Math.round((formal / Math.max(rows, 1)) * 100)}%</b><span>of ${n(rows)} transcribed trait statements captured</span></div>
          <div class="figure"><b class="num">${n(occurrences)}</b><span>records of where taxa grow</span></div>
        </div>
        <p class="muted">Each number in the atlas counts the taxa with at least one trait for that plant part and kind of trait. Select a cell to see them.</p>
      </div>
      <div class="tablewrap" tabindex="0" role="region" aria-label="Taxa by plant part and trait">${atlasTable(atlasCells, g.organs, g.traits, { caption: "Taxa with an annotation, by plant part and kind of trait" })}</div>
    </section>
    <h2>Sources</h2>
    <p class="muted">Counts describe the extracts currently included. Annotation percentages refer to transcribed statements, not the complete source. Taxon mappings and provisional traits remain under review.</p>
    <div class="sources">${srcRows}</div>`);
  homeSearch();
}

/* ---------------------------------------------------------------- taxa */
// The release ships a static index of all taxa (tools/atlas_taxa_index.py): one compressed file,
// filtered in the browser, instead of four large queries. Rows keep the order of the file (the map
// refers to them by position); `sorted` is the same rows ordered by name without leading punctuation.
// The last field of a row, names printed in the floras, is missing in older releases.
const taxonIndex = () =>
  cached("taxa", async () => {
    const data = await requestJson(new URL("taxa.json", document.baseURI).href);
    const rows = data.taxa.map(([key, label, auth, fam, n, srcs, vern, syns]) => {
      const family = data.families[fam] || "";
      return {
        t: TAXON + key, key, label, auth, family, n, src: srcs, vern, syn: syns ? syns.split("|") : [],
        sk: label.replace(/^[^\p{L}\p{N}]+/u, "").toLowerCase(),
        find: (label + " " + family + " " + vern + " " + (syns || "").replace(/\|/g, " ")).toLowerCase(),
      };
    });
    const sorted = [...rows].sort((a, b) => (a.sk < b.sk ? -1 : a.sk > b.sk ? 1 : 0));
    return { rows, sorted, sourceKeys: data.sources, withData: rows.filter((r) => r.n > 0).length };
  });

const LIST_LIMIT = 200;
function taxonMatches(index, filter, source, onlyData = false) {
  const words = filter.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const s = source === "" ? -1 : index.sourceKeys.indexOf(source);
  return index.sorted.filter((r) => (!onlyData || r.n > 0) && (s < 0 || r.src.includes(s)) && words.every((w) => r.find.includes(w)));
}
// A taxon found by a name printed in a flora: that name, shown beside the accepted one.
function matchedSynonym(r, filter) {
  const words = filter.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length || !r.syn.length) return "";
  const own = (r.label + " " + r.family + " " + r.vern).toLowerCase();
  if (words.every((w) => own.includes(w))) return "";
  return r.syn.find((x) => words.some((w) => x.toLowerCase().includes(w))) || "";
}
// The list shows a window of the matches: the first page, or the page around the taxon that is open.
function taxonList(shown, filter, current, start, end) {
  if (!shown.length) return `<p class="muted">No taxon matches “${esc(filter)}”.</p>`;
  const items = shown.slice(start, end).map((r) => {
    const syn = matchedSynonym(r, filter);
    return `<a href="${taxonHref(r.t)}" class="${r.t === current ? "current" : ""}"><span class="sci">${esc(r.label)}${syn ? ` <span class="syn">= ${esc(syn)}</span>` : ""}</span>${r.family ? ` <span class="muted fam">${esc(r.family)}</span>` : ""}<small class="num" title="trait records">${r.n}</small></a>`;
  }).join("");
  const less = start > 0 ? `<button type="button" class="ghost" id="tless">Show ${n(Math.min(LIST_LIMIT, start))} earlier of ${n(start)}</button>` : "";
  const more = shown.length > end ? `<button type="button" class="ghost" id="tmore">Show ${n(Math.min(LIST_LIMIT, shown.length - end))} more of ${n(shown.length - end)}</button>` : "";
  return less + items + more;
}
const narrowScreen = () => window.matchMedia && window.matchMedia("(max-width: 900px)").matches;

async function taxa(key) {
  const current = key ? TAXON + decodeURIComponent(key) : "";
  // Moving from one taxon to another keeps the list, its filter and its scroll position.
  if (document.getElementById("tlist") && document.getElementById("tpane")) {
    document.querySelectorAll("#tlist a.current").forEach((a) => a.classList.remove("current"));
    document.querySelectorAll(`#tlist a[href="${CSS.escape(taxonHref(current))}"]`).forEach((a) => a.classList.add("current"));
    if (current) {
      document.getElementById("tpane").innerHTML = `<p class="loading">Loading…</p>`;
      if (narrowScreen()) { setDrawer(false); window.scrollTo(0, 0); }
      await taxonPage(current);
    }
    return;
  }
  let filterValue = "", sourceValue = "", onlyData = true;
  try {
    filterValue = sessionStorage.getItem("taxonFilter") || "";
    sourceValue = sessionStorage.getItem("taxonSourceFilter") || "";
    onlyData = sessionStorage.getItem("taxonShowAll") !== "1";
  } catch (e) { /* storage unavailable */ }
  setTitle(current ? "Taxon" : "Taxa");
  setView(html`<div class="split">
      <aside class="listpane${current && narrowScreen() ? " collapsed" : ""}" id="listpane">
        <button type="button" class="drawer-toggle" id="drawer-toggle" aria-controls="listbody" aria-expanded="${!(current && narrowScreen())}">Find or switch taxon</button>
        <div class="listbody" id="listbody">
          <label for="tfilter" class="col-title">Find a taxon by name, family or a name printed in a flora</label>
          <input id="tfilter" type="search" value="${esc(filterValue)}" placeholder="e.g. Acacia tortilis, Lamiaceae" autocomplete="off">
          <label for="sfilter" class="col-title">Flora</label>
          <select id="sfilter" style="width:100%;margin-bottom:.5rem"><option value="">All floras</option></select>
          <label class="check"><input type="checkbox" id="thastrait" ${onlyData ? "checked" : ""}> <span id="thastrait-label">Only taxa with trait records</span></label>
          <p class="muted" id="tcount" aria-live="polite">Loading the taxon list…</p>
          <div class="taxonlist" id="tlist"></div>
        </div>
      </aside>
      <section id="tpane">${current ? `<p class="loading">Loading…</p>` : ""}</section>
    </div>`);
  document.getElementById("drawer-toggle").addEventListener("click", () => setDrawer(document.getElementById("listpane").classList.contains("collapsed")));
  const pagePromise = current ? taxonPage(current) : null; // the taxon does not wait for the list
  const [index, srcList] = await Promise.all([taxonIndex(), sources()]);
  const sourceLabel = (k) => (srcList.find((x) => x.s.endsWith("/" + k)) || {}).label || k;
  const input = document.getElementById("tfilter");
  const sselect = document.getElementById("sfilter");
  const check = document.getElementById("thastrait");
  const list = document.getElementById("tlist");
  if (!input || !list) return;
  sselect.innerHTML = `<option value="">All floras</option>` +
    index.sourceKeys.map((k) => [k, sourceLabel(k)]).sort((a, b) => a[1].localeCompare(b[1]))
      .map(([k, l]) => `<option value="${esc(k)}" ${k === sourceValue ? "selected" : ""}>${esc(l)}</option>`).join("");
  document.getElementById("thastrait-label").textContent = `Only taxa with trait records (${n(index.withData)} of ${n(index.rows.length)})`;
  if (!current) {
    document.getElementById("tpane").innerHTML = `<h1>${n(index.withData)} taxa with trait records</h1><p class="muted">Type part of a name to find a taxon, or a name that a flora prints for it; several words narrow the list (“Acacia Fabaceae”). The number after each name counts its trait records. ${n(index.rows.length - index.withData)} more taxa have no trait records yet; tick “Only taxa with trait records” off to list them too.</p>`;
  }
  // A filter left from an earlier visit to this page must not hide the taxon that was opened.
  if (current && !taxonMatches(index, input.value, sselect.value, check.checked).some((r) => r.t === current)) {
    input.value = "";
    sselect.value = "";
    if (!taxonMatches(index, "", "", check.checked).some((r) => r.t === current)) check.checked = false;
  }
  let shown = [], start = 0, end = LIST_LIMIT, timer = 0;
  const draw = () => {
    list.innerHTML = taxonList(shown, input.value, current, start, end);
    const base = check.checked ? index.withData : index.rows.length;
    document.getElementById("tcount").textContent = shown.length === base ? `${n(shown.length)} taxa${check.checked ? " with trait records" : ""}, alphabetical` : `${n(shown.length)} of ${n(base)} taxa match`;
    document.getElementById("tmore")?.addEventListener("click", () => { end += LIST_LIMIT; draw(); });
    document.getElementById("tless")?.addEventListener("click", () => {
      const keep = list.querySelector("a")?.getAttribute("href");
      start = Math.max(0, start - LIST_LIMIT);
      draw();
      if (keep) list.querySelector(`a[href="${CSS.escape(keep)}"]`)?.scrollIntoView({ block: "start" });
    });
  };
  const update = (opened = false) => {
    try {
      sessionStorage.setItem("taxonFilter", input.value);
      sessionStorage.setItem("taxonSourceFilter", sselect.value);
      sessionStorage.setItem("taxonShowAll", check.checked ? "0" : "1");
    } catch (e) { /* storage unavailable */ }
    shown = taxonMatches(index, input.value, sselect.value, check.checked);
    const at = opened ? shown.findIndex((r) => r.t === current) : -1;
    start = at > LIST_LIMIT / 2 ? at - LIST_LIMIT / 2 : 0;
    end = start + LIST_LIMIT;
    draw();
  };
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => update(), 120); });
  sselect.addEventListener("change", () => update());
  check.addEventListener("change", () => update());
  update(true);
  const active = list.querySelector("a.current");
  if (active && !narrowScreen()) active.scrollIntoView({ block: "center" });
  if (pagePromise) await pagePromise;
}
// On a phone the list of taxa sits behind a button, so that the taxon comes first.
function setDrawer(open) {
  const pane = document.getElementById("listpane");
  if (!pane) return;
  pane.classList.toggle("collapsed", !open);
  document.getElementById("drawer-toggle")?.setAttribute("aria-expanded", String(open));
}

// A taxon's trait records, as three small queries joined here. One grouped query with all the
// optional fields took up to 17 s for taxa with hundreds of records; these take under a second.
async function taxonRecords(T) {
  const [core, extra, numbers, labels] = await Promise.all([
    sparql(`SELECT ?r ?label ?organ ?trait ?source ?status ?text ?quality ?bearer ?negated WHERE {
      ?r fb:taxon ${T} . ?r a fb:TraitRecord ; rdfs:label ?label ; fb:organGroup ?organ ; fb:traitGroup ?trait ;
         fb:source ?s ; fb:status ?status ; fb:text ?text ; fb:quality ?quality ; fb:bearer ?bearer ; fb:negated ?negated . ?s rdfs:label ?source }`),
    sparql(`SELECT ?r ?context ?qualifier ?attribute ?fac ?fclass ?unit ?relation ?from ?to ?fromText ?toText WHERE {
      ?r a fb:TraitRecord ; fb:taxon ${T} . OPTIONAL { ?r fb:context ?context } OPTIONAL { ?r fb:qualifier ?qualifier }
      OPTIONAL { ?r fb:attribute ?attribute } OPTIONAL { ?r fb:phenotypeClass ?fac } OPTIONAL { ?r fb:flopoClass ?fclass }
      OPTIONAL { ?r fb:unit ?unit } OPTIONAL { ?r fb:relation ?relation ; fb:fromValue ?from ; fb:toValue ?to .
        OPTIONAL { ?r fb:fromText ?fromText } OPTIONAL { ?r fb:toText ?toText } } }`),
    // the numbers of a record are asked apart: with the other optional fields in one query the answer takes seconds
    sparql(`SELECT ?r ?usym ?low ?high WHERE { ?r a fb:TraitRecord ; fb:taxon ${T} . OPTIONAL { ?r fb:unitSymbol ?usym } OPTIONAL { ?r fb:low ?low } OPTIONAL { ?r fb:high ?high } }`),
    sparql(`SELECT DISTINCT ?x ?l WHERE { ?r a fb:TraitRecord ; fb:taxon ${T} .
      { ?r fb:quality ?x } UNION { ?r fb:bearer ?x } UNION { ?r fb:fromValue ?x } UNION { ?r fb:toValue ?x }
      UNION { ?r fb:unit ?x } UNION { ?r fb:flopoClass ?x } UNION { ?r fb:attribute ?x } ?x rdfs:label ?l }`),
  ]);
  const label = new Map(labels.map((x) => [x.x, x.l]));
  const byR = new Map();
  for (const row of core) if (!byR.has(row.r)) byR.set(row.r, { ...row });
  for (const row of [...extra, ...numbers]) {
    const rec = byR.get(row.r);
    if (!rec) continue;
    for (const [k, v] of Object.entries(row)) if (v !== undefined && rec[k] === undefined) rec[k] = v;
  }
  return [...byR.values()].map((r) => ({
    ...r, qlabel: label.get(r.quality), blabel: label.get(r.bearer), fromLabel: r.from && label.get(r.from),
    toLabel: r.to && label.get(r.to), unitLabel: r.unit && label.get(r.unit), flabel: r.fclass && label.get(r.fclass), alabel: r.attribute && label.get(r.attribute),
  }));
}

async function taxonPage(t) {
  const T = iriLiteral(t);
  // Taxa are keyed by their accepted IPNI name; an older WFO-keyed address forwards to its taxon.
  if (!/\/taxon\/(ipni|wcvp)-/.test(t)) {
    const moved = await sparql(`SELECT ?n WHERE { ?n dcterms:replaces ${T} } LIMIT 1`);
    if (moved.length) {
      location.replace(taxonHref(moved[0].n));
      return;
    }
  }
  const [g, info, names, allRecords, merged, places, growth, pending, notes, conflicts] = await Promise.all([
    groups(),
    sparql(`SELECT (SAMPLE(?l) AS ?label) (SAMPLE(?a) AS ?auth) (SAMPLE(?f) AS ?family) (SAMPLE(?o) AS ?order) (SAMPLE(?w) AS ?wfo) (SAMPLE(?ip) AS ?ipni)
      (GROUP_CONCAT(DISTINCT ?ar; separator="، ") AS ?arabic) (SAMPLE(?elo) AS ?emin) (SAMPLE(?ehi) AS ?emax) (SAMPLE(?nr) AS ?range) WHERE {
      ${T} rdfs:label ?l . OPTIONAL { ${T} fb:authorship ?a } OPTIONAL { ${T} fb:family ?f } OPTIONAL { ${T} fb:order ?o }
      OPTIONAL { ${T} fb:wfo ?w } OPTIONAL { ${T} fb:ipni ?ip } OPTIONAL { ${T} fb:vernacularName ?ar } OPTIONAL { ${T} fb:nativeRange ?nr }
      OPTIONAL { ${T} fb:elevationMin ?elo ; fb:elevationMax ?ehi } }`),
    sparql(`SELECT ?name ?src (GROUP_CONCAT(DISTINCT ?page; separator=", ") AS ?pages) (SAMPLE(?st) AS ?status) (SAMPLE(?sn) AS ?standard) (SAMPLE(?ni) AS ?ipni) WHERE {
      ${T} fb:printedName ?pn . ?pn fb:name ?name ; fb:source/rdfs:label ?src .
      OPTIONAL { ?pn fb:page ?page } OPTIONAL { ?pn fb:nameStatus ?st } OPTIONAL { ?pn fb:standardName ?sn } OPTIONAL { ?pn fb:ipni ?ni } } GROUP BY ?name ?src`),
    taxonRecords(T),
    sparql(`SELECT ?m (SAMPLE(?l) AS ?label) (SAMPLE(?b) AS ?bearer) (SAMPLE(?a) AS ?attribute) (SAMPLE(?pc) AS ?fac)
      (SAMPLE(?u) AS ?unit) (SAMPLE(?n) AS ?sources) (GROUP_CONCAT(STR(?mem); separator=" ") AS ?members) WHERE {
      ?m a fb:MergedTrait ; fb:taxon ${T} ; rdfs:label ?l ; fb:bearer ?b ; fb:attribute ?a ; fb:phenotypeClass ?pc ;
         fb:unit ?u ; fb:sourceCount ?n ; fb:member ?mem } GROUP BY ?m`),
    sparql(`SELECT ?region (SAMPLE(?rl) AS ?rlabel) ?loc (SAMPLE(?lat) AS ?la) (SAMPLE(?lon) AS ?lo) (GROUP_CONCAT(DISTINCT ?src; separator="|") AS ?sources) WHERE {
      ?o a fb:Occurrence ; fb:taxon ${T} ; fb:source/rdfs:label ?src .
      OPTIONAL { ?o fb:region ?region . ?region rdfs:label ?rl } OPTIONAL { ?o fb:locality ?loc }
      OPTIONAL { ?o fb:lat ?lat ; fb:lon ?lon } } GROUP BY ?region ?loc`),
    sparql(`SELECT ?label ?source (GROUP_CONCAT(DISTINCT ?v; separator="; ") AS ?value) WHERE {
      ?g a fb:GrowthTrait ; fb:taxon ${T} ; rdfs:label ?label ; fb:value ?v ; fb:source/rdfs:label ?source FILTER(lang(?v) = "") } GROUP BY ?label ?source`),
    sparql(`SELECT ?text ?reason ?context ?src WHERE { ?p a fb:PendingStatement ; fb:taxon ${T} ; fb:text ?text ; fb:reason ?reason ;
      fb:source/rdfs:label ?src . OPTIONAL { ?p fb:context ?context } }`),
    sparql(`SELECT ?kind ?text ?src WHERE { VALUES ?kind { fb:abundance fb:habitat } ${T} ?kind ?node . ?node rdfs:label ?text ; fb:source/rdfs:label ?src }`),
    sparql(`SELECT ?c (SAMPLE(?k) AS ?kind) (SAMPLE(?cm) AS ?note) (SAMPLE(?bs) AS ?between) (GROUP_CONCAT(STR(?m); separator=" ") AS ?members) WHERE {
      ?c a fb:Conflict ; fb:taxon ${T} ; fb:kind ?k ; rdfs:comment ?cm ; fb:betweenSources ?bs ; fb:member ?m } GROUP BY ?c`),
  ]);
  const pane = document.getElementById("tpane");
  if (!pane) return;
  const i = info[0] || {};
  setTitle(i.label || "Taxon");
  // Records that failed a check are not traits: they are listed apart, below the table.
  const records = allRecords.filter((r) => r.status !== "blocked");
  const blocked = allRecords.filter((r) => r.status === "blocked");
  const nameRows = names
    .map((x) => `<li><span class="sci">${esc(x.name)}</span> <span class="chip ${sourceClass(x.src)}">${esc(x.src)}</span>${x.pages ? ` <span class="muted">p. ${esc(x.pages)}</span>` : ""}${x.standard && x.standard !== x.name ? ` <span class="muted">IPNI: <a href="https://www.ipni.org/n/${esc(x.ipni)}" target="_blank" rel="noopener"><i>${esc(x.standard)}</i></a></span>` : ""}${x.status && !["accepted", "exact", "n/a"].includes(x.status.toLowerCase()) ? ` <span class="muted">(${esc(x.status.toLowerCase())} in ${x.ipni || x.standard ? "WCVP" : "WFO"})</span>` : ""}</li>`)
    .join("");

  // fingerprint
  const fpCells = [];
  for (const r of records) {
    let c = fpCells.find((x) => x.og === r.organ && x.tg === r.trait);
    if (!c) fpCells.push((c = { og: r.organ, tg: r.trait, value: 0 }));
    c.value += 1;
  }
  fpCells.forEach((c) => (c.title = `${c.value} records`));

  // traits grouped by organ
  const byOrgan = new Map(g.organs.map((o) => [o.g, []]));
  for (const r of records) (byOrgan.get(r.organ) || byOrgan.set(r.organ, []).get(r.organ)).push(r);
  let rowId = 0;
  const STATUS_TIP = "Admitted for review, not yet accepted by the checks";
  const amount = (v) => Number(v).toLocaleString("en", { maximumFractionDigits: 6 });
  // What the record says, in the order of what it carries: a relation, then numbers with their unit,
  // then the class of the annotation, then the quality; "not" comes first in each case.
  const valueCell = (r) => {
    const not = r.negated === "true" ? `<span class="muted">not</span> ` : "";
    if (r.relation) {
      const kind = { continuum: "continuum", taxon_level_alternatives: "alternatives in the taxon", temporal_transition: "change over time" }[r.relation] || r.relation;
      const end = (iri, label, verbatim) => {
        const link = termLink(iri, label || curie(iri));
        return verbatim && label && verbatim.toLowerCase() !== label.toLowerCase() ? `${link} <span class="muted">“${esc(verbatim)}”</span>` : link;
      };
      return `${not}${end(r.from, r.fromLabel, r.fromText)} → ${end(r.to, r.toLabel, r.toText)} <span class="muted">(${esc(kind)})</span>`;
    }
    if (r.low !== undefined || r.high !== undefined) {
      const range = r.low !== undefined && r.high !== undefined ? (+r.low === +r.high ? amount(r.low) : `${amount(r.low)}–${amount(r.high)}`)
        : r.low !== undefined ? `at least ${amount(r.low)}` : `up to ${amount(r.high)}`;
      const unit = r.usym !== undefined ? r.usym : r.unit && !/^(count unit|ratio)$/.test(r.unitLabel || "") ? r.unitLabel || "" : "";
      const what = r.attribute || r.quality;
      return `${not}<span class="num">${esc(`${range} ${unit}`.trim())}</span> <span class="muted">${termLink(what, r.alabel || r.qlabel || curie(what))}</span>`;
    }
    if (r.unit) return `${not}${termLink(r.attribute || r.quality, r.alabel || r.qlabel || curie(r.quality))} <span class="muted">in</span> ${termLink(r.unit, r.unitLabel || curie(r.unit))}`;
    if (r.fclass) return not + termLink(r.fclass, r.flabel || curie(r.fclass));
    return not + termLink(r.quality, r.qlabel || curie(r.quality));
  };
  const owlLink = (iri) => iri ? ` <a href="#/query?describe=${encodeURIComponent(iri)}" title="OWL definition of the annotation class">OWL class</a>` : "";
  // Contradictions come as pairs. They are grouped by the statement that most of them concern
  // (a leaf stated absent against every leaf statement of the other floras is one group).
  const byIriAll = new Map(allRecords.map((r) => [r.r, r]));
  const conflictOf = new Map();
  const pairs = conflicts
    .map((c) => ({ c, members: c.members.split(" ").map((x) => byIriAll.get(x)).filter(Boolean) }))
    .filter(({ members }) => members.length && members.every((m) => m.status !== "blocked"));
  const weight = new Map();
  for (const { c, members } of pairs) {
    members.forEach((m) => {
      (conflictOf.get(m.r) || conflictOf.set(m.r, []).get(m.r)).push(c.note);
      weight.set(m.r, (weight.get(m.r) || 0) + 1);
    });
  }
  const conflictGroups = new Map();
  for (const pair of pairs) {
    const anchor = pair.members.reduce((best, m) => (weight.get(m.r) > weight.get(best.r) ? m : best));
    (conflictGroups.get(anchor.r) || conflictGroups.set(anchor.r, { anchor, pairs: [] }).get(anchor.r)).pairs.push({ ...pair, others: pair.members.filter((m) => m !== anchor) });
  }
  const chipOf = (m) => `<b>${esc(m.label)}</b> <span class="chip ${sourceClass(m.source)}">${esc(m.source)}</span>`;
  const sayWhere = (c) => `${esc(c.kind)}, ${c.between === "true" ? "the sources disagree" : "within one source"}: ${esc(c.note)}`;
  const conflictHtml = [...conflictGroups.values()].sort((a, b) => b.pairs.length - a.pairs.length || a.anchor.label.localeCompare(b.anchor.label)).map((grp) => {
    if (grp.pairs.length === 1) {
      const { c, members } = grp.pairs[0];
      return `<li>${members.map(chipOf).join(` <span class="muted">versus</span> `)}<br><span class="muted">${sayWhere(c)}</span></li>`;
    }
    return `<li>${chipOf(grp.anchor)} <span class="muted">is contradicted by ${n(grp.pairs.length)} statements</span>
      <details><summary>Show them</summary><ul>${grp.pairs.map(({ c, others }) => `<li>${others.map(chipOf).join(", ")}<br><span class="muted">${sayWhere(c)}</span></li>`).join("")}</ul></details></li>`;
  });
  const CONFLICT_SHOWN = 5;
  const conflictBox = pairs.length ? `<div class="conflicts"><h3>${n(pairs.length)} contradiction${pairs.length > 1 ? "s" : ""}, in ${n(conflictHtml.length)} group${conflictHtml.length > 1 ? "s" : ""}</h3>
    <p class="muted">These statements cannot both be true of one plant. A taxon covers many plants, so the sources may describe different plants or one may be wrong.</p>
    <ul>${conflictHtml.slice(0, CONFLICT_SHOWN).join("")}</ul>
    ${conflictHtml.length > CONFLICT_SHOWN ? `<details class="more"><summary>${n(conflictHtml.length - CONFLICT_SHOWN)} more group${conflictHtml.length - CONFLICT_SHOWN > 1 ? "s" : ""}</summary><ul>${conflictHtml.slice(CONFLICT_SHOWN).join("")}</ul></details>` : ""}</div>` : "";
  const recordRow = (r, sub = false) => {
    const id = `d${rowId++}`;
    const clash = conflictOf.has(r.r) ? ` <span class="chip conflict" title="${esc(conflictOf.get(r.r).join("; "))}">conflict</span>` : "";
    const status = (r.status === "accepted" ? "" : `<span class="chip review" title="${STATUS_TIP}">${esc(r.status)}</span>`) + clash;
    return `<tr class="rec${sub ? " sub" : ""}" data-detail="${id}"><td class="q"><button type="button" class="rowtoggle" aria-expanded="false" aria-controls="${id}"><span class="chev" aria-hidden="true">▸</span><span>${sub ? "↳ " : ""}${esc(r.label)}${r.qualifier ? ` <span class="muted">(${esc(r.qualifier)})</span>` : ""}</span></button></td>
      <td>${valueCell(r)}</td>
      <td><span class="chip ${sourceClass(r.source)}">${esc(r.source)}</span> ${status} <span class="tally" data-tally="${esc(r.r)}"></span></td></tr>
      <tr class="detail" id="${id}" hidden><td colspan="3">${highlight(r.context, r.text)}<br>
        <span class="muted">Annotation <a href="#/query?describe=${encodeURIComponent(r.r)}">${esc(local(r.r))}</a>: bearer ${termLink(r.bearer, r.blabel || curie(r.bearer))}${r.relation ? "" : `, quality ${termLink(r.quality, r.qlabel || curie(r.quality))}`}${r.unit ? `, unit ${termLink(r.unit, r.unitLabel || curie(r.unit))}` : ""}${r.fclass ? `, FLOPO class ${termLink(r.fclass, r.flabel || curie(r.fclass))}` : ""}${owlLink(r.fac)}</span>
        <div class="review" data-record="${esc(r.r)}"></div></td></tr>`;
  };
  const byIri = new Map(records.map((r) => [r.r, r]));
  const inMerged = new Set();
  const mergedByOrgan = new Map();
  for (const m of merged) {
    if (!m.m || !m.members) continue;
    const members = m.members.split(" ").map((x) => byIri.get(x)).filter(Boolean);
    if (!members.length) continue;
    members.forEach((x) => inMerged.add(x.r));
    const og = members[0].organ;
    (mergedByOrgan.get(og) || mergedByOrgan.set(og, []).get(og)).push({ ...m, members });
  }
  const traitRows = [...byOrgan]
    .filter(([og, list]) => list.length)
    .map(([og, list]) => {
      list.sort((a, b) => a.trait.localeCompare(b.trait) || a.label.localeCompare(b.label));
      const mergedRows = (mergedByOrgan.get(og) || []).map((m) => `<tr class="merged"><td class="q"><b>${esc(m.label)}</b></td>
          <td>range over ${m.members.length} values from ${m.sources} source${m.sources > 1 ? "s" : ""}${owlLink(m.fac)}</td><td></td></tr>`
          + m.members.map((x) => recordRow(x, true)).join("")).join("");
      return `<tr><th colspan="3" scope="colgroup">${esc(g.label[og] || "Other")}</th></tr>` + mergedRows
        + list.filter((r) => !inMerged.has(r.r)).map((r) => recordRow(r)).join("");
    })
    .join("");

  const regions = new Map();
  for (const p of places) if (p.region) regions.set(p.region, p.rlabel);
  const points = places.filter((p) => p.la && p.lo);
  const localities = [...new Set(places.filter((p) => p.loc).map((p) => p.loc))];
  const notesHtml = notes.map((x) => `<dt>${x.kind.endsWith("abundance") ? "Abundance" : "Habitat"}</dt><dd>${esc(x.text)} <span class="chip ${sourceClass(x.src)}">${esc(x.src)}</span></dd>`).join("");
  // Each condition of growth keeps the flora that states it.
  const growthBy = new Map();
  for (const x of growth) (growthBy.get(x.label) || growthBy.set(x.label, []).get(x.label)).push(x);
  const growthHtml = [...growthBy].map(([label, rows]) => `<dt>${esc(label)}</dt><dd>${rows.map((x) => `<div>${esc(x.value)} <span class="chip ${sourceClass(x.source)}">${esc(x.source)}</span></div>`).join("")}</dd>`).join("");
  const blockedHtml = blocked.length ? `<details class="pending blocked"><summary>Not used: failed a check (${n(blocked.length)})</summary>
    <p class="muted">These statements failed an automatic check. They are kept for the record and are not counted as traits.</p>
    <ul>${blocked.map((r) => `<li><b>${esc(r.label)}</b> <span class="chip ${sourceClass(r.source)}">${esc(r.source)}</span><br>${highlight(r.context, r.text)}</li>`).join("")}</ul></details>` : "";

  pane.innerHTML = html`
    <div class="taxon-head">
      <h1>${esc(i.label)}</h1>
      ${i.auth ? `<div class="auth">${esc(i.auth)}</div>` : ""}
      <div class="taxon-meta">
        ${i.family ? `<span>${esc(i.family)}${i.order ? `, ${esc(i.order)}` : ""}</span>` : ""}
        ${i.arabic ? `<span class="ar" lang="ar">${esc(i.arabic)}</span>` : ""}
        ${i.ipni ? `<a href="https://powo.science.kew.org/taxon/urn:lsid:ipni.org:names:${esc(i.ipni)}" target="_blank" rel="noopener">POWO</a> <a href="https://www.ipni.org/n/${esc(i.ipni)}" target="_blank" rel="noopener">IPNI ${esc(i.ipni)}</a>` : `<span>Not matched to IPNI</span>`}
        ${i.wfo ? `<a href="https://list.worldfloraonline.org/${esc(i.wfo)}" target="_blank" rel="noopener">World Flora Online ${esc(i.wfo)}</a>` : ""}
      </div>
    </div>
    <div id="inat-panel"></div>
    <div class="taxon-grid">
      <div>
        <h2>Traits</h2>
        ${conflictBox}
        ${records.length ? `<p class="muted">${n(records.length)} annotations. Select a row to see the sentence it was read from, and to say whether the annotation is right.</p><p class="reviewbar" id="reviewbar" hidden></p><div class="tablewrap"><table class="traits"><thead><tr><th scope="col">Statement</th><th scope="col">Value</th><th scope="col">Source and review</th></tr></thead><tbody>${traitRows}</tbody></table></div>` : `<p class="muted">No trait annotations yet.</p>`}
        ${blockedHtml}
        ${pending.length ? `<details class="pending"><summary>${n(pending.length)} statements not yet annotated</summary><ul>${pending.map((p) => `<li>${highlight(p.context, p.text)} <span class="muted">— ${esc(p.reason.replace(/_/g, " "))}</span></li>`).join("")}</ul></details>` : ""}
      </div>
      <div>
        <h2>Trait fingerprint</h2>
        <div class="fingerprint tablewrap" tabindex="0" role="region" aria-label="Trait fingerprint">${records.length ? atlasTable(fpCells, g.organs, g.traits, { link: false, short: true }) : `<p class="muted">Nothing to show.</p>`}</div>
        <h2>Where it grows</h2>
        ${regions.size ? `<div class="regions">${[...regions].map(([, l]) => `<span class="region on">${esc(l)}</span>`).join("")}</div>` : `<p class="muted">No region recorded.</p>`}
        ${points.length ? `<div class="map" id="map" role="img" aria-label="Map of recorded localities"></div>` : ""}
        ${localities.length ? `<p class="muted" style="font-size:.88rem">Localities: ${localities.map(esc).join("; ")}</p>` : ""}
        ${i.emin ? `<p>Elevation ${n(i.emin)}${i.emax !== i.emin ? `–${n(i.emax)}` : ""} m</p>` : ""}
        ${notesHtml || i.range ? `<h3>Notes</h3><dl class="kv">${i.range ? `<dt>Native range</dt><dd>${esc(i.range)}</dd>` : ""}${notesHtml}</dl>` : ""}
        ${growthHtml ? `<h3>Ecology and cultivation</h3><dl class="kv">${growthHtml}</dl>` : ""}
        <h3>Names in the sources</h3><ul>${nameRows}</ul>
        <p><a href="#/compare/${encodeURIComponent(taxonKey(t))}">Compare with another taxon</a> · <a href="#/query?taxon=${encodeURIComponent(t)}">Query this taxon in SPARQL</a></p>
      </div>
    </div>`;
  const photoPane = pane.querySelector("#inat-panel");
  // The catalogue is optional: without a match (or without the catalogue) the taxon page has no photo block.
  inaturalistData().then((data) => {
    if (!photoPane.isConnected) return;
    photoPane.innerHTML = inaturalistPanel(data.taxa?.[t], i.label, data.generated);
    photoPane.querySelectorAll("img").forEach((img) => img.addEventListener("error", () => {
      img.replaceWith(Object.assign(document.createElement("span"), { textContent: "Photograph unavailable; open the source to view it." }));
    }));
  }).catch(() => { /* no photo block */ });
  setupReview(pane, t, records, i.label || taxonKey(t));
  pane.querySelectorAll("tr.rec").forEach((tr) => {
    const button = tr.querySelector("button.rowtoggle");
    const toggle = () => {
      const d = document.getElementById(tr.dataset.detail);
      d.hidden = !d.hidden;
      button.setAttribute("aria-expanded", String(!d.hidden));
      tr.classList.toggle("open", !d.hidden);
    };
    button.addEventListener("click", (e) => { e.stopPropagation(); toggle(); });
    tr.addEventListener("click", (e) => { if (!e.target.closest("a, button")) toggle(); });
  });
  if (points.length && window.L) {
    const map = L.map("map", { scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 12, attribution: "© OpenStreetMap contributors" }).addTo(map);
    const markers = points.map((p) => L.circleMarker([+p.la, +p.lo], { radius: 6, color: "#2f5d50", weight: 2, fillColor: "#b8862b", fillOpacity: 0.8 }).bindTooltip(esc(p.loc || p.rlabel || "")).addTo(map));
    map.fitBounds(L.featureGroup(markers).getBounds().pad(0.4), { maxZoom: 8 });
  }
}

/* ---------------------------------------------------------------- traits browser */
// Records that failed a check are not traits; every count and list of traits leaves them out.
const NOT_BLOCKED = `FILTER NOT EXISTS { ?r fb:status "blocked" }`;
const PAGE = 200;
async function traits(organKey, traitKey, valueKey, params = new URLSearchParams()) {
  const g = await groups();
  const og = organKey ? FB + organKey : "";
  const tg = traitKey ? FB + traitKey : "";
  setTitle(organKey ? `Traits: ${(g.label[og] || organKey).toLowerCase()}` : "Traits");
  setView(`<h1>Browse traits</h1><p class="muted">Search for a trait by any of its names (several words are fine: “yellow flower”), or choose a plant part, then a kind of trait, then a value to list the taxa that have it.</p>
    <div class="field"><label for="tsearch">Search traits by name or synonym</label><input id="tsearch" type="search" placeholder="e.g. shrub, awn, glabrous leaf, yellow flower" autocomplete="off" style="max-width:28rem;width:100%"></div>
    <div id="tsearch-results" aria-live="polite"></div>
    <div class="cols"><div id="c1"></div><div id="c2"></div><div id="c3"></div></div>
    <section id="trait-taxa" aria-live="polite"></section>`);
  const search = document.getElementById("tsearch");
  traitSearch(search, document.getElementById("tsearch-results"));
  if (params.get("q")) { search.value = params.get("q"); search.dispatchEvent(new Event("input")); }
  const organCounts = await precomputed("organCounts");
  const oc = Object.fromEntries(organCounts.map((r) => [r.og, r.n]));
  document.getElementById("c1").innerHTML = `<p class="col-title">Plant part</p><ul class="pick">${g.organs
    .filter((o) => oc[o.g])
    .map((o) => `<li><a class="${o.g === og ? "current" : ""}" href="#/traits/${local(o.g)}">${esc(o.label)}<small class="num">${n(oc[o.g])}</small></a></li>`)
    .join("")}</ul>`;
  if (!og) return;
  const traitCounts = await sparql(`SELECT ?tg (COUNT(DISTINCT ?t) AS ?n) WHERE { ?r a fb:TraitRecord ; fb:organGroup ${iriLiteral(og)} ; fb:traitGroup ?tg ; fb:taxon ?t . ${NOT_BLOCKED} } GROUP BY ?tg`);
  const tc = Object.fromEntries(traitCounts.map((r) => [r.tg, r.n]));
  document.getElementById("c2").innerHTML = `<p class="col-title">Kind of trait</p><ul class="pick">${g.traits
    .filter((t) => tc[t.g])
    .map((t) => `<li><a class="${t.g === tg ? "current" : ""}" href="#/traits/${organKey}/${local(t.g)}">${esc(t.label)}<small class="num">${n(tc[t.g])}</small></a></li>`)
    .join("")}</ul>`;
  if (!tg) { if (narrowScreen()) document.getElementById("c2").scrollIntoView({ block: "start" }); return; }
  const values = await sparql(`SELECT ?b ?q (SAMPLE(?bl) AS ?blabel) (SAMPLE(?ql) AS ?qlabel) (COUNT(DISTINCT ?t) AS ?n) WHERE {
    ?r a fb:TraitRecord ; fb:organGroup ${iriLiteral(og)} ; fb:traitGroup ${iriLiteral(tg)} ; fb:bearer ?b ; fb:quality ?q ; fb:taxon ?t ; fb:negated false .
    ?b rdfs:label ?bl . ?q rdfs:label ?ql . ${NOT_BLOCKED} } GROUP BY ?b ?q ORDER BY DESC(?n)`);
  const c3 = document.getElementById("c3");
  const selected = valueKey ? decodeURIComponent(valueKey) : "";
  const keyOf = (v) => `${local(v.b)}~${local(v.q)}`;
  // A long list is shown in pages; the page of the chosen value is always among them.
  let limit = Math.max(PAGE, Math.ceil((values.findIndex((v) => keyOf(v) === selected) + 1) / PAGE) * PAGE), vfilter = "";
  c3.innerHTML = `<p class="col-title">Value (part and quality), with number of taxa</p>
    ${values.length > 20 ? `<input id="vfilter" type="search" placeholder="Filter these ${n(values.length)} values" aria-label="Filter values" autocomplete="off" style="margin-bottom:.5rem;width:100%">` : ""}
    <ul class="pick" id="vlist"></ul><div id="vmore"></div>`;
  const drawValues = () => {
    const shown = values.filter((v) => !vfilter || `${v.blabel} ${v.qlabel}`.toLowerCase().includes(vfilter));
    document.getElementById("vlist").innerHTML = shown.slice(0, limit)
      .map((v) => `<li><a class="${keyOf(v) === selected ? "current" : ""}" href="#/traits/${organKey}/${traitKey}/${encodeURIComponent(keyOf(v))}">${esc(v.blabel)} ${esc(v.qlabel)}<small class="num">${n(v.n)}</small></a></li>`)
      .join("") || `<li class="muted">No value matches.</li>`;
    document.getElementById("vmore").innerHTML = shown.length > limit ? `<button type="button" class="ghost">Show ${n(Math.min(PAGE, shown.length - limit))} more of ${n(shown.length - limit)}</button>` : "";
    document.querySelector("#vmore button")?.addEventListener("click", () => { limit += PAGE; drawValues(); });
  };
  drawValues();
  document.getElementById("vfilter")?.addEventListener("input", (e) => { vfilter = e.target.value.trim().toLowerCase(); limit = PAGE; drawValues(); });
  if (!selected) { if (narrowScreen()) c3.scrollIntoView({ block: "start" }); return; }
  const [b, q] = selected.split("~");
  const box = document.getElementById("trait-taxa");
  if (!/^\w+$/.test(b || "") || !/^\w+$/.test(q || "")) { box.innerHTML = `<p class="muted">That value does not exist.</p>`; return; }
  box.innerHTML = `<p class="loading">Loading the taxa…</p>`;
  const taxaRows = await sparql(`SELECT ?t (SAMPLE(?l) AS ?label) (SAMPLE(?f) AS ?family) (GROUP_CONCAT(DISTINCT ?lab; separator="; ") AS ?values) (GROUP_CONCAT(DISTINCT ?src; separator="|") AS ?sources) WHERE {
    ?r a fb:TraitRecord ; fb:bearer obo:${b} ; fb:quality obo:${q} ; fb:organGroup ${iriLiteral(og)} ; fb:taxon ?t ; rdfs:label ?lab ; fb:negated false ; fb:source/rdfs:label ?src .
    ?t rdfs:label ?l . OPTIONAL { ?t fb:family ?f } ${NOT_BLOCKED} } GROUP BY ?t ORDER BY ?label`);
  const value = values.find((v) => keyOf(v) === selected);
  const row = (r) => `<tr><td><a class="sci" href="${taxonHref(r.t)}">${esc(r.label)}</a></td><td>${esc(r.family || "")}</td><td>${esc(r.values)}</td><td>${r.sources.split("|").map((s) => `<span class="chip ${sourceClass(s)}">${esc(s)}</span>`).join(" ")}</td></tr>`;
  box.innerHTML = `<h2>${esc(value ? value.blabel + " " + value.qlabel : selected)}: ${n(taxaRows.length)} taxa</h2>
    <div class="tablewrap"><table class="results"><thead><tr><th scope="col">Taxon</th><th scope="col">Family</th><th scope="col">Annotation</th><th scope="col">Source</th></tr></thead><tbody id="trows"></tbody></table></div>
    <div id="trmore"></div>`;
  let shownRows = 0;
  const more = () => {
    const next = taxaRows.slice(shownRows, shownRows + PAGE);
    document.getElementById("trows").insertAdjacentHTML("beforeend", next.map(row).join(""));
    shownRows += next.length;
    document.getElementById("trmore").innerHTML = shownRows < taxaRows.length ? `<button type="button" class="ghost">Show ${n(Math.min(PAGE, taxaRows.length - shownRows))} more of ${n(taxaRows.length - shownRows)}</button>` : "";
    document.querySelector("#trmore button")?.addEventListener("click", more);
  };
  more();
  box.querySelector("h2").scrollIntoView({ block: "nearest" });
}

/* Search by concept: a word is looked up in the labels and the synonyms (of every scope) of the
   ontology terms, so "shrub" finds 'frutescent habit' (synonym: shrub habit). Several words must each
   match the part or the quality ("yellow flower": yellow the colour, flower the part). The result
   lists the part-and-quality values that use matching terms, with the number of taxa. */
const positionedQuery = (part, quality) => `PREFIX fb: <${FB}>
PREFIX obo: <http://purl.obolibrary.org/obo/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
# Taxa with this quality on a part in a named position (pattern 18)
SELECT ?taxon ?annotation ?text ?source WHERE {
  ?r a fb:TraitRecord ; fb:positionedPart obo:${part} ; fb:quality obo:${quality} ; fb:negated false ;
     rdfs:label ?annotation ; fb:text ?text ; fb:taxon ?t ; fb:source/rdfs:label ?source .
  ?t rdfs:label ?taxon } ORDER BY ?taxon LIMIT 500`;

const traitData = () =>
  cached("traitData", async () => {
    const [values, names, positioned] = await Promise.all([precomputed("traitValues"), precomputed("termNames"), precomputed("positionedValues")]);
    const label = {}, all = {};
    for (const t of names) { label[t.id] = t.label; all[t.id] = [t.label, ...(t.names ? t.names.split("|") : [])]; }
    return { values, positioned, label, all };
  });
// How a word matches a term: 0 as a word of its label, 0.5 as a word of a synonym, 1 and 1.5 inside a label or a synonym.
function termMatch(all, word) {
  let best = null;
  (all || []).forEach((x, i) => {
    const l = x.toLowerCase();
    const rank = l === word || l.split(/[^a-z0-9]+/).includes(word) ? (i ? 0.5 : 0) : l.includes(word) ? (i ? 1.5 : 1) : null;
    if (rank !== null && (!best || rank < best.rank)) best = { name: x, rank };
  });
  return best;
}
function findTraits(query, data) {
  const words = query.toLowerCase().split(/\s+/).filter((w) => w.length > 1);
  if (!words.length) return [];
  const memo = new Map();
  const match = (id, w) => {
    const k = id + "|" + w;
    if (!memo.has(k)) memo.set(k, termMatch(data.all[id], w));
    return memo.get(k);
  };
  const score = (p, v, needPart) => {
    let rank = 0, onPart = 0, onQuality = 0;
    const found = [];
    for (const w of words) {
      const a = match(p, w), b = match(v, w);
      if (!a && !b) return null;
      const useQuality = b && (!a || b.rank <= a.rank);
      const m = useQuality ? b : a;
      if (useQuality) onQuality++; else onPart++;
      rank += m.rank;
      if (!found.includes(m.name)) found.push(m.name);
    }
    if (needPart && !words.some((w) => match(p, w))) return null;
    return { rank: rank - (onPart && onQuality ? 0.5 : 0), found };
  };
  const rows = [];
  for (const r of data.values) { const s = score(r.p, r.v, false); if (s) rows.push({ ...r, ...s, n: +r.n }); }
  // a part in a position that has a name ('basal leaf', 'lateral vein'): found by that name only
  for (const r of data.positioned) { const s = score(r.p, r.v, true); if (s) rows.push({ ...r, ...s, n: +r.n, named: true }); }
  return rows.sort((a, b) => a.rank - b.rank || b.n - a.n);
}
const traitHref = (r) => (r.named ? "#/query?q=" + encodeURIComponent(positionedQuery(r.p, r.v)) : `#/traits/${r.o}/${r.g}/${encodeURIComponent(r.p + "~" + r.v)}`);

function traitSearch(input, box) {
  let timer = 0;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = input.value.trim().toLowerCase();
      if (q.length < 3) { box.innerHTML = ""; return; }
      box.innerHTML = `<p class="muted">Searching…</p>`;
      let data;
      try { data = await traitData(); } catch (err) { box.innerHTML = `<p class="error">${esc(err.message)}</p>`; return; }
      if (input.value.trim().toLowerCase() !== q) return;
      const all = findTraits(q, data);
      const rows = all.slice(0, 60);
      box.innerHTML = rows.length
        ? `<div class="tablewrap"><table class="results"><thead><tr><th scope="col">Trait</th><th scope="col">Found as</th><th scope="col" class="num">Taxa</th></tr></thead><tbody>${rows
            .map((r) => `<tr><td><a href="${esc(traitHref(r))}">${esc(data.label[r.p] || r.p)} ${esc(data.label[r.v] || r.v)}</a></td><td class="muted">${esc(r.found.join(" · "))}</td><td class="num">${n(r.n)}</td></tr>`)
            .join("")}</tbody></table></div>${all.length > rows.length ? `<p class="muted">The first ${rows.length} of ${n(all.length)}; add a word to narrow the list.</p>` : ""}`
        : `<p class="muted">No trait has a name or synonym with ${q.includes(" ") ? "each of these words: " : ""}“${esc(q)}”.</p>`;
    }, 250);
  });
}

/* The search box of the overview: taxa (names, families, names printed in floras) and traits, as one
   short list while typing. The taxon index and the trait names load when the box is first used. */
function homeSearch() {
  const form = document.getElementById("home-form"), input = document.getElementById("home-search"), box = document.getElementById("home-results");
  if (!input) return;
  let timer = 0, token = 0, first = "";
  const warm = () => { taxonIndex().catch(() => {}); traitData().catch(() => {}); };
  input.addEventListener("focus", warm, { once: true });
  const run = async () => {
    const q = input.value.trim();
    const mine = ++token;
    first = "";
    if (q.length < 2) { box.innerHTML = ""; return; }
    box.innerHTML = `<p class="muted">Searching…</p>`;
    let index, data;
    try { [index, data] = await Promise.all([taxonIndex(), traitData()]); } catch (err) { if (mine === token) box.innerHTML = `<p class="error">${esc(err.message)}</p>`; return; }
    if (mine !== token || !input.isConnected) return;
    const lower = q.toLowerCase();
    const found = taxonMatches(index, q, "");
    const rank = (r) => (r.label.toLowerCase().startsWith(lower) ? 0 : 1) + (r.n > 0 ? 0 : 2);
    const taxa = found.sort((a, b) => rank(a) - rank(b) || b.n - a.n).slice(0, 6);
    const kinds = findTraits(q, data);
    const traitRows = kinds.slice(0, 6);
    const list = [];
    const taxaHtml = taxa.length ? `<h3>Taxa</h3><ul>${taxa.map((r) => {
      const syn = matchedSynonym(r, q);
      list.push(taxonHref(r.t));
      return `<li><a href="${taxonHref(r.t)}"><span class="sci">${esc(r.label)}${syn ? ` <span class="syn">= ${esc(syn)}</span>` : ""}</span>${r.family ? ` <span class="muted">${esc(r.family)}</span>` : ""}<small class="num">${r.n ? `${n(r.n)} records` : "no records"}</small></a></li>`;
    }).join("")}</ul>${found.length > taxa.length ? `<a href="#/taxa" id="home-all">All ${n(found.length)} matching taxa</a>` : ""}` : "";
    const traitHtml = traitRows.length ? `<h3>Traits</h3><ul>${traitRows.map((r) => {
      list.push(traitHref(r));
      return `<li><a href="${esc(traitHref(r))}">${esc(data.label[r.p] || r.p)} ${esc(data.label[r.v] || r.v)}<small class="num">${n(r.n)} taxa</small></a></li>`;
    }).join("")}</ul>${kinds.length > traitRows.length ? `<a href="#/traits?q=${encodeURIComponent(q)}">All ${n(kinds.length)} matching traits</a>` : ""}` : "";
    first = list[0] || "";
    box.innerHTML = taxaHtml || traitHtml ? `<div class="home-cols"><div>${taxaHtml}</div><div>${traitHtml}</div></div>` : `<p class="muted">Nothing matches “${esc(q)}”. Try fewer words, or a family name.</p>`;
    document.getElementById("home-all")?.addEventListener("click", () => {
      try { sessionStorage.setItem("taxonFilter", q); sessionStorage.setItem("taxonSourceFilter", ""); sessionStorage.setItem("taxonShowAll", "0"); } catch (e) { /* storage unavailable */ }
    });
  };
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 150); });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearTimeout(timer);
    await run();
    if (first) location.hash = first.replace(/^#/, "");
  });
  // arrow keys move between the box and the results
  const links = () => [...box.querySelectorAll("a")];
  form.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "Escape") return;
    const all = links(), at = all.indexOf(document.activeElement);
    if (e.key === "Escape") { input.focus(); return; }
    e.preventDefault();
    const next = e.key === "ArrowDown" ? at + 1 : at - 1;
    if (next < 0) input.focus(); else if (all[next]) all[next].focus();
  });
}

/* ---------------------------------------------------------------- identify */
const valueChoices = () => precomputed("valueChoices");

async function identify() {
  setTitle("Identify");
  const [g, choices] = await Promise.all([groups(), valueChoices()]);
  const organs = g.organs.filter((o) => choices.some((c) => c.og === o.g));
  // the values of each plant part, the ones that many taxa have first
  const byOrgan = new Map(organs.map((o) => [o.g, choices.filter((c) => c.og === o.g).map((c) => ({ ...c, n: +c.n })).sort((a, b) => b.n - a.n || a.label.localeCompare(b.label))]));
  const conditionHtml = (i) => `<div class="condition" data-i="${i}">
      <div class="field"><label for="og${i}">Plant part</label><select id="og${i}">${organs.map((o) => `<option value="${o.g}">${esc(o.label)}</option>`).join("")}</select></div>
      <div class="field"><label for="q${i}">Value</label><input id="qf${i}" type="search" class="qfilter" placeholder="Type to filter the values" aria-label="Filter the values of this plant part" autocomplete="off"><select id="q${i}"></select></div>
      <button type="button" class="ghost" data-remove="${i}" aria-label="Remove this condition">Remove</button></div>`;
  setView(`<h1>Identify</h1><p class="muted">Describe a plant by the traits you can see. Taxa are ranked by how many of your traits their annotations state; a colour also matches its shades (pale yellow matches yellow).</p>
    <div class="conditions" id="conds"></div>
    <div class="toolbar"><button type="button" class="ghost" id="add">Add a trait</button><button type="button" id="run">Find taxa</button></div>
    <div id="idresults" aria-live="polite"></div>`);
  const conds = document.getElementById("conds");
  let next = 0;
  const fill = (i) => {
    const og = document.getElementById("og" + i).value;
    const select = document.getElementById("q" + i);
    const filter = document.getElementById("qf" + i).value.trim().toLowerCase();
    const all = byOrgan.get(og) || [];
    const list = all.filter((c) => !filter || c.label.toLowerCase().includes(filter));
    const prev = select.value;
    select.innerHTML = `<option value="">Choose a value${filter ? ` (${n(list.length)} of ${n(all.length)} match)` : ` (${n(all.length)})`}</option>` +
      list.map((c) => `<option value="${esc(c.q)}"${c.q === prev ? " selected" : ""}>${esc(c.label)} (${n(c.n)} taxa)</option>`).join("");
    document.getElementById("qf" + i).hidden = all.length <= 12;
  };
  const add = (organ) => {
    const i = next++;
    conds.insertAdjacentHTML("beforeend", conditionHtml(i));
    if (organ) document.getElementById("og" + i).value = organ;
    fill(i);
    document.getElementById("og" + i).addEventListener("change", () => { document.getElementById("qf" + i).value = ""; fill(i); });
    document.getElementById("qf" + i).addEventListener("input", () => fill(i));
    conds.querySelector(`[data-remove="${i}"]`).addEventListener("click", () => conds.querySelector(`[data-i="${i}"]`).remove());
  };
  add(FB + "organ-flower");
  add(FB + "organ-plant");
  document.getElementById("add").addEventListener("click", () => add());
  document.getElementById("run").addEventListener("click", async () => {
    const picked = [...conds.querySelectorAll(".condition")].map((c) => ({ og: c.querySelector("select[id^=og]").value, q: c.querySelector("select[id^=q]").value })).filter((c) => c.q);
    const out = document.getElementById("idresults");
    if (!picked.length) { out.innerHTML = `<p class="muted">Choose a value for at least one trait.</p>`; return; }
    out.innerHTML = `<p class="loading">Searching…</p>`;
    const values = picked.map((c, i) => `(${i} ${iriLiteral(c.og)} ${iriLiteral(c.q)})`).join(" ");
    const rows = await sparql(`SELECT ?t (SAMPLE(?l) AS ?label) (SAMPLE(?f) AS ?family) (COUNT(DISTINCT ?i) AS ?hits) (GROUP_CONCAT(DISTINCT STR(?i); separator=",") AS ?which) (GROUP_CONCAT(DISTINCT ?lab; separator="; ") AS ?evidence) WHERE {
      VALUES (?i ?og ?q) { ${values} }
      ?r a fb:TraitRecord ; fb:organGroup ?og ; fb:quality ?rq ; fb:taxon ?t ; fb:negated false ; rdfs:label ?lab .
      ?rq rdfs:subClassOf* ?q . ${NOT_BLOCKED}
      ?t rdfs:label ?l . OPTIONAL { ?t fb:family ?f } } GROUP BY ?t ORDER BY DESC(?hits) ?label LIMIT 200`);
    out.innerHTML = rows.length
      ? `<p class="muted">${n(rows.filter((r) => +r.hits === picked.length).length)} taxa state all ${picked.length} traits.</p><div class="tablewrap"><table class="results"><thead><tr><th scope="col">Match</th><th scope="col">Taxon</th><th scope="col">Family</th><th scope="col">Matching annotations</th></tr></thead><tbody>${rows
          .map((r) => {
            const hit = new Set(r.which.split(","));
            return `<tr><td><span class="score" role="img" aria-label="${r.hits} of ${picked.length} traits matched" title="${r.hits} of ${picked.length}">${picked.map((_, i) => `<i class="${hit.has(String(i)) ? "hit" : ""}"></i>`).join("")}</span> <span class="num muted" aria-hidden="true">${r.hits}/${picked.length}</span></td><td><a class="sci" href="${taxonHref(r.t)}">${esc(r.label)}</a></td><td>${esc(r.family || "")}</td><td>${esc(r.evidence)}</td></tr>`;
          })
          .join("")}</tbody></table></div>`
      : `<p class="muted">No taxon states any of these traits. Try a broader quality.</p>`;
  });
}

/* ---------------------------------------------------------------- query */
const EXAMPLES = {
  "Taxa with yellow flowers (including shades of yellow)": `PREFIX fb: <${FB}>
PREFIX obo: <http://purl.obolibrary.org/obo/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT DISTINCT ?taxon ?name ?annotation WHERE {
  ?r a fb:TraitRecord ; fb:taxon ?taxon ; fb:bearer obo:PO_0009046 ;
     fb:quality ?colour ; rdfs:label ?annotation ; fb:negated false .
  FILTER NOT EXISTS { ?r fb:status "blocked" }   # leave out records that failed a check
  ?colour rdfs:subClassOf* obo:FLOPO_0988004 .   # ISCC-NBS yellow
  ?taxon rdfs:label ?name .
} ORDER BY ?name`,
  "All records of one taxon, as plain RDF (no OWL)": `PREFIX fb: <${FB}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

# Every record links its taxon, plant part, value and sentence directly.
# The taxon links to its records with fb:record.
SELECT ?part ?value ?low ?high ?unit ?text ?source WHERE {
  <http://phenomebrowser.net/flopo/taxon/ipni-862354-1> fb:record ?r .   # Clerodendrum robecchii
  ?r fb:bearer/rdfs:label ?part ; fb:quality/rdfs:label ?value ; fb:text ?text ; fb:source/rdfs:label ?source .
  OPTIONAL { ?r fb:low ?low } OPTIONAL { ?r fb:high ?high } OPTIONAL { ?r fb:unit ?unit }
  FILTER(LANG(?part) = "" && LANG(?value) = "")
} ORDER BY ?part ?value`,
  "Shrubs taller than 2 m in Asir": `PREFIX fb: <${FB}>
PREFIX obo: <http://purl.obolibrary.org/obo/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT DISTINCT ?name ?height WHERE {
  ?habit fb:taxon ?t ; fb:quality obo:FLOPO_0987002 .            # frutescent habit
  ?size fb:taxon ?t ; fb:bearer obo:PO_0000003 ; fb:quality obo:PATO_0000119 ; fb:high ?h ; fb:unit ?unit .
  BIND(IF(?unit = "cm", ?h / 100, IF(?unit = "mm", ?h / 1000, ?h)) AS ?height)
  FILTER(?height > 2)
  ?occ a fb:Occurrence ; fb:taxon ?t ; fb:region <http://phenomebrowser.net/flopo/geo/region/SA-14> .
  ?t rdfs:label ?name .
} ORDER BY DESC(?height)`,
  "FLOPO classes most used across the floras": `PREFIX fb: <${FB}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?class (SAMPLE(?l) AS ?label) (COUNT(DISTINCT ?t) AS ?taxa) WHERE {
  ?r fb:flopoClass ?class ; fb:taxon ?t . ?class rdfs:label ?l .
} GROUP BY ?class ORDER BY DESC(?taxa) LIMIT 50`,
  "Taxa recorded in multiple flora sources": `PREFIX fb: <${FB}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?taxon ?name (COUNT(DISTINCT ?src) AS ?sources) WHERE {
  ?taxon a fb:Taxon ; rdfs:label ?name ; fb:printedName/fb:source ?src .
} GROUP BY ?taxon ?name HAVING (COUNT(DISTINCT ?src) > 1) ORDER BY ?name`,
  "Strict taxon axioms of the formal assertion modules (OWL)": `PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?taxon ?property ?phenotypeClass WHERE {
  ?taxon rdfs:subClassOf ?restriction .
  ?restriction a owl:Restriction ; owl:onProperty ?property ; owl:someValuesFrom ?phenotypeClass .
} LIMIT 50`,
  "Contradictory statements, by kind": `PREFIX fb: <${FB}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?taxon ?kind ?note (GROUP_CONCAT(?label; separator=" | ") AS ?statements) WHERE {
  ?c a fb:Conflict ; fb:taxon ?t ; fb:kind ?kind ; rdfs:comment ?note ; fb:member ?r .
  ?r rdfs:label ?label . ?t rdfs:label ?taxon .
} GROUP BY ?c ?taxon ?kind ?note ORDER BY ?kind ?taxon`,
  "Statements not yet annotated, by reason": `PREFIX fb: <${FB}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?source ?reason (COUNT(*) AS ?statements) WHERE {
  ?p a fb:PendingStatement ; fb:reason ?reason ; fb:source/rdfs:label ?source .
} GROUP BY ?source ?reason ORDER BY DESC(?statements)`,
};

async function query(params) {
  const first = Object.keys(EXAMPLES)[0];
  let text = EXAMPLES[first];
  if (params.get("describe")) text = `DESCRIBE ${iriLiteral(params.get("describe"))}`;
  if (params.get("q")) text = params.get("q");
  if (params.get("taxon")) text = `PREFIX fb: <${FB}>\nPREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n\nSELECT ?annotation ?bearer ?quality ?flopoClass ?source WHERE {\n  ?r fb:taxon <${params.get("taxon")}> ; rdfs:label ?annotation ;\n     fb:bearer ?bearer ; fb:quality ?quality ; fb:source/rdfs:label ?source .\n  OPTIONAL { ?r fb:flopoClass ?flopoClass }\n} ORDER BY ?annotation`;
  setTitle(params.get("describe") ? "Annotation or class" : "Query");
  setView(`<h1>Query</h1><p class="muted">All annotations are RDF. Write SPARQL 1.1 against the endpoint at <code>${esc(ENDPOINT)}</code> (all graphs are queried together; the FLOPO class hierarchy is loaded too). Common prefixes such as <code>fb:</code>, <code>obo:</code> and <code>rdfs:</code> are predefined.</p>
    <div class="toolbar"><label for="ex" class="muted">Examples</label><select id="ex">${Object.keys(EXAMPLES).map((k) => `<option>${esc(k)}</option>`).join("")}</select></div>
    <textarea class="sparql" id="q" spellcheck="false" aria-label="SPARQL query">${esc(text)}</textarea>
    <div class="toolbar"><button type="button" id="runq">Run query</button><label class="check"><input type="checkbox" id="nolimit"> No limit</label><a id="csv" href="#">Download all as CSV</a><a id="tsv" href="#">Download all as TSV</a><span class="muted" id="qinfo" role="status"></span></div>
    <div class="tablewrap" id="qout"></div>`);
  const area = document.getElementById("q");
  document.getElementById("ex").addEventListener("change", (e) => { area.value = EXAMPLES[e.target.value]; });
  const run = async () => {
    const out = document.getElementById("qout");
    const info = document.getElementById("qinfo");
    out.innerHTML = `<p class="loading">Running…</p>`;
    info.textContent = "";
    const started = performance.now();
    try {
      if (/^\s*(PREFIX[^\n]*\n\s*)*(DESCRIBE|CONSTRUCT)/i.test(area.value)) {
        const r = await fetch(sparqlUrl(area.value), { headers: { Accept: "text/turtle" } });
        const body = await r.text();
        if (!r.ok) throw new Error(body);
        out.innerHTML = await describeHtml(body);
        wireRaw(out, body);
        info.textContent = `${Math.round(performance.now() - started)} ms`;
      } else {
        // A query without LIMIT could return millions of rows: it is run with one unless the box is ticked.
        const { text: effective, added } = withLimit(area.value, !document.getElementById("nolimit").checked);
        const rows = await sparql(effective);
        const cols = rows.length ? Object.keys(rows.reduce((a, r) => Object.assign(a, r), {})) : [];
        const shown = rows.slice(0, QUERY_ROWS);
        const cell = (c, r) => {
          const v = r[c] ?? "";
          if (v.startsWith(TAXON)) return `<td><a href="${taxonHref(v)}">${esc(taxonKey(v))}</a></td>`;
          if (isObo(v) && /^[A-Za-z]+_\d+$/.test(local(v))) return `<td><a href="${esc(termHref(v))}">${esc(curie(v))}</a></td>`;
          if (/^https?:\/\//.test(v)) return `<td><a href="${esc(v)}" target="_blank" rel="noopener">${esc(v)}</a></td>`;
          return `<td>${esc(v)}</td>`;
        };
        const tsv = `<a href="${esc(sparqlUrl(area.value, { format: "tsv" }))}" target="_blank" rel="noopener">Download all as TSV</a>`;
        const notes = [];
        if (rows.length > QUERY_ROWS) notes.push(`Showing the first ${n(QUERY_ROWS)} of ${n(rows.length)}${added && rows.length >= QUERY_LIMIT ? " or more" : ""} rows. ${tsv}.`);
        if (added && rows.length >= QUERY_LIMIT) notes.push(`The query has no LIMIT, so it was run with LIMIT ${n(QUERY_LIMIT)}. Tick “No limit” to run it as written; the downloads always contain every row.`);
        out.innerHTML = (rows.length
          ? `<table class="results"><thead><tr>${cols.map((c) => `<th scope="col">${esc(c)}</th>`).join("")}</tr></thead><tbody>${shown.map((r) => `<tr>${cols.map((c) => cell(c, r)).join("")}</tr>`).join("")}</tbody></table>`
          : `<p class="muted">The query returned no results.</p>`) + notes.map((x) => `<p class="muted">${x}</p>`).join("");
        info.textContent = `${n(rows.length)} rows in ${Math.round(performance.now() - started)} ms`;
      }
    } catch (err) {
      out.innerHTML = `<p class="error">${esc(err.message)}</p>`;
      info.textContent = "";
    }
  };
  document.getElementById("runq").addEventListener("click", run);
  area.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") run(); });
  for (const format of ["csv", "tsv"]) {
    // the file is the endpoint's answer to the query as written, all rows
    document.getElementById(format).addEventListener("click", (e) => { e.currentTarget.href = sparqlUrl(area.value, { format }); e.currentTarget.target = "_blank"; e.currentTarget.rel = "noopener"; });
  }
  if (params.get("describe") || params.get("taxon") || params.get("q")) run();
}
const QUERY_ROWS = 500;
const QUERY_LIMIT = 5000;
// The query with LIMIT added when it is a SELECT without one (and the reader has not asked for none).
function withLimit(text, enforce) {
  const plain = text.replace(/<[^<>\s]*>/g, " ").replace(/"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'/g, " ").replace(/#[^\n]*/g, "");
  const select = /\bSELECT\b/i.test(plain) && !/\b(ASK|CONSTRUCT|DESCRIBE)\b/i.test(plain);
  const limited = /\bLIMIT\s+\d+(\s+OFFSET\s+\d+)?\s*$/i.test(plain.trim()) || /\bOFFSET\s+\d+\s+LIMIT\s+\d+\s*$/i.test(plain.trim());
  if (!enforce || !select || limited) return { text, added: false };
  return { text: text.replace(/\s+$/, "") + `\nLIMIT ${QUERY_LIMIT}`, added: true };
}

/* ---------------------------------------------------------------- readable DESCRIBE */
// DESCRIBE answers in N-Triples, with blank nodes for the parts of OWL class expressions. They are
// shown as labelled lines first, with the triples as they are behind a button.
const RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#";
const RDFS_NS = "http://www.w3.org/2000/01/rdf-schema#";
const OWL_NS = "http://www.w3.org/2002/07/owl#";
function parseTerm(x) {
  if (x[0] === "<") return { t: "i", v: x.slice(1, -1) };
  if (x[0] === "_") return { t: "b", v: x };
  const m = /^"((?:[^"\\]|\\.)*)"(?:@([\w-]+)|\^\^<([^>]*)>)?$/.exec(x);
  if (!m) return { t: "l", v: x }; // a number or true/false written without quotes
  let v = m[1];
  try { v = JSON.parse(`"${m[1]}"`); } catch (e) { /* keep the escaped text */ }
  return { t: "l", v, lang: m[2], dt: m[3] };
}
function parseNTriples(text) {
  const re = /^(<[^>]*>|_:\S+)\s+<([^>]*)>\s+(<[^>]*>|_:\S+|"(?:[^"\\]|\\.)*"(?:@[A-Za-z0-9-]+|\^\^<[^>]*>)?|[-+]?\d[\d.eE+-]*|true|false)\s*\.$/;
  const triples = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line[0] === "#") continue;
    const m = re.exec(line);
    if (!m) return null; // Turtle with prefixes or lists: shown as it is
    triples.push([parseTerm(m[1]), m[2], parseTerm(m[3])]);
  }
  return triples;
}
async function labelsOf(iris) {
  const labels = new Map();
  const list = [...iris].slice(0, 300);
  for (let i = 0; i < list.length; i += 100) {
    const rows = await sparql(`SELECT ?x (SAMPLE(?l) AS ?label) WHERE { VALUES ?x { ${list.slice(i, i + 100).map(iriLiteral).join(" ")} } ?x rdfs:label ?l FILTER(LANG(?l) = "" || LANGMATCHES(LANG(?l), "en")) } GROUP BY ?x`);
    rows.forEach((r) => labels.set(r.x, r.label));
  }
  return labels;
}
const tidyName = (iri) => { const w = local(iri).replace(/[_-]+/g, " ").replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase(); return w.charAt(0).toUpperCase() + w.slice(1); };
const iriText = (labels, iri) => labels.get(iri) || (isObo(iri) ? curie(iri) : tidyName(iri).toLowerCase());
function iriHtml(labels, iri) {
  const text = esc(iriText(labels, iri));
  if (isObo(iri)) return `<a href="${esc(termHref(iri))}" title="${esc(curie(iri))}">${text}</a>`;
  if (iri.startsWith(TAXON)) return `<a href="${taxonHref(iri)}">${text}</a>`;
  if (iri.startsWith("http://phenomebrowser.net/flopo/")) return `<a href="#/query?describe=${encodeURIComponent(iri)}">${text}</a>`;
  return `<a href="${esc(iri)}" target="_blank" rel="noopener">${text}</a>`;
}
// A class expression, in the words of Manchester syntax: has part some (leaf and has characteristic some glabrous).
function expressionHtml(g, labels, node, depth = 0) {
  const get = (n, p) => (g.get(n.t + n.v) || new Map()).get(p) || [];
  const quoted = (iri) => { const t = esc(iriText(labels, iri)); return /\s/.test(iriText(labels, iri)) ? `‘${t}’` : t; };
  const atom = (n) => (n.t === "i" ? iriHtml(labels, n.v) : n.t === "l" ? `<span class="lit">${esc(n.v)}</span>` : "");
  if (node.t !== "b") return atom(node);
  if (depth > 12) return "…";
  const sub = (n) => expressionHtml(g, labels, n, depth + 1);
  const wrap = (n) => (n.t === "b" && !get(n, OWL_NS + "onDatatype").length ? `(${sub(n)})` : sub(n));
  const list = (head) => { const items = []; let at = head; for (let i = 0; at && at.v !== RDF_NS + "nil" && i < 300; i++) { items.push(...get(at, RDF_NS + "first")); at = get(at, RDF_NS + "rest")[0]; } return items; };
  const prop = get(node, OWL_NS + "onProperty")[0];
  if (prop) {
    const kinds = [["someValuesFrom", "some"], ["allValuesFrom", "only"], ["hasValue", "value"]];
    for (const [k, word] of kinds) { const f = get(node, OWL_NS + k)[0]; if (f) return `${prop.t === "i" ? iriHtml(labels, prop.v) : "…"} <b>${word}</b> ${wrap(f)}`; }
    const cards = { minCardinality: "min", maxCardinality: "max", cardinality: "exactly", minQualifiedCardinality: "min", maxQualifiedCardinality: "max", qualifiedCardinality: "exactly" };
    for (const [k, word] of Object.entries(cards)) {
      const c = get(node, OWL_NS + k)[0];
      if (c) { const on = get(node, OWL_NS + "onClass")[0] || get(node, OWL_NS + "onDataRange")[0]; return `${iriHtml(labels, prop.v)} <b>${word} ${esc(c.v)}</b>${on ? " " + wrap(on) : ""}`; }
    }
  }
  const joins = [["intersectionOf", " <b>and</b> "], ["unionOf", " <b>or</b> "]];
  for (const [k, word] of joins) { const l = get(node, OWL_NS + k)[0]; if (l) return list(l).map(wrap).join(word); }
  const not = get(node, OWL_NS + "complementOf")[0];
  if (not) return `<b>not</b> ${wrap(not)}`;
  const one = get(node, OWL_NS + "oneOf")[0];
  if (one) return `{${list(one).map(sub).join(", ")}}`;
  const datatype = get(node, OWL_NS + "onDatatype")[0];
  if (datatype) {
    const facets = { minInclusive: "≥", maxInclusive: "≤", minExclusive: ">", maxExclusive: "<" };
    const parts = list(get(node, OWL_NS + "withRestrictions")[0] || { v: RDF_NS + "nil" }).flatMap((r) => Object.entries(facets).flatMap(([f, sign]) => get(r, "http://www.w3.org/2001/XMLSchema#" + f).map((v) => `${sign} ${esc(v.v)}`)));
    return `${local(datatype.v)}${parts.length ? ` [${parts.join(", ")}]` : ""}`;
  }
  const first = get(node, RDF_NS + "first");
  if (first.length) return `(${list(node).map(sub).join(", ")})`;
  return "…";
}
async function describeHtml(body) {
  const triples = parseNTriples(body);
  if (!triples || !triples.length) return `<pre>${esc(body)}</pre>`;
  const g = new Map();
  for (const [s, p, o] of triples) {
    const k = s.t + s.v;
    if (!g.has(k)) g.set(k, new Map());
    if (!g.get(k).has(p)) g.get(k).set(p, []);
    g.get(k).get(p).push(o);
  }
  // terms to name: the properties and the IRIs inside class expressions, not the records of a taxon
  const want = new Set();
  for (const [s, p, o] of triples) {
    if (p !== "http://phenomebrowser.net/flopo/browse#record") want.add(p);
    for (const x of [s, o]) if (x.t === "i" && (isObo(x.v) || s.t === "i")) want.add(x.v);
  }
  let labels = new Map();
  try { labels = await labelsOf(want); } catch (e) { /* the readable view then uses the identifiers */ }
  const ORDER = [RDFS_NS + "label", RDF_NS + "type", OWL_NS + "equivalentClass", RDFS_NS + "subClassOf", RDFS_NS + "comment"];
  const NAME = { [RDF_NS + "type"]: "Type", [RDFS_NS + "label"]: "Label", [OWL_NS + "equivalentClass"]: "Equivalent to", [RDFS_NS + "subClassOf"]: "Subclass of", [RDFS_NS + "comment"]: "Comment" };
  const subjects = [...g.keys()].filter((k) => k[0] === "i");
  const view = subjects.slice(0, 5).map((k) => {
    const iri = k.slice(1);
    const props = [...g.get(k)].sort(([a], [b]) => (ORDER.indexOf(a) < 0 ? 99 : ORDER.indexOf(a)) - (ORDER.indexOf(b) < 0 ? 99 : ORDER.indexOf(b)) || iriText(labels, a).localeCompare(iriText(labels, b)));
    let lines = 0;
    const items = props.map(([p, objects]) => {
      const seen = new Map();
      for (const o of objects) {
        const h = expressionHtml(g, labels, o);
        seen.set(h, (seen.get(h) || 0) + 1);
      }
      return [...seen].slice(0, 60).map(([h, count]) => { lines++; return `<li><span class="axiom-p">${esc(NAME[p] || labels.get(p) || tidyName(p))}</span> <span class="axiom-v">${h}</span>${count > 1 ? ` <span class="muted">(stated ${count} times)</span>` : ""}</li>`; }).join("") + (seen.size > 60 ? `<li class="muted">${n(seen.size - 60)} more ${esc(NAME[p] || tidyName(p)).toLowerCase()} values</li>` : "");
    }).join("");
    const title = (g.get(k).get(RDFS_NS + "label") || [])[0];
    return `<section class="describe"><h2>${esc(title ? title.v : labels.get(iri) || local(iri))}</h2><p class="muted"><code>${esc(iri)}</code></p><ul class="axioms">${items}</ul></section>`;
  }).join("");
  return `${view}${subjects.length > 5 ? `<p class="muted">${n(subjects.length - 5)} more subjects are in the raw triples.</p>` : ""}
    <p><button type="button" class="ghost" id="rawbtn" aria-expanded="false" aria-controls="raw">Show raw triples</button> <span class="muted">${n(triples.length)} triples</span></p><pre id="raw" hidden></pre>`;
}
function wireRaw(out, body) {
  const button = out.querySelector("#rawbtn"), pre = out.querySelector("#raw");
  if (!button) return;
  button.addEventListener("click", () => {
    const open = pre.hidden;
    if (open && !pre.textContent) pre.textContent = body;
    pre.hidden = !open;
    button.setAttribute("aria-expanded", String(open));
    button.textContent = open ? "Hide raw triples" : "Show raw triples";
  });
}

/* ---------------------------------------------------------------- coverage */
/* One table for all floras, with totals; a flora opens to the reasons its statements are held. */
let coverageSort = { key: "rows", dir: -1 };
async function coverage() {
  const [s, src, reasons] = await Promise.all([
    summary(),
    sources(),
    cached("pending-reasons", () =>
      sparql(`SELECT ?src ?reason (COUNT(*) AS ?n) WHERE { ?p a fb:PendingStatement ; fb:reason ?reason ; fb:source/rdfs:label ?src } GROUP BY ?src ?reason ORDER BY DESC(?n)`)
    ),
  ]);
  const keys = Object.keys(s).filter((k) => s[k] && s[k].phenotype_rows !== undefined);
  const data = keys.map((k) => {
    const meta = src.find((x) => x.s.endsWith("/" + k)) || { label: k, title: k };
    const sk = s[k];
    return {
      key: k, label: meta.label, title: meta.title || "", taxa: s.taxa.per_source[k] || 0, rows: sk.phenotype_rows || 0,
      formal: sk.rows_formalized || 0, accepted: sk.gate_accepted || 0, review: sk.gate_review || 0, pending: sk.pending || 0,
      share: sk.phenotype_rows ? sk.rows_formalized / sk.phenotype_rows : 0,
    };
  });
  const total = (f) => data.reduce((a, d) => a + d[f], 0);
  const all = { rows: total("rows"), formal: total("formal"), accepted: total("accepted"), review: total("review"), pending: total("pending") };
  const pct = (a, b) => Math.round((100 * a) / Math.max(1, b));
  // reasons over all floras; the many "alternatives ... unreviewed: A|B" reasons are one kind
  const kind = (reason) => reason.replace(/^(alternatives_across_attributes_unreviewed):.*/, "$1").replace(/^merged_into:.*/, "merged_into");
  const overall = new Map();
  for (const r of reasons) overall.set(kind(r.reason), (overall.get(kind(r.reason)) || 0) + +r.n);
  const top = [...overall.entries()].filter(([k]) => k !== "merged_into").sort((a, b) => b[1] - a[1]).slice(0, 14);
  const topMax = Math.max(1, ...top.map(([, v]) => v));

  const columns = [
    ["label", "Flora"], ["taxa", "Taxa"], ["rows", "Statements"], ["share", "Annotated"],
    ["accepted", "Accepted"], ["review", "Under review"], ["pending", "Not yet annotated"],
  ];
  const draw = () => {
    const { key, dir } = coverageSort;
    const sorted = [...data].sort((a, b) => (typeof a[key] === "string" ? a[key].localeCompare(b[key]) : a[key] - b[key]) * dir);
    const body = sorted
      .map((d) => `<tr class="cov-row" data-src="${esc(d.label)}" tabindex="0" aria-expanded="false" title="${esc(d.title)}">
        <th scope="row">${esc(d.label)}</th><td class="num">${n(d.taxa)}</td><td class="num">${n(d.rows)}</td>
        <td><span class="cov-bar" title="${n(d.formal)} of ${n(d.rows)}"><i style="width:${(100 * d.accepted) / Math.max(1, d.rows)}%"></i><i class="part" style="width:${(100 * d.review) / Math.max(1, d.rows)}%"></i></span><span class="num cov-pct">${pct(d.formal, d.rows)}%</span></td>
        <td class="num">${n(d.accepted)}</td><td class="num">${n(d.review)}</td><td class="num">${n(d.pending)}</td></tr>
        <tr class="cov-detail" hidden><td colspan="7"></td></tr>`)
      .join("");
    view.querySelector("#cov-table").innerHTML = `<thead><tr>${columns
      .map(([k, label]) => `<th scope="col" class="${k === "label" ? "" : "num"}"><button type="button" data-sort="${k}" aria-pressed="${k === key}">${label}${k === key ? (dir < 0 ? " ▾" : " ▴") : ""}</button></th>`)
      .join("")}</tr></thead><tbody>${body}</tbody>
      <tfoot><tr><th scope="row">All ${n(data.length)} floras</th><td class="num">${n(s.taxa.taxa)}</td><td class="num">${n(all.rows)}</td>
        <td><span class="cov-bar"><i style="width:${(100 * all.accepted) / Math.max(1, all.rows)}%"></i><i class="part" style="width:${(100 * all.review) / Math.max(1, all.rows)}%"></i></span><span class="num cov-pct">${pct(all.formal, all.rows)}%</span></td>
        <td class="num">${n(all.accepted)}</td><td class="num">${n(all.review)}</td><td class="num">${n(all.pending)}</td></tr></tfoot>`;
    view.querySelectorAll("#cov-table [data-sort]").forEach((b) =>
      b.addEventListener("click", () => {
        coverageSort = { key: b.dataset.sort, dir: coverageSort.key === b.dataset.sort ? -coverageSort.dir : b.dataset.sort === "label" ? 1 : -1 };
        draw();
      })
    );
    const open = (row) => {
      const detail = row.nextElementSibling;
      detail.hidden = !detail.hidden;
      row.classList.toggle("open", !detail.hidden);
      row.setAttribute("aria-expanded", String(!detail.hidden));
      if (detail.hidden || detail.dataset.loaded) return;
      detail.dataset.loaded = "1";
      const mine = reasons.filter((r) => r.src === row.dataset.src && !r.reason.startsWith("merged_into"));
      const max = Math.max(1, ...mine.map((r) => +r.n));
      detail.firstElementChild.innerHTML = mine.length
        ? `<p class="muted">Why statements of ${esc(row.dataset.src)} are not yet annotated. Open a reason to list the transcribed qualities, most frequent first.</p>
          <div class="reasons">${mine
            .map((r) => `<details class="reason" data-src="${esc(row.dataset.src)}" data-reason="${esc(r.reason)}"><summary><span class="reason-name">${esc(reasonLabel(r.reason))}</span><span class="num">${n(r.n)}</span><span class="bar"><i class="part" style="width:${(100 * r.n) / max}%"></i></span></summary><div class="reason-body"></div></details>`)
            .join("")}</div>`
        : `<p class="muted">Every transcribed statement of this flora is annotated.</p>`;
      detail.querySelectorAll("details.reason").forEach((d) => d.addEventListener("toggle", () => { if (d.open) pendingPhrases(d); }));
    };
    view.querySelectorAll("tr.cov-row").forEach((row) => {
      row.addEventListener("click", () => open(row));
      row.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(row); } });
    });
  };

  setView(html`<h1>Coverage</h1>
    <p class="lede">Each flora description is transcribed into trait statements, one per plant part and quality. A statement becomes an annotation when its part and quality match ontology terms and it fits one of the annotation patterns. The rest are kept as text with the reason, so they can be added later.</p>
    <div class="figures cov-figures">
      <div class="figure"><b class="num">${n(all.rows)}</b><span>trait statements transcribed from ${n(data.length)} floras</span></div>
      <div class="figure"><b class="num">${pct(all.formal, all.rows)}%</b><span>annotated with FLOPO, PO and PATO</span></div>
      <div class="figure"><b class="num">${n(all.accepted)}</b><span>annotations accepted by the checks; ${n(all.review)} more under review</span></div>
      <div class="figure"><b class="num">${n(s.taxa.taxa)}</b><span>taxa in ${n(s.taxa.families)} families, ${s.taxa.with_ipni !== undefined ? `${n(s.taxa.with_ipni)} standardized to IPNI (WCVP)` : `${n(s.taxa.with_wfo)} matched to World Flora Online`}</span></div>
    </div>
    <h2>By flora</h2>
    <p class="muted">Select a column to sort, and a flora to see why its remaining statements are not yet annotated. The bar shows accepted annotations <span class="key key-acc"></span> and those under review <span class="key key-rev"></span>, as a share of all statements.</p>
    <div class="tablewrap" tabindex="0" role="region" aria-label="Coverage by flora"><table id="cov-table" class="coverage"></table></div>
    <h2>Why statements are not yet annotated</h2>
    <p class="muted">All floras together, the most frequent reasons. A flora's own list, with the statements, opens from the table above.</p>
    <div class="reasons overall">${top
      .map(([reason, count]) => `<div class="reason-line"><span>${esc(reasonLabel(reason))}</span><span class="num">${n(count)}</span><span class="bar"><i class="part" style="width:${(100 * count) / topMax}%"></i></span></div>`)
      .join("")}</div>`);
  draw();
}

/* ---------------------------------------------------------------- map */
/* Where the taxa are recorded, by country (places.json, built by tools/atlas_places.py). */
async function placesMap() {
  const [places, shapes] = await Promise.all([
    cached("places", () => requestJson(new URL("places.json", document.baseURI).href)),
    cached("countries", () => requestJson(new URL("data/countries.geojson", document.baseURI).href)),
  ]);
  const src = await sources();
  const label = (key) => (src.find((x) => x.s.endsWith("/" + key)) || {}).label || key;
  const countries = places.countries || {};
  const max = Math.max(1, ...Object.values(countries).map((c) => c.taxa));
  const steps = [1, 10, 100, 1000, 10000].filter((v) => v <= max * 10);
  const shades = ["#e3ede8", "#bcd6cb", "#8cbba9", "#5d9c86", "#3a7b66", "#1f5a49"];
  const shade = (taxa) => (taxa ? shades[Math.min(shades.length - 1, 1 + Math.floor(Math.log10(taxa)))] : "transparent");
  const total = Object.keys(countries).length;
  const countryName = (a3) => ((shapes.features.find((f) => f.properties.a3 === a3) || { properties: { name: a3 } }).properties.name);
  setTitle("Map");
  setView(html`<h1>Map</h1>
    <p class="lede">Where the taxa of the atlas grow. A taxon counts for a country when a regional flora of that country describes it (every taxon of the Flora of China, of NCVC and Collenette for Saudi Arabia), or when a place record names the country, one of its provinces or a coded region; ${n(places.matched)} of ${n(places.records)} place records could be assigned to one of ${n(total)} countries. Worldwide sources (World Flora Online, Plazi, GrassBase…) count only through their place records. Select a country for its floras and taxa.</p>
    <div class="map-layout">
      <div>
        <div class="field country-pick"><label for="country-select">Choose a country from the list (the map can also be clicked)</label>
          <select id="country-select"><option value="">Choose a country…</option>${Object.keys(countries).map((a3) => [a3, countryName(a3)]).sort((a, b) => a[1].localeCompare(b[1])).map(([a3, name]) => `<option value="${a3}">${esc(name)} (${n(countries[a3].taxa)})</option>`).join("")}</select></div>
        <div id="world" class="worldmap" role="img" aria-label="World map of taxa recorded per country"></div>
        <div class="map-legend"><span class="muted">Taxa recorded</span>${steps
          .map((v, i) => `<span><i style="background:${shades[i + 1]}"></i>${n(v)}${i === steps.length - 1 ? "+" : "–" + n(steps[i + 1] - 1)}</span>`)
          .join("")}<span><i class="none"></i>none</span></div>
      </div>
      <aside id="country" class="country-panel" aria-live="polite"><p class="muted">No country selected.</p>
        <h3>Most taxa</h3><ol class="country-top">${Object.entries(countries).sort((a, b) => b[1].taxa - a[1].taxa).slice(0, 12)
          .map(([a3, c]) => `<li><button type="button" class="link" data-a3="${a3}">${esc(countryName(a3))}</button> <span class="num muted">${n(c.taxa)}</span></li>`)
          .join("")}</ol>
        ${places.unmatched && places.unmatched.length ? `<h3>Not placed in a country</h3><p class="muted">${places.unmatched.slice(0, 14).map(([name, count]) => `${esc(name)} (${n(count)})`).join(", ")}, …</p>` : ""}
      </aside>
    </div>`);
  const panel = document.getElementById("country");
  const show = async (a3, name) => {
    const c = countries[a3];
    if (!c) { panel.innerHTML = `<h2>${esc(name)}</h2><p class="muted">No taxa recorded for this country in the floras of the atlas.</p>`; return; }
    const floras = Object.entries(c.floras || {});
    panel.innerHTML = `<h2>${esc(name)}</h2>
      <dl class="kv"><dt>Taxa</dt><dd class="num">${n(c.taxa)}</dd>
        ${c.taxa_flora !== undefined ? `<dt>in a flora of the country</dt><dd class="num">${n(c.taxa_flora)}</dd><dt>with a place record</dt><dd class="num">${n(c.taxa_places)}</dd>` : ""}
        <dt>Place records</dt><dd class="num">${n(c.records)}</dd></dl>
      ${floras.length ? `<h3>Floras of the country</h3><ul class="plain">${floras.map(([k, v]) => `<li>${esc(label(k))} <span class="num muted">${n(v)} taxa</span></li>`).join("")}</ul>` : ""}
      ${Object.keys(c.sources).length ? `<h3>Place records from</h3><ul class="plain">${Object.entries(c.sources).map(([k, v]) => `<li>${esc(label(k))} <span class="num muted">${n(v)}</span></li>`).join("")}</ul>` : ""}
      ${c.localities.length ? `<h3>Named as</h3><p class="muted">${c.localities.slice(0, 24).map(esc).join(", ")}${c.localities.length > 24 ? ", …" : ""}</p>` : ""}
      <h3>Taxa</h3><input id="ctfilter" type="search" placeholder="Filter these taxa" autocomplete="off"><div id="country-taxa"><p class="muted">Loading…</p></div>`;
    try {
      const [byCountry, index] = await Promise.all([
        cached("country-taxa", () => requestJson(new URL("country-taxa.json", document.baseURI).href)),
        taxonIndex(),
      ]);
      const rows = (byCountry[a3] || []).map((i) => index.rows[i]).filter(Boolean);
      const box = document.getElementById("country-taxa");
      const filter = document.getElementById("ctfilter");
      if (!box || !filter) return;
      const draw = () => {
        const words = filter.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
        const shown = rows.filter((r) => words.every((w) => r.find.includes(w)));
        box.innerHTML = `<ul class="plain taxa-list">${shown.slice(0, 400).map((r) => `<li><a href="${taxonHref(r.t)}"><i>${esc(r.label)}</i></a> <span class="muted">${esc(r.family)}</span></li>`).join("")}</ul>${shown.length > 400 ? `<p class="muted">The first 400 of ${n(shown.length)}, in alphabetical order; type to narrow the list.</p>` : ""}`;
      };
      filter.addEventListener("input", draw);
      draw();
    } catch (err) {
      const box = document.getElementById("country-taxa");
      if (box) box.innerHTML = `<p class="error">${esc(err.message)}</p>`;
    }
  };
  // Every country can be chosen from the list, with or without the map.
  const pickSelect = document.getElementById("country-select");
  let pick = (a3) => show(a3, countryName(a3));
  pickSelect.addEventListener("change", () => { if (pickSelect.value) pick(pickSelect.value); });
  view.querySelectorAll("[data-a3]").forEach((b) => b.addEventListener("click", () => { pickSelect.value = b.dataset.a3; pick(b.dataset.a3); }));
  if (!window.L) return;
  const map = L.map("world", { scrollWheelZoom: false, worldCopyJump: true, minZoom: 1, maxZoom: 6, attributionControl: true }).setView([22, 15], 2);
  map.attributionControl.setPrefix("").addAttribution("Country outlines: Natural Earth");
  let selected = null;
  const layers = new Map();
  const layer = L.geoJSON(shapes, {
    style: (f) => ({ color: "#7d8a83", weight: 0.6, fillColor: shade((countries[f.properties.a3] || {}).taxa), fillOpacity: (countries[f.properties.a3] || {}).taxa ? 0.9 : 0.05 }),
    onEachFeature: (f, l) => {
      const c = countries[f.properties.a3];
      l.bindTooltip(`${esc(f.properties.name)}: ${c ? n(c.taxa) + " taxa" : "none"}`, { sticky: true });
      layers.set(f.properties.a3, l);
      l.on("click", () => {
        if (selected) layer.resetStyle(selected);
        selected = l;
        l.setStyle({ weight: 2, color: "#b8862b" });
        pickSelect.value = f.properties.a3;
        show(f.properties.a3, f.properties.name);
      });
    },
  }).addTo(map);
  pick = (a3) => {
    const l = layers.get(a3);
    if (l) { map.fitBounds(l.getBounds(), { maxZoom: 4 }); l.fire("click"); } else show(a3, countryName(a3));
  };
}

const reasonLabel = (reason) => reason.replace(/_/g, " ").replace(/^no ontology term:/, "no ontology term: ");

/* The pending statements of one source and reason, grouped by phrase (case-folded). */
async function pendingPhrases(d) {
  const body = d.querySelector(".reason-body");
  if (body.dataset.loaded) return;
  body.dataset.loaded = "1";
  body.innerHTML = `<p class="muted">Loading…</p>`;
  try {
    const rows = await sparql(`SELECT ?text ?context ?taxon ?name ?part ?quality WHERE {
      ?p a fb:PendingStatement ; fb:reason ${JSON.stringify(d.dataset.reason)} ; fb:source/rdfs:label ${JSON.stringify(d.dataset.src)} ;
         fb:text ?text ; fb:taxon ?taxon . OPTIONAL { ?p fb:context ?context } OPTIONAL { ?taxon rdfs:label ?name }
         OPTIONAL { ?p fb:entityText ?part } OPTIONAL { ?p fb:qualityText ?quality } }`);
    // Group by the transcribed quality (with its part), which is what a term would be made for;
    // the anchored span can be a fallback word such as the part name.
    const groups = new Map();
    for (const r of rows) {
      r.label = r.quality ? `${r.quality}` : r.text;
      const key = (r.quality || r.text).trim().toLowerCase();
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(r);
    }
    const phrases = [...groups.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
    body.innerHTML = `<div class="phrase-tools"><input type="search" placeholder="Filter qualities" aria-label="Filter qualities">
      <span class="muted">${n(phrases.length)} distinct qualities</span>
      <a href="#" class="csv">Download as CSV</a></div>
      <ul class="phrases">${phrases
        .map(([key, occ]) => `<li data-key="${esc(key)}"><details><summary><span>${esc(occ[0].label)}</span>${occ.length > 1 ? ` <span class="num muted">× ${n(occ.length)}</span>` : ""}</summary><ul>${occ
          .map((o) => `<li><a href="${taxonHref(o.taxon)}"><i>${esc(o.name || taxonKey(o.taxon))}</i></a>${o.part ? ` <span class="muted">(${esc(o.part)})</span>` : ""}: ${highlight(o.context, o.text)}</li>`)
          .join("")}</ul></details></li>`)
        .join("")}</ul>`;
    const items = body.querySelectorAll("ul.phrases > li");
    const count = body.querySelector(".phrase-tools .muted");
    body.querySelector("input").addEventListener("input", (e) => {
      const q = e.target.value.trim().toLowerCase();
      let shown = 0;
      items.forEach((li) => { const on = !q || li.dataset.key.includes(q); li.hidden = !on; shown += on; });
      count.textContent = q ? `${n(shown)} of ${n(phrases.length)} qualities` : `${n(phrases.length)} distinct qualities`;
    });
    body.querySelector("a.csv").addEventListener("click", (e) => {
      e.preventDefault();
      const cell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
      const lines = [["quality", "count", "part", "span", "taxon", "sentence"].join(",")];
      for (const [, occ] of phrases) for (const o of occ) lines.push([o.label, occ.length, o.part, o.text, o.name || taxonKey(o.taxon), o.context].map(cell).join(","));
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
      a.download = `${d.dataset.src}-${d.dataset.reason}.csv`.replace(/[^\w.-]+/g, "_");
      a.click();
      URL.revokeObjectURL(a.href);
    });
  } catch (err) {
    delete body.dataset.loaded;
    body.innerHTML = `<p class="error">${esc(err.message)}</p>`;
  }
}

/* ---------------------------------------------------------------- patterns */
// The annotation design patterns (docs/odp, as patterns.json from tools/atlas_patterns.py), each
// with records of the atlas that follow it, found by the property only such records have.
const patternDocs = () => cached("patterns", () => requestJson(new URL("patterns.json", document.baseURI).href));
const patternQuery = (p, limit = 50) => `PREFIX fb: <${FB}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
# Records of pattern ${p.id}, ${p.title}
SELECT ?record ?annotation ?text ?taxon ?taxonIri ?source ?owlClass WHERE {
  ?r a fb:TraitRecord .
  ${p.selector}
  ?r rdfs:label ?annotation ; fb:text ?text ; fb:taxon ?t ; fb:source/rdfs:label ?source .
  ?t rdfs:label ?taxon .
  OPTIONAL { ?r fb:phenotypeClass ?owlClass }
  BIND(?r AS ?record) BIND(?t AS ?taxonIri)
} LIMIT ${limit}`;

async function patterns(id) {
  setView(`<p class="loading">Loading the patterns…</p>`);
  const docs = await patternDocs();
  const list = docs.patterns;
  if (!id) {
    setView(`<h1>Annotation patterns</h1>
      <p class="lede">The atlas does not store traits as text or as a table of characters. Every statement of a flora becomes a record that names a plant part from the Plant Ontology and a quality from PATO or FLOPO, and the firm content of each record is also an OWL class, which a reasoner places under FLOPO's phenotype classes. Because every flora is annotated with the same patterns, “leaves glabrous” in the Flora of China and “feuilles glabres” in the Flore du Gabon become the same class, and a query for glabrous leaves finds both.</p>
      <p>Each pattern below covers one way floras phrase a trait: what the source says, the record the annotator writes, its OWL class expression, its RDF in this atlas, and the rules that check it. Each page shows records of the atlas that follow the pattern.</p>
      <div class="doc">${docs.model || ""}</div>
      <h2>The patterns</h2>
      <ol class="patternlist">${list.map((p) => `<li><a href="#/patterns/${p.id}"><b>${esc(p.id)}. ${esc(p.title)}</b></a><span class="muted">${p.intent}</span><span class="wording">${p.wording}</span></li>`).join("")}</ol>
      <div class="doc">${docs.intro}</div>`);
    return;
  }
  const p = list.find((x) => x.id === id);
  if (!p) { setView(`<h1>Pattern not found</h1><p><a href="#/patterns">All patterns</a></p>`); return; }
  const i = list.indexOf(p);
  const nav = `<nav class="pager">${i > 0 ? `<a href="#/patterns/${list[i - 1].id}">← ${esc(list[i - 1].title)}</a>` : "<span></span>"}<a href="#/patterns">All patterns</a>${i < list.length - 1 ? `<a href="#/patterns/${list[i + 1].id}">${esc(list[i + 1].title)} →</a>` : "<span></span>"}</nav>`;
  setView(`${nav}<h1>${esc(p.id)}. ${esc(p.title)}</h1>
    <p class="lede">${p.intent}</p>
    ${p.wording ? `<p><span class="col-title">Source wording</span><br>${p.wording}</p>` : ""}
    ${p.selector ? `<section class="examples"><h2>In the atlas</h2><div id="pexamples"><p class="loading">Finding records…</p></div></section>` : ""}
    <div class="doc">${p.html}</div>
    <p class="muted"><a href="${esc(p.source)}" target="_blank" rel="noopener">This pattern in the FLOPO repository</a></p>${nav}`);
  if (!p.selector) return;
  try {
    const [count, rows] = await Promise.all([
      sparql(`PREFIX fb: <${FB}>\nSELECT (COUNT(?r) AS ?n) WHERE { ?r a fb:TraitRecord . ${p.selector} }`),
      sparql(patternQuery(p, 40)),
    ]);
    // a spread of sources, then the shortest source texts, which show the pattern most plainly
    const bySource = new Map();
    for (const r of rows.sort((a, b) => a.text.length - b.text.length)) if (!bySource.has(r.source)) bySource.set(r.source, r);
    const shown = [...bySource.values(), ...rows.filter((r) => ![...bySource.values()].includes(r))].slice(0, 6);
    const box = document.getElementById("pexamples");
    if (!box) return;
    box.innerHTML = `<p>${n(count[0]?.n || 0)} records of the atlas follow this pattern. Some of them, taken as the endpoint returns them (not chosen as good examples; they show the pattern as applied, including its errors):</p>
      <div class="tablewrap"><table class="results"><thead><tr><th>Source text</th><th>Annotation</th><th>Taxon</th><th>Source</th></tr></thead><tbody>${shown
        .map((r) => `<tr><td>“${esc(r.text)}”</td><td>${esc(r.annotation)}${r.owlClass ? ` <a href="#/query?describe=${encodeURIComponent(r.owlClass)}" title="OWL definition of the annotation class">OWL class</a>` : ""} <a href="#/query?describe=${encodeURIComponent(r.record)}" title="The RDF record">record</a></td><td><a class="sci" href="${taxonHref(r.taxonIri)}">${esc(r.taxon)}</a></td><td><span class="chip ${sourceClass(r.source)}">${esc(r.source)}</span></td></tr>`)
        .join("")}</tbody></table></div>
      <p><a href="#/query?q=${encodeURIComponent(patternQuery(p, 500))}">Open this query</a> to list more records of the pattern, or change it.</p>`;
  } catch (err) {
    const box = document.getElementById("pexamples");
    if (box) box.innerHTML = `<p class="error">${esc(err.message)}</p>`;
  }
}

/* ---------------------------------------------------------------- review */
// Readers say whether an annotation is right. Votes go to the feedback service beside the endpoint
// ("feedback/"); votes of signed-in reviewers and anonymous votes are counted apart. A server
// without that service (development) shows only the link that reports a problem.
const ISSUES = "https://github.com/flora-phenotype-ontology/flopoontology/issues/new";
const feedbackUrl = (name, params) => new URL("feedback/" + name, document.baseURI).href + (params ? "?" + new URLSearchParams(params) : "");
function reportHref(r, taxonLabel) {
  const body = [
    `Record: ${r.r}`, `Taxon: ${taxonLabel}`, `Source: ${r.source}`, `Annotation: ${r.label}`,
    `Source text: “${r.text || ""}”`, r.context ? `Sentence: “${r.context.slice(0, 600)}”` : "",
    `Page: ${location.href}`, "", "What is wrong, and what should it be?", "",
  ].filter((line) => line !== "").join("\n") + "\n\n";
  return ISSUES + "?" + new URLSearchParams({ title: `Annotation: ${taxonLabel}, “${r.label}”`.slice(0, 200), body });
}
async function setupReview(pane, taxonIri, records, taxonLabel) {
  // The table is rebuilt with every taxon; listeners on it go with it (the pane itself stays).
  const table = pane.querySelector("table.traits");
  if (!table) return;
  const byIri = new Map(records.map((r) => [r.r, r]));
  const boxes = () => table.querySelectorAll(".review[data-record]");
  const report = (r) => `<a href="${esc(reportHref(r, taxonLabel))}" target="_blank" rel="noopener" title="Opens an issue on GitHub with this record filled in">Report a problem</a>`;
  boxes().forEach((box) => { box.innerHTML = report(byIri.get(box.dataset.record)); });
  let state;
  try {
    const response = await fetch(feedbackUrl("state", { taxon: taxonIri }));
    if (!response.ok) return;
    state = await response.json();
  } catch (err) {
    return;
  }
  if (!table.isConnected || !state.counts) return;
  const kind = state.signed_in ? "named" : "anonymous";
  const zero = () => ({ named: [0, 0], anonymous: [0, 0] });
  const pair = ([up, down]) => `👍 ${n(up)} 👎 ${n(down)}`;
  const draw = (box, asking = false) => {
    const id = box.dataset.record;
    const c = state.counts[id] || zero();
    const mine = (state.mine[id] || {})[kind];
    const any = (k) => c[k][0] + c[k][1] > 0;
    const tally = [...table.querySelectorAll(".tally")].find((x) => x.dataset.tally === id);
    if (tally) tally.innerHTML = ["named", "anonymous"].filter(any).map((k) => `<span class="chip votes ${k}" title="${k === "named" ? "Votes of signed-in reviewers" : "Anonymous votes"}">${k === "named" ? "named" : "anon."} ${pair(c[k])}</span>`).join(" ");
    const button = (vote, text) => `<button type="button" class="ghost vote" data-vote="${vote}" aria-pressed="${mine?.vote === vote}">${text}</button>`;
    box.innerHTML = `<span class="ask">Is this annotation right?</span> ${button("up", "👍 Right")} ${button("down", "👎 Wrong")}
      <span class="muted">Signed-in reviewers: ${pair(c.named)} · anonymous: ${pair(c.anonymous)}</span> ${report(byIri.get(id))}
      ${asking && mine?.vote === "down" ? `<form class="why"><label>What is wrong? <select name="reason"><option value="">(choose, optional)</option>${Object.entries(state.reasons).map(([key, text]) => `<option value="${esc(key)}"${mine.reason === key ? " selected" : ""}>${esc(text)}</option>`).join("")}</select></label>
        <label>Comment <input name="comment" maxlength="500" placeholder="optional: what should it be?"></label> <button type="submit">Send</button> <span class="muted">Recorded as ${kind === "named" ? esc(state.signed_in.name) : "an anonymous vote"}.</span></form>` : ""}
      <span class="note muted" role="status"></span>`;
  };
  const send = async (box, vote, extra = {}) => {
    const note = box.querySelector(".note");
    try {
      const response = await fetch(feedbackUrl("vote"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ record: box.dataset.record, vote, ...extra }) });
      const out = await response.json();
      if (!response.ok) throw new Error(out.error || `HTTP ${response.status}`);
      state.counts[box.dataset.record] = out.counts;
      state.mine[box.dataset.record] = out.mine;
      draw(box, vote === "down" && !extra.sent);
      if (extra.sent) box.querySelector(".note").textContent = "Thank you, noted.";
    } catch (err) {
      if (note) note.textContent = `Your vote could not be saved (${err.message}).`;
    }
  };
  boxes().forEach((box) => draw(box));
  table.addEventListener("click", (e) => {
    const button = e.target.closest("button.vote");
    if (!button) return;
    const box = button.closest(".review");
    send(box, button.getAttribute("aria-pressed") === "true" ? "none" : button.dataset.vote);
  });
  table.addEventListener("submit", (e) => {
    const form = e.target.closest("form.why");
    if (!form) return;
    e.preventDefault();
    send(form.closest(".review"), "down", { reason: form.reason.value, comment: form.comment.value, sent: true });
  });
  const bar = document.getElementById("reviewbar");
  if (!bar) return;
  const back = encodeURIComponent(location.hash || "#/");
  const signIn = state.providers.map((p) => `<a href="${esc(feedbackUrl("login/" + p.key))}?return=${back}">${esc(p.label)}</a>`).join(" or ");
  bar.innerHTML = state.signed_in
    ? `Signed in as <b>${esc(state.signed_in.name)}</b>: your votes are recorded under your name. <button type="button" class="ghost" id="signout">Sign out</button>`
    : `Your votes are anonymous.${signIn ? ` Sign in with ${signIn} to have them counted under your name.` : ""} Named and anonymous votes are counted separately; a vote does not change the data, it tells the curators where to look.`;
  bar.hidden = false;
  document.getElementById("signout")?.addEventListener("click", async () => {
    await fetch(feedbackUrl("logout"), { method: "POST" });
    route();
  });
}

/* ---------------------------------------------------------------- compare two taxa */
// A flora describes one taxon at a time (a direct statement). Two such statements can be compared
// when they are about the same plant part and their qualities are values of the same attribute;
// the attribute of a value is its most specific superclass in PATO's attribute subset
// (Gkoutos, Schofield and Hoehndorf 2018, reference 2 of the About page).
const attributeTable = () => cached("attributes", () => requestJson(new URL("attributes.json", document.baseURI).href));
const METRES = { UO_0000008: 1, UO_0000015: 0.01, UO_0000016: 0.001, UO_0000017: 1e-6 };
const CONDITIONS = "fb:frequency fb:stage fb:bearerState fb:whole fb:container fb:specimenCondition fb:towards fb:scope fb:partQuality fb:collectionSize fb:countPosition fb:ratioNumerator";
async function comparableTraits(t, table) {
  const T = iriLiteral(t);
  const [rows, conditional, labels] = await Promise.all([
    sparql(`SELECT ?r ?bearer ?quality ?attribute ?unit ?low ?high ?negated WHERE {
      ?r a fb:TraitRecord ; fb:taxon ${T} ; fb:status "accepted" ; fb:bearer ?bearer ; fb:quality ?quality ; fb:negated ?negated .
      OPTIONAL { ?r fb:attribute ?attribute } OPTIONAL { ?r fb:unit ?unit } OPTIONAL { ?r fb:low ?low } OPTIONAL { ?r fb:high ?high } }`),
    sparql(`SELECT DISTINCT ?r WHERE { VALUES ?p { ${CONDITIONS} } ?r fb:taxon ${T} ; ?p ?x }`),
    sparql(`SELECT DISTINCT ?x ?l WHERE { ?r a fb:TraitRecord ; fb:taxon ${T} . { ?r fb:quality ?x } UNION { ?r fb:bearer ?x } ?x rdfs:label ?l }`),
  ]);
  const skip = new Set(conditional.map((x) => x.r));
  const label = new Map(labels.map((x) => [x.x, x.l]));
  const traits = new Map();
  let left = 0;
  const negated = new Set();
  for (const row of rows) {
    if (skip.has(row.r)) continue;
    // "not velutinous" says little about what the part is like: it is not set against a value
    if (row.negated === "true") { negated.add(row.r); continue; }
    const numeric = Boolean(row.unit);
    const attribute = numeric ? local(row.quality) : row.attribute ? local(row.attribute) : table.of[local(row.quality)];
    if (!attribute) { left += 1; continue; }
    const key = `${row.bearer} ${attribute} ${numeric ? "n" : "c"}`;
    const trait = traits.get(key) || traits.set(key, {
      bearer: row.bearer, blabel: label.get(row.bearer) || curie(row.bearer), attribute, numeric,
      alabel: table.label[attribute] || label.get(row.quality) || attribute.replace("_", ":"),
      values: new Map(), lo: Infinity, hi: -Infinity, units: new Set(), records: new Set(),
    }).get(key);
    trait.records.add(row.r);
    if (numeric) {
      const unit = local(row.unit), factor = METRES[unit];
      trait.units.add(factor ? "length" : unit);
      trait.unit = trait.unit || unit;
      const scale = factor || 1;
      // "to 8 m" has no lower number and "more than 5" no upper one
      trait.lo = Math.min(trait.lo, row.low === undefined ? 0 : row.low * scale);
      trait.hi = Math.max(trait.hi, row.high === undefined ? Infinity : row.high * scale);
    } else {
      trait.values.set(row.quality, label.get(row.quality) || curie(row.quality));
    }
  }
  return { traits, skipped: skip.size, negated: negated.size, left };
}
function compareTraits(a, b) {
  if (a.numeric) {
    if (a.units.size > 1 || b.units.size > 1 || [...a.units][0] !== [...b.units][0]) return "units";
    if (b.lo > a.hi) return "larger";
    if (b.hi < a.lo) return "smaller";
    return a.lo === b.lo && a.hi === b.hi ? "same" : "overlap";
  }
  const shared = [...a.values.keys()].filter((v) => b.values.has(v)).length;
  if (!shared) return "different";
  return shared === a.values.size && shared === b.values.size ? "same" : "overlap";
}
function traitValue(x) {
  if (!x.numeric) return [...x.values.values()].sort().map(esc).join(", ");
  const scale = METRES[x.unit] || 1;
  const show = (v) => Number((v / scale).toPrecision(6)).toLocaleString("en");
  const symbol = { UO_0000008: "m", UO_0000015: "cm", UO_0000016: "mm", UO_0000017: "µm", UO_0000189: "", UO_0000190: "" }[x.unit] ?? "";
  const range = x.hi === Infinity ? `more than ${show(x.lo)}` : x.lo === x.hi ? show(x.lo) : x.lo === 0 ? `up to ${show(x.hi)}` : `${show(x.lo)}–${show(x.hi)}`;
  return esc(`${range} ${symbol}`.trim());
}
function taxonPicker(id, prompt) {
  return `<label for="${id}" class="col-title" style="display:block">${prompt}</label>
    <input id="${id}" type="search" placeholder="e.g. Quercus stellata" autocomplete="off" style="max-width:28rem;width:100%">
    <div class="taxonlist" id="${id}-list" style="max-width:28rem"></div>`;
}
async function setupPicker(id, href, except = "") {
  const input = document.getElementById(id), list = document.getElementById(id + "-list");
  if (!input) return;
  const index = await taxonIndex();
  let timer = 0;
  const draw = () => {
    const words = input.value.trim();
    if (words.length < 2) { list.innerHTML = ""; return; }
    const shown = taxonMatches(index, words, "").filter((r) => r.t !== except && r.n > 0);
    list.innerHTML = shown.length
      ? shown.slice(0, 30).map((r) => `<a href="${href(r)}"><span class="sci">${esc(r.label)}</span>${r.family ? ` <span class="muted fam">${esc(r.family)}</span>` : ""}<small class="num" title="trait records">${r.n}</small></a>`).join("")
        + (shown.length > 30 ? `<p class="muted">${n(shown.length - 30)} more; type more of the name.</p>` : "")
      : `<p class="muted">No taxon matches “${esc(words)}”.</p>`;
  };
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(draw, 120); });
}
const COMPARE_INTRO = `<p class="muted">A flora describes one taxon at a time. Two statements can be compared when they are about the same plant part and their qualities are values of the same attribute (white and pink are both colours; white and ovate are not comparable). See <a href="#/about">About</a>, reference 2.</p>`;
async function compare(keyA, keyB) {
  const a = keyA ? TAXON + decodeURIComponent(keyA) : "", b = keyB ? TAXON + decodeURIComponent(keyB) : "";
  const index = await taxonIndex();
  const name = (t) => (index.rows.find((r) => r.t === t) || {}).label || taxonKey(t);
  if (!a || !b) {
    setView(`<h1>Compare two taxa</h1>${COMPARE_INTRO}
      ${a ? `<p>First taxon: <a href="${taxonHref(a)}" class="sci">${esc(name(a))}</a> <a href="#/compare" class="muted">change</a></p>` : ""}
      ${taxonPicker("cpick", a ? "Find the second taxon" : "Find the first taxon")}`);
    await setupPicker("cpick", (r) => `#/compare/${a ? encodeURIComponent(taxonKey(a)) + "/" : ""}${encodeURIComponent(r.key)}`, a);
    return;
  }
  setView(`<h1>Compare two taxa</h1><p class="loading">Loading…</p>`);
  const table = await attributeTable();
  const [A, B] = await Promise.all([comparableTraits(a, table), comparableTraits(b, table)]);
  const nameA = name(a), nameB = name(b);
  const rows = { different: [], larger: [], smaller: [], overlap: [], same: [], units: [] };
  const onlyA = [], onlyB = [];
  for (const [key, x] of A.traits) {
    const y = B.traits.get(key);
    if (y) rows[compareTraits(x, y)].push([x, y]); else onlyA.push(x);
  }
  for (const [key, y] of B.traits) if (!A.traits.has(key)) onlyB.push(y);
  const traitName = (x) => `${esc(x.blabel)} ${esc(x.alabel)}`;
  const byName = (p, q) => traitName(p[0] || p).localeCompare(traitName(q[0] || q));
  const verdict = {
    different: (x) => `${traitName(x)} differs`,
    larger: (x) => `${traitName(x)} greater in <i>${esc(nameB)}</i>`,
    smaller: (x) => `${traitName(x)} smaller in <i>${esc(nameB)}</i>`,
    overlap: () => `overlapping`, same: () => `the same`, units: () => `different units, not compared`,
  };
  const section = (kinds, title, note) => {
    const list = kinds.flatMap((k) => rows[k].map((pair) => [k, pair])).sort((p, q) => byName(p[1], q[1]));
    if (!list.length) return "";
    return `<h2>${title} <span class="muted">(${n(list.length)})</span></h2>${note ? `<p class="muted">${note}</p>` : ""}
      <div class="tablewrap"><table class="results compare"><thead><tr><th>Part and attribute</th><th><i>${esc(nameA)}</i></th><th><i>${esc(nameB)}</i></th><th>Comparison</th></tr></thead><tbody>
      ${list.map(([k, [x, y]]) => `<tr><th scope="row">${termLink(x.bearer, x.blabel)} ${termLink("http://purl.obolibrary.org/obo/" + x.attribute, x.alabel)}</th><td data-label="${esc(nameA)}">${traitValue(x)}</td><td data-label="${esc(nameB)}">${traitValue(y)}</td><td>${verdict[k](x)}</td></tr>`).join("")}
      </tbody></table></div>`;
  };
  const only = (list, who) => list.length ? `<details class="pending"><summary>${n(list.length)} described only for <i>${esc(who)}</i></summary><ul>${list.sort(byName).map((x) => `<li>${traitName(x)}: ${traitValue(x)}</li>`).join("")}</ul></details>` : "";
  const compared = Object.values(rows).reduce((sum, list) => sum + list.length, 0);
  const notes = [
    [A.skipped + B.skipped, "with a condition (“usually”, “when young”, “of male flowers”, relative to another part)"],
    [A.negated + B.negated, "that say what a part is not"],
    [A.left + B.left, "whose quality has no attribute in PATO"],
  ].filter(([count]) => count).map(([count, what]) => `${n(count)} annotations ${what}`);
  setView(`<h1>Compare two taxa</h1>
    <p class="lede"><a href="${taxonHref(a)}" class="sci">${esc(nameA)}</a> <span class="muted">and</span> <a href="${taxonHref(b)}" class="sci">${esc(nameB)}</a></p>
    ${COMPARE_INTRO}
    <p>${compared ? `${n(compared)} traits are described for both taxa: ${n(rows.different.length + rows.larger.length + rows.smaller.length)} differ, ${n(rows.overlap.length)} overlap, ${n(rows.same.length)} are the same.` : `No trait is described for both taxa in a comparable way.`}
      <a href="#/compare/${encodeURIComponent(taxonKey(b))}/${encodeURIComponent(taxonKey(a))}">Swap</a> · <a href="#/compare/${encodeURIComponent(taxonKey(a))}">Choose another second taxon</a></p>
    ${section(["different", "larger", "smaller"], "Differences", `Relative to <i>${esc(nameA)}</i>. A taxon covers many plants and each flora describes its own area, so a difference here is a difference between descriptions; check the sentences on the taxon pages.`)}
    ${section(["overlap"], "Overlapping", "The values or ranges share a part.")}
    ${section(["same"], "The same", "")}
    ${section(["units"], "Not compared", "")}
    <h2>Not comparable</h2>
    ${only(onlyA, nameA)}${only(onlyB, nameB)}
    <p class="muted">Only accepted annotations are compared.${notes.length ? ` Left out: ${notes.join("; ")}.` : ""}</p>`);
}

/* ---------------------------------------------------------------- about */
const doi = (id) => `<a href="https://doi.org/${id}" target="_blank" rel="noopener">doi:${id}</a>`;
const ext = (url, text) => `<a href="${url}" target="_blank" rel="noopener">${text}</a>`;
// [what, used for]; the links are the specifications or home pages.
const STANDARDS = [
  ["Data", [
    [ext("https://www.w3.org/TR/rdf11-concepts/", "RDF 1.1"), "Every annotation is RDF. The downloads are N-Quads, one named graph per source and kind of data."],
    [ext("https://www.w3.org/TR/sparql11-query/", "SPARQL 1.1"), "The public endpoint, which this website itself queries."],
    [ext("https://www.w3.org/TR/owl2-overview/", "OWL 2"), "The firm content of each annotation is an OWL class expression: a part, a quality, numbers as data ranges, “or” as a union, absence as a complement. Taxa are subclasses of these classes. Everything is classified with the ELK reasoner (OWL 2 EL)."],
    [ext("https://www.w3.org/TR/prov-o/", "PROV-O"), "Provenance: how each annotation was made, the source statement it derives from and the extraction step that produced it."],
    [ext("https://www.evidenceontology.org/", "Evidence and Conclusion Ontology (ECO)"), "Evidence: the kind of support each annotation has. Every record points to its source sentence as an author statement used in an automatic assertion (ECO:0007319)."],
    [ext("https://www.w3.org/TR/void/", "VoID") + ", " + ext("https://www.w3.org/TR/vocab-dcat-3/", "DCAT 3") + ", " + ext("https://schema.org/Dataset", "schema.org") + ", " + ext("https://www.w3.org/TR/tabular-data-primer/", "CSV on the Web"), "The description of the dataset itself: licence, version, files, checksums, sources and the columns of the tables (see <a href=\"#/downloads\">Downloads</a>)."],
    [ext("https://github.com/MaastrichtU-IDS/semanticscience", "SIO") + ", " + ext("https://www.dublincore.org/specifications/dublin-core/dcmi-terms/", "Dublin Core terms") + ", " + ext("https://www.w3.org/TR/skos-reference/", "SKOS"), "Source statements and their text (SIO), titles and identifiers of sources (Dublin Core), links from taxa to IPNI, Plants of the World Online and World Flora Online (skos:exactMatch)."],
    [ext("https://www.ogc.org/standards/geosparql/", "GeoSPARQL"), "Coordinates of named places, as WKT points."],
    [ext("https://shex.io/shex-semantics/", "ShEx") + " and " + ext("https://linkml.io/", "LinkML"), "The annotation record is defined as a LinkML schema; each annotation pattern has a ShEx shape that its RDF is checked against."],
    ["Linked data", "Every record, annotation class and taxon has an IRI under <code>http://phenomebrowser.net/flopo/</code> that returns RDF to programs (Turtle or N-Triples, by the Accept header) and a page to people. Ontology classes keep their OBO PURLs."],
  ]],
  ["Ontologies", [
    [ext("https://github.com/flora-phenotype-ontology/flopoontology", "FLOPO") + ", the Flora Phenotype Ontology", "Phenotype classes of plants, each defined from a plant part and a quality; also the quality words of floras that PATO lacks."],
    [ext("https://obofoundry.org/ontology/po.html", "Plant Ontology (PO)"), "Plant parts and developmental stages."],
    [ext("https://obofoundry.org/ontology/pato.html", "PATO"), "Qualities: shape, colour, texture, size and the like."],
    [ext("https://obofoundry.org/ontology/uo.html", "Units Ontology (UO)"), "Units of measurements and counts. Feet and inches of older floras are converted to SI units."],
    [ext("https://obofoundry.org/ontology/ro.html", "Relation Ontology (RO)") + ", " + ext("https://obofoundry.org/ontology/bfo.html", "BFO") + ", " + ext("https://obofoundry.org/ontology/bspo.html", "BSPO") + ", " + ext("https://obofoundry.org/ontology/iao.html", "IAO"), "The relations of the class expressions (has part, part of, has characteristic, towards), regions such as margin and apex, and the “pending final vetting” mark on provisional terms."],
    ["Entity–Quality (EQ) model", "The way of writing a phenotype as an entity and a quality that the phenotype ontologies share (references 2–5)."],
    ["ISCC-NBS colour names", "Colour words of the floras are read on the ISCC-NBS colour names, so that “reddish orange” is one value."],
  ]],
  ["Names and places", [
    [ext("https://www.ipni.org/", "IPNI") + " and Kew’s " + ext("https://powo.science.kew.org/about-wcvp", "World Checklist of Vascular Plants"), "Taxa are keyed by the IPNI identifier of the accepted name in the checklist; the names the floras print are kept and linked to it."],
    [ext("https://www.worldfloraonline.org/", "World Flora Online"), "Identifiers for mosses, algae and lichens, which the checklist does not cover, and as a second identifier for the others."],
    ["ISO 3166-2", "Codes of the regions of Saudi Arabia in the two Saudi guides."],
  ]],
];
// [citation, DOI, what the atlas takes from it]
const REFERENCES = [
  ["Hoehndorf R, Alshahrani M, Gkoutos GV, Gosline G, Groom Q, Hamann T, Kattge J, de Oliveira SM, Schmidt M, Sierra S, Smets E, Vos RA, Weiland C. The flora phenotype ontology (FLOPO): tool for integrating morphological traits and phenotypes of vascular plants. <i>Journal of Biomedical Semantics</i> 2016;7:65.", "10.1186/s13326-016-0107-8", "FLOPO itself, and the first version of this work: phenotypes mined from digitized floras."],
  ["Gkoutos GV, Schofield PN, Hoehndorf R. The anatomy of phenotype ontologies: principles, properties and applications. <i>Briefings in Bioinformatics</i> 2018;19(5):1008–1021.", "10.1093/bib/bbx035", "The principles the atlas is built on: direct and comparative phenotype statements, attributes and their values, the entity-first class pattern, inheritance over parts, relational qualities, absence. See “Principles” above."],
  ["Hoehndorf R, Oellrich A, Rebholz-Schuhmann D. Interoperability between phenotype and anatomy ontologies. <i>Bioinformatics</i> 2010;26(24):3112–3118.", "10.1093/bioinformatics/btq578", "The form of every phenotype class: a phene, the quality that a property gives its bearer, with a functional relation to the plant that has it; absence as the phene of lacking a part."],
  ["Mungall CJ, Gkoutos GV, Smith CL, Haendel MA, Lewis SE, Ashburner M. Integrating phenotype ontologies across multiple species. <i>Genome Biology</i> 2010;11:R2.", "10.1186/gb-2010-11-1-r2", "The entity–quality model in OWL: the form of every annotation class, relational qualities, counts."],
  ["Gkoutos GV, Green ECJ, Mallon AM, Hancock JM, Davidson D. Using ontologies to describe mouse phenotypes. <i>Genome Biology</i> 2005;6:R8.", "10.1186/gb-2004-6-1-r8", "PATO and the decomposition of a phenotype into entity and quality."],
  ["Dahdul WM, Balhoff JP, Engeman J, et al. Evolutionary characters, phenotypes and ontologies: curating data from the systematic biology literature. <i>PLoS ONE</i> 2010;5(5):e10708.", "10.1371/journal.pone.0010708", "Entity–quality annotation of characters from the systematic literature; composing terms where no single class exists."],
  ["Balhoff JP, Mikó I, Yoder MJ, Mullins PL, Deans AR. A semantic model for species description applied to the ensign wasps (Hymenoptera: Evaniidae) of New Caledonia. <i>Systematic Biology</i> 2013;62(5):639–659.", "10.1093/sysbio/syt028", "Species descriptions written as OWL class expressions, with the taxon as a class. The atlas follows this model, and its limits for relative measurements and counts are discussed on the pattern pages."],
  ["Endara L, Thessen AE, Cole HA, Walls R, Gkoutos G, Cao Y, Chong SS, Cui H. Modifier ontologies for frequency, certainty, degree, and coverage phenotype modifier. <i>Biodiversity Data Journal</i> 2018;6:e29232.", "10.3897/BDJ.6.e29232", "The kinds of modifier (usually, rarely, about, broadly) that the records keep beside the OWL class."],
  ["Osumi-Sutherland D, Courtot M, Balhoff JP, Mungall C. Dead simple OWL design patterns. <i>Journal of Biomedical Semantics</i> 2017;8:18.", "10.1186/s13326-017-0126-0", "Documenting each way of writing a class as a named pattern (the Patterns pages)."],
  ["Loebe F, Stumpf F, Hoehndorf R, Herre H. Towards improving phenotype representation in OWL. <i>Journal of Biomedical Semantics</i> 2012;3(Suppl 2):S5.", "10.1186/2041-1480-3-S2-S5", "Ways of writing phenotypes in OWL, including the absence of parts."],
  ["Cui H. CharaParser for fine-grained semantic annotation of organism morphological descriptions. <i>Journal of the American Society for Information Science and Technology</i> 2012;63(4):738–754.", "10.1002/asi.22618", "Earlier automatic annotation of morphological descriptions, to which the patterns are compared."],
  ["Deans AR, Lewis SE, Huala E, et al. Finding our way through phenotypes. <i>PLoS Biology</i> 2015;13(1):e1002033.", "10.1371/journal.pbio.1002033", "The case for computable phenotype descriptions across biodiversity and genetics."],
  ["Cooper L, Walls RL, Elser J, et al. The Plant Ontology as a tool for comparative plant anatomy and genomic analyses. <i>Plant and Cell Physiology</i> 2013;54(2):e1.", "10.1093/pcp/pcs163", "The Plant Ontology."],
  ["Dumontier M, Baker CJO, Baran J, et al. The Semanticscience Integrated Ontology (SIO) for biomedical research and knowledge discovery. <i>Journal of Biomedical Semantics</i> 2014;5:14.", "10.1186/2041-1480-5-14", "SIO, used for source statements and the annotation model."],
  ["Kazakov Y, Krötzsch M, Simančík F. The incredible ELK: from polynomial procedures to efficient reasoning with EL ontologies. <i>Journal of Automated Reasoning</i> 2014;53:1–61.", "10.1007/s10817-013-9296-3", "The reasoner that classifies FLOPO and the annotation classes."],
  ["Govaerts R, Nic Lughadha E, Black N, Turner R, Paton A. The World Checklist of Vascular Plants, a continuously updated resource for exploring global plant diversity. <i>Scientific Data</i> 2021;8:215.", "10.1038/s41597-021-00997-6", "The checklist the taxon names are standardized to."],
];
async function about() {
  setView(`<h1>About the atlas</h1>
    <p class="lede">The FLOPO Trait Atlas turns the descriptions in floras into data: every statement about a plant (“leaves glabrous”, “petals white or pink”, “fruit 3–5 cm”) becomes an annotation with ontology classes, linked to the taxon and to the sentence it comes from.</p>
    <div class="doc">
    <h2>How the annotations are made</h2>
    <p>The text of each flora is split into single trait statements by a language model. Each statement is then mapped to a plant part (Plant Ontology) and a quality (PATO, or FLOPO where PATO has no term) with rule tables, and written as a record following one of the <a href="#/patterns">annotation patterns</a>. Automatic checks decide whether a record is accepted, kept for review or blocked: rules on the record, ShEx shapes on its RDF, and a reasoner run that finds contradictory classes. Statements that could not be mapped are kept as pending, with the reason; the <a href="#/coverage">coverage</a> page counts them per flora.</p>
    <p>Taxon names are matched to Kew’s World Checklist of Vascular Plants and keyed by IPNI identifier. A language model repairs names the checklist did not match, and a repair counts only if the checklist then matches it.</p>
    <p>The annotations are made automatically and contain errors. Each record keeps the words of the source so that it can be checked, and terms not yet reviewed by a curator are marked as provisional.</p>
    <h2>Standards and vocabularies</h2>
    ${STANDARDS.map(([title, rows]) => `<h3>${title}</h3><div class="tablewrap"><table class="results about"><tbody>${rows.map(([what, use]) => `<tr><th scope="row">${what}</th><td>${use}</td></tr>`).join("")}</tbody></table></div>`).join("")}
    <h2>Principles</h2>
    <p>The atlas follows the principles for phenotype ontologies set out by Gkoutos, Schofield and Hoehndorf (reference 2). In the terms of that review:</p>
    <div class="tablewrap"><table class="results about"><tbody>
    <tr><th scope="row">Direct statements</th><td>A flora describes each taxon by itself, without a reference plant. Every annotation is such a direct statement about one taxon. Comparative statements (“leaf colour differs”, “petals longer”) are not stored; they are derived from two direct statements, as the review describes, on the <a href="#/compare">Compare</a> page.</td></tr>
    <tr><th scope="row">Comparable statements</th><td>Two statements are comparable when they are about the same plant part and their qualities are values of the same attribute. The attribute of a value is its most specific superclass in PATO’s attribute subset. The same rule decides whether “white or pink” is one statement with two values, which measurements of several floras are merged into one range, and what the Compare page sets side by side.</td></tr>
    <tr><th scope="row">A phenotype is a quality of the plant</th><td>The review separates two readings of a phenotype class: a class of organisms, or a class of qualities of organisms. FLOPO and the atlas use the second, in the form of reference 3: <code>'flora phenotype' and 'phenotype of' some (<i>defining property</i>)</code>, where the defining property says what the plant is like. A taxon is linked to its classes with <code>'has phenotype'</code>. <code>'phenotype of'</code> is functional (a phenotype belongs to one plant) and the inverse of <code>'has phenotype'</code>, so a plant with several phenotypes has all their defining properties at once (<a href="#/patterns/00">pattern 00</a>).</td></tr>
    <tr><th scope="row">Entity first</th><td>The defining property is written with the plant part first and the quality as its modifier: <code>'has part' some (leaf and 'has characteristic' some glabrous)</code>. All statements about one part are therefore grouped together.</td></tr>
    <tr><th scope="row">Inheritance over parts</th><td>FLOPO’s grouping classes are written with <code>'part of' some</code> the part, as in <code>'has part' some ('part of' some leaf and 'has characteristic' some quality)</code>, so a phenotype of the leaf margin is also a leaf phenotype. The structure of FLOPO follows the Plant Ontology in this way and is computed by a reasoner.</td></tr>
    <tr><th scope="row">Relational qualities</th><td>A quality that involves a second part (“adnate to the petals”, “shorter than the tube”) is a quality of the first part directed <code>towards</code> the second.</td></tr>
    <tr><th scope="row">Absence</th><td>“Petals absent” is the complement of having petals, not a quality of a petal that does not exist. The defining property is the review’s form, <code>not ('has part' some ('part of' some petal))</code>: no petal and no part of a petal. A taxon said to lack leaves and to have ovate leaf blades is therefore flagged as contradictory (<a href="#/patterns/15">pattern 15</a>).</td></tr>
    <tr><th scope="row">Reasoning in OWL 2 EL</th><td>Classes are classified with ELK. Negation, unions, number ranges and functional properties are outside OWL 2 EL, so the reasoner passes over them; they are kept in the classes and checked separately. Whether the statements about one taxon can all hold of one plant is checked with ELK through one extra axiom per class (<code>'has phenotype' some C SubClassOf <i>defining property</i></code>), and on the published axioms themselves with HermiT, a reasoner for all of OWL 2 DL, one taxon at a time.</td></tr>
    <tr><th scope="row">Evidence and provenance</th><td>PATO does not record what supports a statement or how it was obtained. The atlas keeps the two apart. <b>Evidence</b> is what supports the annotation: the sentence of the flora, linked with <code>has evidence</code> (RO:0002558) and typed with the Evidence and Conclusion Ontology as ${ext("http://purl.obolibrary.org/obo/ECO_0007319", "ECO:0007319")}, an author statement used in an automatic assertion. <b>Provenance</b> is how the annotation was made: the extraction step and the program that ran it, in PROV-O.</td></tr>
    </tbody></table></div>
    <h2>Work the atlas builds on</h2>
    <p>The representation follows the entity–quality model of the phenotype ontologies, the principles above, the phene of reference 3, and the OWL model of species descriptions of Balhoff and colleagues. The <a href="#/patterns">pattern pages</a> say, for each pattern, where it follows this literature and where it departs from it.</p>
    <ol class="refs">${REFERENCES.map(([cite, id, use]) => `<li>${cite} ${doi(id)}<br><span class="muted">${use}</span></li>`).join("")}</ol>
    <h2>How to cite</h2>
    <p>Until the atlas has its own publication, please cite the FLOPO paper (reference 1) and the data version you used; the <a href="#/downloads">downloads</a> page gives the version, its permanent address and the line to cite.</p>
    <h2>Licence</h2>
    <p>The annotations are licensed ${ext("https://creativecommons.org/licenses/by/4.0/", "CC BY 4.0")}: use them for any purpose, with credit (the <a href="#/downloads">downloads</a> page has the line to cite). The Flora Phenotype Ontology is released under CC0. The sentences quoted from the floras are there so that annotations can be checked; rights in them remain with the floras they come from and are not covered by the licence.</p>
    <h2>FAIR data</h2>
    <div class="tablewrap"><table class="results about"><tbody>
    <tr><th scope="row">Findable</th><td>Every record, annotation class, taxon and data version has its own IRI. The dataset is described in <a href="void.ttl">void.ttl</a> (VoID, DCAT) and, for dataset search engines, in schema.org terms in this page.</td></tr>
    <tr><th scope="row">Accessible</th><td>Everything is open over HTTP without registration: by IRI, through the SPARQL endpoint, and as files. Earlier versions stay listed, with their date and what changed, after their files are gone.</td></tr>
    <tr><th scope="row">Interoperable</th><td>RDF and OWL with community ontologies (PO, PATO, FLOPO, UO, RO, ECO, PROV-O) and shared identifiers for taxa (IPNI, World Flora Online); tables with a machine-readable column description.</td></tr>
    <tr><th scope="row">Reusable</th><td>A stated licence (CC BY 4.0), versions with dates and a note of what changed, checksums, the source sentence and the evidence and provenance of every record, and documented annotation patterns.</td></tr>
    </tbody></table></div>
    <h2>Code and contact</h2>
    <p>The ontology, the annotation pipeline and this website are developed at ${ext("https://github.com/flora-phenotype-ontology/flopoontology", "github.com/flora-phenotype-ontology/flopoontology")}; questions and corrections are welcome as issues there.</p>
    </div>`);
}

/* ---------------------------------------------------------------- downloads */
const size = (bytes) => (bytes >= 1e9 ? (bytes / 1e9).toFixed(1) + " GB" : bytes >= 1e6 ? Math.round(bytes / 1e6) + " MB" : Math.max(1, Math.round(bytes / 1e3)) + " kB");
async function downloads() {
  setView(`<p class="loading">Loading the list of files…</p>`);
  let d;
  try {
    d = await cached("downloads", () => requestJson(new URL("downloads.json", document.baseURI).href));
  } catch (err) {
    setView(`<h1>Downloads</h1><p>The download files are not available on this server. All data can be read from the <a href="#/query">SPARQL endpoint</a>.</p>`);
    return;
  }
  // versions.json: the data version, its licence and citation, and earlier versions (tools.atlas_metadata)
  const v = await cached("versions", () => requestJson(new URL("versions.json", document.baseURI).href)).catch(() => null);
  const versionBox = v ? `<h2>Version, licence and citation</h2>
    <dl class="kv">
      <dt>Version</dt><dd><code>${esc(v.version)}</code>, with the permanent address <a href="${esc(v.iri)}"><code>${esc(v.iri)}</code></a>. A version is one build of the data; changes to the website alone do not make a new one.</dd>
      <dt>Licence</dt><dd><a href="${esc(v.license)}" target="_blank" rel="license noopener">${esc(v.license_name)}</a> for the annotations. The Flora Phenotype Ontology is CC0. The sentences quoted from the floras are there so that annotations can be checked; rights in them remain with their sources. <a href="downloads/LICENSE.txt">LICENSE.txt</a></dd>
      <dt>Cite as</dt><dd>${esc(v.citation)} <span class="muted">(<a href="downloads/CITATION.cff">CITATION.cff</a>; please also cite the FLOPO paper, see <a href="#/about">About</a>)</span></dd>
      <dt>Metadata</dt><dd><a href="void.ttl">void.ttl</a> describes the dataset for programs (VoID and DCAT: licence, version, every graph and file with size and checksum, the sources); <a href="dataset.jsonld">dataset.jsonld</a> is the same in schema.org terms; <a href="downloads/tsv/csv-metadata.json">csv-metadata.json</a> gives the columns of the tables (CSV on the Web).</dd>
    </dl>
    <details class="columns"><summary><b>Earlier versions</b> <span class="muted">${n(v.history.length)} listed</span></summary>
    <div class="tablewrap"><table class="results"><thead><tr><th>Version</th><th>Date</th><th>Triples</th><th>What changed</th></tr></thead><tbody>${v.history.map((h) => `<tr><td><code>${esc(h.version)}</code></td><td>${esc(h.date)}</td><td class="num">${h.triples ? n(h.triples) : ""}</td><td>${esc(h.changes || "")}</td></tr>`).join("")}</tbody></table></div>
    <p class="muted">Only the current version is kept for download here.</p></details>` : "";
  const file = (f, text) => (f ? `<a href="downloads/${esc(f.path)}" download>${text || esc(f.path.split("/").pop())}</a> <span class="muted num">${size(f.bytes)}</span>` : `<span class="empty">·</span>`);
  const rdf = d.files.filter((f) => f.format === "nquads");
  const tsv = d.files.filter((f) => f.format === "tsv");
  const plain = d.files.find((f) => f.format === "ntriples");
  const total = (list) => list.reduce((a, f) => a + f.bytes, 0);
  const all = tsv.find((f) => f.path === "tsv/traits-all.tsv.gz");
  const keys = [...new Set(rdf.filter((f) => f.source).map((f) => f.source))];
  const records = (key) => tsv.find((f) => f.table === "traits" && f.source === key)?.rows || 0;
  keys.sort((a, b) => records(b) - records(a));
  const sourceRows = keys.map((key) => {
    const g = (kind) => rdf.find((f) => f.source === key && f.kind === kind);
    const meta = d.sources[key] || {};
    return `<tr><th scope="row">${esc(meta.label || key)}<br><span class="muted">${esc(meta.title || "")}</span></th>
      <td class="num">${n(records(key))}</td>
      <td>${file(tsv.find((f) => f.table === "traits" && f.source === key), "TSV")}</td>
      <td>${file(g("assertions"), "RDF")}</td><td>${file(g("index"), "RDF")}</td><td>${file(g("places"), "RDF")}</td></tr>`;
  }).join("");
  const tables = Object.entries(d.tables).map(([key, t]) => {
    const f = key === "traits" ? all : tsv.find((x) => x.table === key);
    return `<tr><th scope="row">${esc(t.title)}</th><td>${esc(t.description)}${key === "traits" ? " This file has all floras; the table below has one file per flora." : ""}</td><td class="num">${f ? n(f.rows) : ""}</td><td>${file(f)}</td></tr>`;
  }).join("");
  const shared = rdf.filter((f) => !f.source).map((f) => `<tr><th scope="row">${esc(f.kind)}</th><td>${esc(d.shared_graphs[f.kind] || "")}</td><td class="num">${n(f.triples)}</td><td>${file(f)}</td></tr>`).join("");
  const columns = Object.entries(d.tables).map(([key, t]) => `<details class="columns"><summary><b>${esc(t.title)}</b> <span class="muted">${key === "traits" ? "traits-*.tsv.gz" : esc(key) + ".tsv.gz"}, ${t.columns.length} columns</span></summary>
    <div class="tablewrap"><table class="results"><thead><tr><th>Column</th><th>Meaning</th></tr></thead><tbody>${t.columns.map((c) => `<tr><td><code>${esc(c.name)}</code></td><td>${esc(c.description)}</td></tr>`).join("")}</tbody></table></div></details>`).join("");
  setView(`<h1>Downloads</h1>
    <p class="lede">All data of the atlas can be downloaded: as RDF, which is complete, and as tab-separated tables with one row per trait record.</p>
    <p>Version <code>${esc(v ? v.version : d.release)}</code>: ${n(tsv.filter((f) => f.table === "traits" && f.source).reduce((a, f) => a + f.rows, 0))} trait records from ${n(keys.length)} sources. All RDF files together are ${size(total(rdf))} compressed, all tables ${size(total(tsv))}.
      <a href="downloads/README.txt">README.txt</a> describes every file and column; <a href="downloads/SHA256SUMS.txt">SHA256SUMS.txt</a> has the checksums.</p>
    <p class="muted">The annotations are made automatically and contain errors; the <code>status</code> column and the <a href="#/about">About</a> page say how they are checked.</p>
    ${versionBox}
    <h2>Tables (TSV)</h2>
    <p>Tab-separated, UTF-8, gzip-compressed, with a header line. Ontology classes are given as identifier and name. Several values in one cell are separated by “|”.</p>
    <div class="tablewrap"><table class="results"><thead><tr><th>Table</th><th>Content</th><th>Rows</th><th>File</th></tr></thead><tbody>${tables}</tbody></table></div>
    <h3>Columns</h3>${columns}
    <h2>By source</h2>
    <p>Each flora has a table of its trait records and up to three RDF graphs: the <b>annotations</b> in full (${esc(d.graph_kinds.assertions.replace(/^Annotations in full: /, "").replace(/\.$/, ""))}), the <b>flat records</b> (the form the tables and this website use, plus the statements not yet annotated), and <b>places</b>.</p>
    <div class="tablewrap"><table class="results"><thead><tr><th>Source</th><th>Trait records</th><th>Table</th><th>Annotations</th><th>Flat records</th><th>Places</th></tr></thead><tbody>${sourceRows}</tbody></table></div>
    ${plain ? `<h2>Plain RDF, without OWL</h2>
    <p>${file(plain)}: the flat records, places, taxa and term names of all sources as N-Triples (${n(plain.triples)} triples). It has no named graphs, no blank nodes and no OWL constructs, so it loads into any triple store, including those that make their own graphs. A record points to its taxon, plant part, value, numbers and sentence; a taxon points to its records with <code>fb:record</code>. The <a href="#/query">Query</a> page has an example. What it leaves out is in the files below: the OWL definitions of the annotation classes, the taxon axioms and the provenance of each annotation.</p>` : ""}
    <h2>Shared RDF graphs</h2>
    <p>RDF files are N-Quads, gzip-compressed, one named graph per file. Loading all of them into a SPARQL store gives the same data as the public endpoint. The OWL definitions of the annotation classes are in <code>annotation-classes</code>.</p>
    <div class="tablewrap"><table class="results"><thead><tr><th>Graph</th><th>Content</th><th>Triples</th><th>File</th></tr></thead><tbody>${shared}</tbody></table></div>
    <h2>Other ways to get the data</h2>
    <ul>
      <li><b>SPARQL:</b> <code>${esc(ENDPOINT)}</code>. Add <code>format=csv</code>, <code>tsv</code> or <code>json</code> to a query URL to choose the result format; the <a href="#/query">Query</a> page has examples.</li>
      <li><b>By IRI:</b> every record, annotation class and taxon IRI returns its RDF: <code>curl -H 'Accept: text/turtle' http://phenomebrowser.net/flopo/taxon/ipni-…</code></li>
      <li><b>The ontology:</b> FLOPO in OWL at ${ext("http://purl.obolibrary.org/obo/flopo.owl", "purl.obolibrary.org/obo/flopo.owl")}; releases and source at ${ext("https://github.com/flora-phenotype-ontology/flopoontology", "GitHub")}.</li>
    </ul>`);
}

/* ---------------------------------------------------------------- an ontology term */
// #/term/PO:0009046 : what the endpoint knows about a term of PO, PATO, FLOPO, UO and the like, and where
// the atlas uses it. The loaded ontology files carry labels, definitions, synonyms and the hierarchy.
const SYNONYM_KINDS = [["hasExactSynonym", "exact"], ["hasNarrowSynonym", "narrower"], ["hasBroadSynonym", "broader"], ["hasRelatedSynonym", "related"], ["altLabel", "also called"]];
async function termPage(id) {
  const m = /^([A-Za-z][A-Za-z0-9]*)[:_](\d+)$/.exec(decodeURIComponent(id || ""));
  if (!m) {
    setTitle("Term not found");
    setView(`<h1>Term not found</h1><p>“${esc(decodeURIComponent(id || ""))}” is not an ontology term identifier such as <a href="#/term/PO:0009046">PO:0009046</a>.</p>`);
    return;
  }
  const iri = `${OBO}${m[1]}_${m[2]}`, cur = `${m[1]}:${m[2]}`, T = iriLiteral(iri);
  setTitle(cur);
  setView(`<p class="loading">Loading ${esc(cur)}…</p>`);
  const used = `{ { ?r fb:bearer ${T} } UNION { ?r fb:quality ?q0 . ?q0 rdfs:subClassOf* ${T} } UNION { ?r fb:flopoClass ?c0 . ?c0 rdfs:subClassOf* ${T} } UNION { ?r fb:unit ${T} } }`;
  const [info, parents, children] = await Promise.all([
    sparql(`SELECT ?p ?o WHERE { VALUES ?p { rdfs:label obo:IAO_0000115 rdfs:comment skos:altLabel oboInOwl:hasExactSynonym oboInOwl:hasNarrowSynonym oboInOwl:hasBroadSynonym oboInOwl:hasRelatedSynonym obo:IAO_0000114 owl:deprecated } ${T} ?p ?o }`),
    sparql(`SELECT DISTINCT ?c ?l WHERE { ${T} rdfs:subClassOf ?c FILTER(isIRI(?c)) OPTIONAL { ?c rdfs:label ?l } }`),
    sparql(`SELECT DISTINCT ?c ?l WHERE { ?c rdfs:subClassOf ${T} ; rdfs:label ?l FILTER(isIRI(?c)) } ORDER BY ?l LIMIT 301`),
  ]);
  const one = (p) => (info.find((x) => x.p === p) || {}).o;
  const label = one(RDFS_NS + "label");
  if (label) setTitle(`${label} (${cur})`);
  const definition = one(OBO + "IAO_0000115") || one(RDFS_NS + "comment");
  // the "also called" names of SKOS often repeat the others (PO adds the scope in brackets): each name is listed once
  const bare = (x) => x.toLowerCase().replace(/ \((?:[a-z]+, )?(?:exact|narrow|broad|related)\)$/i, "");
  const listed = new Set();
  const synonyms = [];
  for (const [k, kind] of SYNONYM_KINDS) {
    const list = [...new Set(info.filter((x) => x.p.endsWith("#" + k) || x.p.endsWith("/" + k)).map((x) => x.o))].filter((x) => !listed.has(bare(x))).sort();
    list.forEach((x) => listed.add(bare(x)));
    if (list.length) synonyms.push([kind, list]);
  }
  const status = one(OBO + "IAO_0000114");
  const provisional = status && local(status) === "IAO_0000125";
  const external = `https://www.ebi.ac.uk/ols4/ontologies/${m[1].toLowerCase()}/classes?iri=${encodeURIComponent(iri)}`;
  const termList = (rows) => `<ul class="plain termlist">${rows.map((r) => `<li>${termLink(r.c, r.l || curie(r.c))}</li>`).join("")}</ul>`;
  const known = info.length || parents.length || children.length;
  setView(`<h1>${esc(label || cur)}</h1>
    <p class="muted"><code>${esc(cur)}</code> · <a href="${esc(external)}" target="_blank" rel="noopener">Open in the ontology browser (OLS)</a> · <a href="${esc(iri)}" target="_blank" rel="noopener">${esc(iri)}</a></p>
    ${provisional ? `<p class="note-box">This is a provisional term, still waiting for a curator to check it.</p>` : ""}
    ${known ? "" : `<p>The atlas has no data on this term. It may belong to an ontology that is not loaded here; try the link above.</p>`}
    ${definition ? `<h2>Definition</h2><p>${esc(definition)}</p>` : ""}
    ${synonyms.length ? `<h2>Synonyms</h2><dl class="kv">${synonyms.map(([kind, list]) => `<dt>${esc(kind)}</dt><dd>${list.map(esc).join("; ")}</dd>`).join("")}</dl>` : ""}
    ${parents.length || children.length ? `<h2>Place in the hierarchy</h2><div class="term-cols"><div><h3>Broader terms</h3>${parents.length ? termList(parents) : `<p class="muted">None in the atlas data.</p>`}</div>
      <div><h3>Narrower terms</h3>${children.length ? termList(children.slice(0, 300)) + (children.length > 300 ? `<p class="muted">More than 300; the first 300 are shown.</p>` : "") : `<p class="muted">None.</p>`}</div></div>` : ""}
    ${known ? `<h2>Use in the atlas</h2><div id="term-use"><p class="loading">Counting…</p></div>` : ""}`);
  const box = document.getElementById("term-use");
  if (!box) return;
  try {
    const totals = await sparql(`SELECT (COUNT(DISTINCT ?t) AS ?taxa) (COUNT(DISTINCT ?r) AS ?records) WHERE { ${used} ?r a fb:TraitRecord ; fb:taxon ?t . ${NOT_BLOCKED} }`);
    if (!box.isConnected) return;
    const taxaN = +(totals[0] || {}).taxa || 0, recordsN = +(totals[0] || {}).records || 0;
    if (!recordsN) { box.innerHTML = `<p class="muted">No trait record uses this term, directly or through a narrower term.</p>`; return; }
    box.innerHTML = `<p><b class="num">${n(taxaN)}</b> taxa and <b class="num">${n(recordsN)}</b> records use this term, or a narrower one. Records that failed a check are not counted.</p><p class="loading">Listing the traits…</p>`;
    const combos = await sparql(`SELECT ?og ?tg ?b ?q (SAMPLE(?bl) AS ?blabel) (SAMPLE(?ql) AS ?qlabel) (COUNT(DISTINCT ?t) AS ?taxa) WHERE {
      ${used} ?r a fb:TraitRecord ; fb:organGroup ?og ; fb:traitGroup ?tg ; fb:bearer ?b ; fb:quality ?q ; fb:taxon ?t . ?b rdfs:label ?bl . ?q rdfs:label ?ql . ${NOT_BLOCKED} }
      GROUP BY ?og ?tg ?b ?q ORDER BY DESC(?taxa) LIMIT 50`);
    if (!box.isConnected) return;
    box.innerHTML = `<p><b class="num">${n(taxaN)}</b> taxa and <b class="num">${n(recordsN)}</b> records use this term, or a narrower one. Records that failed a check are not counted.</p>
      <p class="muted">The traits that use it most, each linked to the list of taxa in the Traits browser:</p>
      <div class="tablewrap"><table class="results"><thead><tr><th scope="col">Trait</th><th scope="col" class="num">Taxa</th></tr></thead><tbody>${combos.map((r) => `<tr><td><a href="#/traits/${local(r.og)}/${local(r.tg)}/${encodeURIComponent(local(r.b) + "~" + local(r.q))}">${esc(r.blabel)} ${esc(r.qlabel)}</a></td><td class="num">${n(r.taxa)}</td></tr>`).join("")}</tbody></table></div>
      <p><a href="#/identify">Identify a plant by its traits</a></p>`;
  } catch (err) {
    if (box.isConnected) box.innerHTML = `<p class="error">${esc(err.message)}</p>`;
  }
}

/* ---------------------------------------------------------------- router */
// Pages render one at a time, in order: a slow page that finishes after the reader has moved on
// would otherwise overwrite the newer page (or fail on its vanished elements and show an error).
// Navigations queued behind a slow page collapse into one render of the current address.
let routing = Promise.resolve();
let routeQueued = false;
function route() {
  if (routeQueued) return routing;
  routeQueued = true;
  routing = routing.then(() => { routeQueued = false; return renderRoute(); });
  return routing;
}
const PAGE_TITLES = { overview: "", taxa: "Taxa", taxon: "Taxon", traits: "Traits", identify: "Identify", query: "Query", coverage: "Coverage", map: "Map", patterns: "Patterns", compare: "Compare", about: "About", downloads: "Downloads", term: "Term" };
async function renderRoute() {
  const [path, qs] = location.hash.replace(/^#/, "").split("?");
  const parts = (path || "/").split("/").filter(Boolean);
  const section = parts[0] || "overview";
  setTitle(PAGE_TITLES[section] ?? "Page not found"); // pages that know more (a taxon, a term) refine it
  const nav = { taxon: "taxa", term: "traits" }[section] || section;
  document.querySelectorAll(".mainnav a").forEach((a) => {
    if (a.dataset.nav === nav) {
      a.setAttribute("aria-current", "page");
      const bar = a.parentElement; // a phone shows part of the row: the current section is brought into view
      if (bar.scrollWidth > bar.clientWidth) bar.scrollLeft = Math.max(0, a.offsetLeft - (bar.clientWidth - a.offsetWidth) / 2);
    } else a.removeAttribute("aria-current");
  });
  try {
    if (section === "overview") await overview();
    else if (section === "taxa") await taxa();
    else if (section === "taxon") await taxa(parts.slice(1).join("/"));
    else if (section === "term") await termPage(parts.slice(1).join("/"));
    else if (section === "traits") await traits(parts[1], parts[2], parts[3], new URLSearchParams(qs || ""));
    else if (section === "identify") await identify();
    else if (section === "query") await query(new URLSearchParams(qs || ""));
    else if (section === "coverage") await coverage();
    else if (section === "map") await placesMap();
    else if (section === "patterns") await patterns(parts[1]);
    else if (section === "compare") await compare(parts[1], parts[2]);
    else if (section === "about") await about();
    else if (section === "downloads") await downloads();
    else setView(`<h1>Page not found</h1><p><a href="#/">Go to the overview</a>.</p>`);
  } catch (err) {
    setView(`<h1>Could not load the atlas</h1><p class="error">${esc(err.message)}</p>
      <p>The connection to the trait service may have been interrupted.</p><button id="retry-atlas" type="button">Retry</button>`);
    document.getElementById("retry-atlas").addEventListener("click", route);
  }
}
window.addEventListener("hashchange", route);
route();
