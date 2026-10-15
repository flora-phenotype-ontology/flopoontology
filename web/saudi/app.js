/* Saudi Flora Trait Atlas: a browser over the SPARQL endpoint at /sparql. */
"use strict";

const FB = "http://phenomebrowser.net/flopo/browse#";
const TAXON = "http://phenomebrowser.net/flopo/taxon/";
const PREFIX = `PREFIX fb: <${FB}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX obo: <http://purl.obolibrary.org/obo/>
`;
const view = document.getElementById("view");
const cache = new Map();

/* ---------------------------------------------------------------- helpers */
async function sparql(query, { raw = false } = {}) {
  const body = new URLSearchParams({ query: raw ? query : PREFIX + query });
  const response = await fetch("/sparql", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/sparql-results+json" },
    body,
  });
  if (!response.ok) throw new Error(await response.text());
  const json = await response.json();
  if (json.boolean !== undefined) return [{ result: String(json.boolean) }];
  return json.results.bindings.map((b) => Object.fromEntries(Object.entries(b).map(([k, v]) => [k, v.value])));
}
async function cached(key, fn) {
  if (!cache.has(key)) cache.set(key, fn());
  return cache.get(key);
}
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const iriLiteral = (iri) => `<${iri.replace(/[<>"{}|^`\\\s]/g, "")}>`;
const taxonKey = (iri) => iri.startsWith(TAXON) ? iri.slice(TAXON.length) : iri;
const taxonHref = (iri) => `#/taxon/${encodeURIComponent(taxonKey(iri))}`;
const local = (iri) => iri.replace(/^.*[#/]/, "");
const curie = (iri) => local(iri).replace("_", ":");
const n = (x) => Number(x).toLocaleString("en");
const sourceClass = (label) => (/collenette/i.test(label) ? "collenette" : "ncvc");
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
function termLink(iri, label) {
  if (!iri) return esc(label);
  return `<a href="${esc(iri)}" target="_blank" rel="noopener" title="${esc(curie(iri))}">${esc(label)}</a>`;
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
const summary = () => cached("summary", () => fetch("/summary.json").then((r) => r.json()));
const sources = () =>
  cached("sources", () => sparql(`SELECT ?s (SAMPLE(?l) AS ?label) (SAMPLE(?t) AS ?title) WHERE { ?s a fb:Source ; rdfs:label ?l ; <http://purl.org/dc/terms/title> ?t } GROUP BY ?s`));

function atlasTable(cells, organs, traits, { link = true, caption = "" } = {}) {
  const max = Math.max(1, ...cells.map((c) => +c.value));
  const lookup = new Map(cells.map((c) => [c.og + "|" + c.tg, c]));
  const usedOrgans = organs.filter((o) => cells.some((c) => c.og === o.g));
  const usedTraits = traits.filter((t) => cells.some((c) => c.tg === t.g));
  return html`<table class="atlas">
    ${caption ? `<caption>${caption}</caption>` : ""}
    <thead><tr><th></th>${usedTraits.map((t) => `<th scope="col">${esc(t.label)}</th>`).join("")}</tr></thead>
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
    cached("atlas", () =>
      sparql(`SELECT ?og ?tg (COUNT(DISTINCT ?t) AS ?taxa) (COUNT(?r) AS ?n) WHERE {
        ?r a fb:TraitRecord ; fb:organGroup ?og ; fb:traitGroup ?tg ; fb:taxon ?t } GROUP BY ?og ?tg`)
    ),
  ]);
  const keys = Object.keys(s).filter((k) => s[k] && s[k].phenotype_rows !== undefined);
  const records = keys.reduce((a, k) => a + (s[k].assertions || 0), 0);
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
          <span class="muted num">${n(s.taxa.per_source[k] || 0)} taxa, ${n(sk.assertions)} trait records, ${n(sk.occurrences || 0)} place records</span></div>
        <div><div class="bar" title="${Math.round(share * 100)}% of transcribed statements are FLOPO annotations"><i style="width:${share * 100}%"></i></div>
          <span class="muted num">${n(sk.rows_formalized)} of ${n(sk.phenotype_rows)} transcribed trait statements annotated (${Math.round(share * 100)}%)</span></div>
      </div>`;
    })
    .join("");
  setView(html`
    <section class="intro">
      <div>
        <h1>Traits of the Saudi flora</h1>
        <p class="lede">Every trait stated in the source floras is recorded as an RDF annotation: a taxon,
          a FLOPO phenotype class built from a Plant Ontology part and a PATO quality, and the sentence it came from.</p>
        <div class="figures">
          <div class="figure"><b class="num">${n(s.taxa.taxa)}</b><span>taxa, ${n(s.taxa.with_wfo)} matched to World Flora Online</span></div>
          <div class="figure"><b class="num">${n(records)}</b><span>trait annotations</span></div>
          <div class="figure"><b class="num">${Math.round((formal / Math.max(rows, 1)) * 100)}%</b><span>of ${n(rows)} transcribed trait statements captured</span></div>
          <div class="figure"><b class="num">${n(occurrences)}</b><span>records of where taxa grow</span></div>
        </div>
        <p class="muted">Each number in the atlas counts the taxa with at least one trait for that plant part and kind of trait. Select a cell to see them.</p>
      </div>
      <div>${atlasTable(atlasCells, g.organs, g.traits, { caption: "Taxa with an annotation, by plant part and kind of trait" })}</div>
    </section>
    <h2>Sources</h2>
    <div class="sources">${srcRows}</div>`);
}

/* ---------------------------------------------------------------- taxa */
const taxonIndex = () =>
  cached("taxa", async () => {
    const [base, counts, arabic] = await Promise.all([
      sparql(`SELECT ?t (SAMPLE(?l) AS ?label) (SAMPLE(?f) AS ?family) WHERE { ?t a fb:Taxon ; rdfs:label ?l . OPTIONAL { ?t fb:family ?f } } GROUP BY ?t`),
      sparql(`SELECT ?t (COUNT(?r) AS ?n) WHERE { ?r a fb:TraitRecord ; fb:taxon ?t } GROUP BY ?t`),
      sparql(`SELECT ?t (GROUP_CONCAT(?ar; separator=" ") AS ?arabic) WHERE { ?t fb:vernacularName ?ar } GROUP BY ?t`),
    ]);
    const count = Object.fromEntries(counts.map((r) => [r.t, r.n]));
    const ar = Object.fromEntries(arabic.map((r) => [r.t, r.arabic]));
    return base.map((r) => ({ ...r, n: count[r.t] || 0, arabic: ar[r.t] || "" }));
  });

function taxonList(rows, filter, current) {
  const f = filter.trim().toLowerCase();
  const shown = rows.filter((r) => !f || r.label.toLowerCase().includes(f) || (r.family || "").toLowerCase().includes(f) || (r.arabic || "").includes(filter.trim()));
  const byFamily = new Map();
  for (const r of shown.sort((a, b) => (a.family || "~").localeCompare(b.family || "~") || a.label.localeCompare(b.label))) {
    const fam = r.family || "Family not resolved";
    if (!byFamily.has(fam)) byFamily.set(fam, []);
    byFamily.get(fam).push(r);
  }
  return [...byFamily]
    .map(([fam, list]) => `<h4>${esc(fam)}</h4>` + list.map((r) => `<a href="${taxonHref(r.t)}" class="${r.t === current ? "current" : ""}"><span class="sci">${esc(r.label)}</span><small class="num">${r.n}</small></a>`).join(""))
    .join("") || `<p class="muted">No taxon matches “${esc(filter)}”.</p>`;
}

async function taxa(key) {
  const current = key ? TAXON + decodeURIComponent(key) : "";
  if (!cache.has("taxa")) setView(`<p class="loading">Loading the taxon list…</p>`);
  const rows = await taxonIndex();
  const filterValue = sessionStorage.getItem("taxonFilter") || "";
  setView(html`<div class="split">
      <aside class="listpane">
        <label for="tfilter" class="col-title">Find a taxon by name, family or Arabic name</label>
        <input id="tfilter" type="search" value="${esc(filterValue)}" placeholder="e.g. Acacia, Lamiaceae, سدر">
        <div class="taxonlist" id="tlist">${taxonList(rows, filterValue, current)}</div>
      </aside>
      <section id="tpane">${current ? `<p class="loading">Loading…</p>` : `<h1>${n(rows.length)} taxa</h1><p class="muted">Choose a taxon to see its traits, sources and where it grows. The number after each name counts its trait annotations.</p>`}</section>
    </div>`);
  const input = document.getElementById("tfilter");
  input.addEventListener("input", () => {
    try { sessionStorage.setItem("taxonFilter", input.value); } catch (e) { /* storage unavailable */ }
    document.getElementById("tlist").innerHTML = taxonList(rows, input.value, current);
  });
  const active = document.querySelector(".taxonlist a.current");
  if (active) active.scrollIntoView({ block: "center" });
  if (current) await taxonPage(current);
}

async function taxonPage(t) {
  const T = iriLiteral(t);
  const [g, info, names, records, merged, places, growth, pending, notes, conflicts] = await Promise.all([
    groups(),
    sparql(`SELECT (SAMPLE(?l) AS ?label) (SAMPLE(?a) AS ?auth) (SAMPLE(?f) AS ?family) (SAMPLE(?o) AS ?order) (SAMPLE(?w) AS ?wfo)
      (GROUP_CONCAT(DISTINCT ?ar; separator="، ") AS ?arabic) (SAMPLE(?emin) AS ?emin) (SAMPLE(?emax) AS ?emax) (SAMPLE(?nr) AS ?range) WHERE {
      ${T} rdfs:label ?l . OPTIONAL { ${T} fb:authorship ?a } OPTIONAL { ${T} fb:family ?f } OPTIONAL { ${T} fb:order ?o }
      OPTIONAL { ${T} fb:wfo ?w } OPTIONAL { ${T} fb:vernacularName ?ar } OPTIONAL { ${T} fb:nativeRange ?nr }
      OPTIONAL { ${T} fb:elevationMin ?emin ; fb:elevationMax ?emax } }`),
    sparql(`SELECT ?name ?src (GROUP_CONCAT(DISTINCT ?page; separator=", ") AS ?pages) (SAMPLE(?st) AS ?status) WHERE {
      ${T} fb:printedName ?pn . ?pn fb:name ?name ; fb:source/rdfs:label ?src .
      OPTIONAL { ?pn fb:page ?page } OPTIONAL { ?pn fb:nameStatus ?st } } GROUP BY ?name ?src`),
    sparql(`SELECT ?r (SAMPLE(?lab) AS ?label) (SAMPLE(?og) AS ?organ) (SAMPLE(?tg) AS ?trait) (SAMPLE(?src) AS ?source)
      (SAMPLE(?st) AS ?status) (SAMPLE(?tx) AS ?text) (SAMPLE(?cx) AS ?context) (SAMPLE(?fc) AS ?fclass) (SAMPLE(?fcl) AS ?flabel)
      (SAMPLE(?q) AS ?quality) (SAMPLE(?ql) AS ?qlabel) (SAMPLE(?b) AS ?bearer) (SAMPLE(?bl) AS ?blabel) (SAMPLE(?qual) AS ?qualifier)
      (SAMPLE(?at) AS ?attribute) (SAMPLE(?rel) AS ?relation) (SAMPLE(?fv) AS ?from) (SAMPLE(?fvl) AS ?fromLabel)
      (SAMPLE(?tv) AS ?to) (SAMPLE(?tvl) AS ?toLabel) (SAMPLE(?ftx) AS ?fromText) (SAMPLE(?ttx) AS ?toText) (SAMPLE(?u) AS ?unit) (SAMPLE(?ul) AS ?unitLabel) (SAMPLE(?fac) AS ?fac) (SAMPLE(?neg) AS ?negated) WHERE {
      ?r a fb:TraitRecord ; fb:taxon ${T} ; rdfs:label ?lab ; fb:organGroup ?og ; fb:traitGroup ?tg ;
         fb:source/rdfs:label ?src ; fb:status ?st ; fb:text ?tx ; fb:quality ?q ; fb:bearer ?b ; fb:negated ?neg .
      OPTIONAL { ?q rdfs:label ?ql } OPTIONAL { ?b rdfs:label ?bl }
      OPTIONAL { ?r fb:context ?cx } OPTIONAL { ?r fb:qualifier ?qual } OPTIONAL { ?r fb:attribute ?at }
      OPTIONAL { ?r fb:relation ?rel ; fb:fromValue ?fv ; fb:toValue ?tv . OPTIONAL { ?fv rdfs:label ?fvl } OPTIONAL { ?tv rdfs:label ?tvl }
                 OPTIONAL { ?r fb:fromText ?ftx } OPTIONAL { ?r fb:toText ?ttx } }
      OPTIONAL { ?r fb:unit ?u . OPTIONAL { ?u rdfs:label ?ul } } OPTIONAL { ?r fb:phenotypeClass ?fac }
      OPTIONAL { ?r fb:flopoClass ?fc . OPTIONAL { ?fc rdfs:label ?fcl } } } GROUP BY ?r`),
    sparql(`SELECT ?m (SAMPLE(?l) AS ?label) (SAMPLE(?b) AS ?bearer) (SAMPLE(?a) AS ?attribute) (SAMPLE(?fac) AS ?fac)
      (SAMPLE(?u) AS ?unit) (SAMPLE(?n) AS ?sources) (GROUP_CONCAT(STR(?mem); separator=" ") AS ?members) WHERE {
      ?m a fb:MergedTrait ; fb:taxon ${T} ; rdfs:label ?l ; fb:bearer ?b ; fb:attribute ?a ; fb:phenotypeClass ?fac ;
         fb:unit ?u ; fb:sourceCount ?n ; fb:member ?mem } GROUP BY ?m`),
    sparql(`SELECT ?region (SAMPLE(?rl) AS ?rlabel) ?loc (SAMPLE(?lat) AS ?la) (SAMPLE(?lon) AS ?lo) (GROUP_CONCAT(DISTINCT ?src; separator="|") AS ?sources) WHERE {
      ?o a fb:Occurrence ; fb:taxon ${T} ; fb:source/rdfs:label ?src .
      OPTIONAL { ?o fb:region ?region . ?region rdfs:label ?rl } OPTIONAL { ?o fb:locality ?loc }
      OPTIONAL { ?o fb:lat ?lat ; fb:lon ?lon } } GROUP BY ?region ?loc`),
    sparql(`SELECT ?label (GROUP_CONCAT(DISTINCT ?v; separator="; ") AS ?value) (SAMPLE(?src) AS ?source) WHERE {
      ?g a fb:GrowthTrait ; fb:taxon ${T} ; rdfs:label ?label ; fb:value ?v ; fb:source/rdfs:label ?src FILTER(lang(?v) = "") } GROUP BY ?label`),
    sparql(`SELECT ?text ?reason ?context ?src WHERE { ?p a fb:PendingStatement ; fb:taxon ${T} ; fb:text ?text ; fb:reason ?reason ;
      fb:source/rdfs:label ?src . OPTIONAL { ?p fb:context ?context } }`),
    sparql(`SELECT ?kind ?text ?src WHERE { VALUES ?kind { fb:abundance fb:habitat } ${T} ?kind ?node . ?node rdfs:label ?text ; fb:source/rdfs:label ?src }`),
    sparql(`SELECT ?c (SAMPLE(?k) AS ?kind) (SAMPLE(?note) AS ?note) (SAMPLE(?bs) AS ?between) (GROUP_CONCAT(STR(?m); separator=" ") AS ?members) WHERE {
      ?c a fb:Conflict ; fb:taxon ${T} ; fb:kind ?k ; rdfs:comment ?note ; fb:betweenSources ?bs ; fb:member ?m } GROUP BY ?c`),
  ]);
  const pane = document.getElementById("tpane");
  if (!pane) return;
  const i = info[0] || {};
  const nameRows = names
    .map((x) => `<li><span class="sci">${esc(x.name)}</span> <span class="chip ${sourceClass(x.src)}">${esc(x.src)}</span>${x.pages ? ` <span class="muted">p. ${esc(x.pages)}</span>` : ""}${x.status && x.status !== "Accepted" && x.status !== "Exact" ? ` <span class="muted">(${esc(x.status.toLowerCase())} in WFO)</span>` : ""}</li>`)
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
  const STATUS_TIP = "Admitted for review, not yet accepted by the gates";
  const valueCell = (r) => {
    if (r.relation) {
      const kind = { continuum: "continuum", taxon_level_alternatives: "alternatives in the taxon", temporal_transition: "change over time" }[r.relation] || r.relation;
      const end = (iri, label, verbatim) => {
        const link = termLink(iri, label || curie(iri));
        return verbatim && label && verbatim.toLowerCase() !== label.toLowerCase() ? `${link} <span class="muted">“${esc(verbatim)}”</span>` : link;
      };
      return `${end(r.from, r.fromLabel, r.fromText)} → ${end(r.to, r.toLabel, r.toText)} <span class="muted">(${esc(kind)})</span>`;
    }
    if (r.fclass) return termLink(r.fclass, r.flabel || curie(r.fclass));
    if (r.unit) return `${termLink(r.attribute || r.quality, r.qlabel || curie(r.quality))} <span class="muted">in</span> ${termLink(r.unit, r.unitLabel || curie(r.unit))}`;
    const base = termLink(r.quality, r.qlabel || curie(r.quality));
    return r.negated === "true" ? `<span class="muted">not</span> ${base}` : base;
  };
  const owlLink = (iri) => iri ? ` <a href="#/query?describe=${encodeURIComponent(iri)}" title="OWL definition of the annotation class">OWL class</a>` : "";
  // Contradictions: record -> notes of the conflicts it takes part in
  const byIriAll = new Map(records.map((r) => [r.r, r]));
  const conflictOf = new Map();
  const conflictItems = conflicts.map((c) => {
    const members = c.members.split(" ").map((x) => byIriAll.get(x)).filter(Boolean);
    members.forEach((m) => (conflictOf.get(m.r) || conflictOf.set(m.r, []).get(m.r)).push(c.note));
    const where = c.between === "true" ? "the sources disagree" : "within one source";
    return `<li>${members.map((m) => `<b>${esc(m.label)}</b> <span class="chip ${sourceClass(m.source)}">${esc(m.source)}</span>`).join(" <span class=\"muted\">versus</span> ")}
      <br><span class="muted">${esc(c.kind)}, ${where}: ${esc(c.note)}</span></li>`;
  }).join("");
  const recordRow = (r, sub = false) => {
    const id = `d${rowId++}`;
    const clash = conflictOf.has(r.r) ? ` <span class="chip conflict" title="${esc(conflictOf.get(r.r).join("; "))}">conflict</span>` : "";
    const status = (r.status === "accepted" ? "" : `<span class="chip review" title="${STATUS_TIP}">${esc(r.status)}</span>`) + clash;
    return `<tr class="rec${sub ? " sub" : ""}" data-detail="${id}" tabindex="0"><td class="q">${sub ? "<span class=\"muted\">↳</span> " : ""}${esc(r.label)}${r.qualifier ? ` <span class="muted">(${esc(r.qualifier)})</span>` : ""}</td>
      <td>${valueCell(r)}</td>
      <td><span class="chip ${sourceClass(r.source)}">${esc(r.source)}</span> ${status}</td></tr>
      <tr class="detail" id="${id}" hidden><td colspan="3">${highlight(r.context, r.text)}<br>
        <span class="muted">Annotation <a href="#/query?describe=${encodeURIComponent(r.r)}">${esc(local(r.r))}</a>: bearer ${termLink(r.bearer, r.blabel || curie(r.bearer))}${r.relation ? "" : `, quality ${termLink(r.quality, r.qlabel || curie(r.quality))}`}${r.unit ? `, unit ${termLink(r.unit, curie(r.unit))}` : ""}${r.fclass ? `, FLOPO class ${termLink(r.fclass, curie(r.fclass))}` : ""}${owlLink(r.fac)}</span></td></tr>`;
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
      return `<tr><th colspan="3">${esc(g.label[og] || "Other")}</th></tr>` + mergedRows
        + list.filter((r) => !inMerged.has(r.r)).map((r) => recordRow(r)).join("");
    })
    .join("");

  const regions = new Map();
  for (const p of places) if (p.region) regions.set(p.region, p.rlabel);
  const points = places.filter((p) => p.la && p.lo);
  const localities = [...new Set(places.filter((p) => p.loc).map((p) => p.loc))];
  const notesHtml = notes.map((x) => `<dt>${x.kind.endsWith("abundance") ? "Abundance" : "Habitat"}</dt><dd>${esc(x.text)} <span class="chip ${sourceClass(x.src)}">${esc(x.src)}</span></dd>`).join("");
  const growthHtml = growth.map((x) => `<dt>${esc(x.label)}</dt><dd>${esc(x.value)}</dd>`).join("");

  pane.innerHTML = html`
    <div class="taxon-head">
      <h1>${esc(i.label)}</h1>
      ${i.auth ? `<div class="auth">${esc(i.auth)}</div>` : ""}
      <div class="taxon-meta">
        ${i.family ? `<span>${esc(i.family)}${i.order ? `, ${esc(i.order)}` : ""}</span>` : ""}
        ${i.arabic ? `<span class="ar" lang="ar">${esc(i.arabic)}</span>` : ""}
        ${i.wfo ? `<a href="https://list.worldfloraonline.org/${esc(i.wfo)}" target="_blank" rel="noopener">World Flora Online ${esc(i.wfo)}</a>` : `<span>Not matched to World Flora Online</span>`}
      </div>
    </div>
    <div class="taxon-grid">
      <div>
        <h2>Traits</h2>
        ${conflicts.length ? `<div class="conflicts"><h3>${n(conflicts.length)} contradictory statement${conflicts.length > 1 ? "s" : ""}</h3>
          <p class="muted">These statements cannot both be true of one plant. A taxon covers many plants, so the sources may describe different plants or one may be wrong.</p><ul>${conflictItems}</ul></div>` : ""}
        ${records.length ? `<p class="muted">${n(records.length)} annotations. Select one to see the sentence it was read from.</p><table class="traits">${traitRows}</table>` : `<p class="muted">No trait annotations yet.</p>`}
        ${pending.length ? `<details class="pending"><summary>${n(pending.length)} statements not yet annotated</summary><ul>${pending.map((p) => `<li>${highlight(p.context, p.text)} <span class="muted">— ${esc(p.reason.replace(/_/g, " "))}</span></li>`).join("")}</ul></details>` : ""}
      </div>
      <div>
        <h2>Trait fingerprint</h2>
        <div class="fingerprint">${records.length ? atlasTable(fpCells, g.organs, g.traits, { link: false }) : `<p class="muted">Nothing to show.</p>`}</div>
        <h2>Where it grows</h2>
        ${regions.size ? `<div class="regions">${[...regions].map(([, l]) => `<span class="region on">${esc(l)}</span>`).join("")}</div>` : `<p class="muted">No region recorded.</p>`}
        ${points.length ? `<div class="map" id="map" role="img" aria-label="Map of recorded localities"></div>` : ""}
        ${localities.length ? `<p class="muted" style="font-size:.88rem">Localities: ${localities.map(esc).join("; ")}</p>` : ""}
        ${i.emin ? `<p>Elevation ${n(i.emin)}${i.emax !== i.emin ? `–${n(i.emax)}` : ""} m <span class="muted">(Collenette, converted from feet)</span></p>` : ""}
        ${notesHtml || i.range ? `<h3>Notes</h3><dl class="kv">${i.range ? `<dt>Native range</dt><dd>${esc(i.range)}</dd>` : ""}${notesHtml}</dl>` : ""}
        ${growthHtml ? `<h3>Ecology and cultivation <span class="chip">NCVC 2024</span></h3><dl class="kv">${growthHtml}</dl>` : ""}
        <h3>Names in the sources</h3><ul>${nameRows}</ul>
        <p><a href="#/query?taxon=${encodeURIComponent(t)}">Query this taxon in SPARQL</a></p>
      </div>
    </div>`;
  pane.querySelectorAll("tr.rec").forEach((tr) => {
    const toggle = () => {
      const d = document.getElementById(tr.dataset.detail);
      d.hidden = !d.hidden;
    };
    tr.addEventListener("click", (e) => { if (!e.target.closest("a")) toggle(); });
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
  });
  if (points.length && window.L) {
    const map = L.map("map", { scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 12, attribution: "© OpenStreetMap contributors" }).addTo(map);
    const markers = points.map((p) => L.circleMarker([+p.la, +p.lo], { radius: 6, color: "#2f5d50", weight: 2, fillColor: "#b8862b", fillOpacity: 0.8 }).bindTooltip(esc(p.loc || p.rlabel || "")).addTo(map));
    map.fitBounds(L.featureGroup(markers).getBounds().pad(0.4), { maxZoom: 8 });
  }
}

/* ---------------------------------------------------------------- traits browser */
async function traits(organKey, traitKey, valueKey) {
  const g = await groups();
  const og = organKey ? FB + organKey : "";
  const tg = traitKey ? FB + traitKey : "";
  setView(`<h1>Browse traits</h1><p class="muted">Choose a plant part, then a kind of trait, then a value to list the taxa that have it.</p><div class="cols"><div id="c1"></div><div id="c2"></div><div id="c3"></div></div>`);
  const organCounts = await cached("organCounts", () => sparql(`SELECT ?og (COUNT(DISTINCT ?t) AS ?n) WHERE { ?r a fb:TraitRecord ; fb:organGroup ?og ; fb:taxon ?t } GROUP BY ?og`));
  const oc = Object.fromEntries(organCounts.map((r) => [r.og, r.n]));
  document.getElementById("c1").innerHTML = `<p class="col-title">Plant part</p><ul class="pick">${g.organs
    .filter((o) => oc[o.g])
    .map((o) => `<li><a class="${o.g === og ? "current" : ""}" href="#/traits/${local(o.g)}">${esc(o.label)}<small class="num">${n(oc[o.g])}</small></a></li>`)
    .join("")}</ul>`;
  if (!og) return;
  const traitCounts = await sparql(`SELECT ?tg (COUNT(DISTINCT ?t) AS ?n) WHERE { ?r a fb:TraitRecord ; fb:organGroup ${iriLiteral(og)} ; fb:traitGroup ?tg ; fb:taxon ?t } GROUP BY ?tg`);
  const tc = Object.fromEntries(traitCounts.map((r) => [r.tg, r.n]));
  document.getElementById("c2").innerHTML = `<p class="col-title">Kind of trait</p><ul class="pick">${g.traits
    .filter((t) => tc[t.g])
    .map((t) => `<li><a class="${t.g === tg ? "current" : ""}" href="#/traits/${organKey}/${local(t.g)}">${esc(t.label)}<small class="num">${n(tc[t.g])}</small></a></li>`)
    .join("")}</ul>`;
  if (!tg) return;
  const values = await sparql(`SELECT ?b ?q (SAMPLE(?bl) AS ?blabel) (SAMPLE(?ql) AS ?qlabel) (COUNT(DISTINCT ?t) AS ?n) WHERE {
    ?r a fb:TraitRecord ; fb:organGroup ${iriLiteral(og)} ; fb:traitGroup ${iriLiteral(tg)} ; fb:bearer ?b ; fb:quality ?q ; fb:taxon ?t ; fb:negated false .
    ?b rdfs:label ?bl . ?q rdfs:label ?ql } GROUP BY ?b ?q ORDER BY DESC(?n)`);
  const c3 = document.getElementById("c3");
  const selected = valueKey ? decodeURIComponent(valueKey) : "";
  c3.innerHTML = `<p class="col-title">Value (part and quality), with number of taxa</p><ul class="pick">${values
    .map((v) => {
      const key = `${local(v.b)}~${local(v.q)}`;
      return `<li><a class="${key === selected ? "current" : ""}" href="#/traits/${organKey}/${traitKey}/${encodeURIComponent(key)}">${esc(v.blabel)} ${esc(v.qlabel)}<small class="num">${n(v.n)}</small></a></li>`;
    })
    .join("")}</ul>`;
  if (!selected) return;
  const [b, q] = selected.split("~");
  const taxaRows = await sparql(`SELECT ?t (SAMPLE(?l) AS ?label) (SAMPLE(?f) AS ?family) (GROUP_CONCAT(DISTINCT ?lab; separator="; ") AS ?values) (GROUP_CONCAT(DISTINCT ?src; separator="|") AS ?sources) WHERE {
    ?r a fb:TraitRecord ; fb:bearer obo:${b} ; fb:quality obo:${q} ; fb:organGroup ${iriLiteral(og)} ; fb:taxon ?t ; rdfs:label ?lab ; fb:negated false ; fb:source/rdfs:label ?src .
    ?t rdfs:label ?l . OPTIONAL { ?t fb:family ?f } } GROUP BY ?t ORDER BY ?label`);
  const value = values.find((v) => `${local(v.b)}~${local(v.q)}` === selected);
  c3.insertAdjacentHTML(
    "beforeend",
    `<h2>${esc(value ? value.blabel + " " + value.qlabel : selected)}: ${n(taxaRows.length)} taxa</h2>
     <table class="results"><thead><tr><th>Taxon</th><th>Family</th><th>Annotation</th><th>Source</th></tr></thead><tbody>${taxaRows
       .map((r) => `<tr><td><a class="sci" href="${taxonHref(r.t)}">${esc(r.label)}</a></td><td>${esc(r.family || "")}</td><td>${esc(r.values)}</td><td>${r.sources.split("|").map((s) => `<span class="chip ${sourceClass(s)}">${esc(s)}</span>`).join(" ")}</td></tr>`)
       .join("")}</tbody></table>`
  );
  c3.querySelector("h2").scrollIntoView({ block: "nearest" });
}

/* ---------------------------------------------------------------- identify */
const valueChoices = () =>
  cached("valueChoices", () =>
    sparql(`SELECT ?og ?q (SAMPLE(?ql) AS ?label) (COUNT(DISTINCT ?t) AS ?n) WHERE {
      ?r a fb:TraitRecord ; fb:organGroup ?og ; fb:quality ?q ; fb:taxon ?t ; fb:negated false . ?q rdfs:label ?ql
      FILTER NOT EXISTS { ?r fb:low ?x } } GROUP BY ?og ?q HAVING (COUNT(DISTINCT ?t) > 1) ORDER BY ?label`)
  );

async function identify() {
  const [g, choices] = await Promise.all([groups(), valueChoices()]);
  const organs = g.organs.filter((o) => choices.some((c) => c.og === o.g));
  const conditionHtml = (i) => `<div class="condition" data-i="${i}">
      <div class="field"><label for="og${i}">Plant part</label><select id="og${i}">${organs.map((o) => `<option value="${o.g}">${esc(o.label)}</option>`).join("")}</select></div>
      <div class="field"><label for="q${i}">Quality</label><select id="q${i}"></select></div>
      <button type="button" class="ghost" data-remove="${i}" aria-label="Remove this condition">Remove</button></div>`;
  setView(`<h1>Identify</h1><p class="muted">Describe a plant by the traits you can see. Taxa are ranked by how many of your traits their annotations state; a colour also matches its shades (pale yellow matches yellow).</p>
    <div class="conditions" id="conds"></div>
    <div class="toolbar"><button type="button" class="ghost" id="add">Add a trait</button><button type="button" id="run">Find taxa</button></div>
    <div id="idresults"></div>`);
  const conds = document.getElementById("conds");
  let next = 0;
  const fill = (i) => {
    const og = document.getElementById("og" + i).value;
    document.getElementById("q" + i).innerHTML = choices.filter((c) => c.og === og).map((c) => `<option value="${c.q}">${esc(c.label)} (${c.n})</option>`).join("");
  };
  const add = (organ) => {
    const i = next++;
    conds.insertAdjacentHTML("beforeend", conditionHtml(i));
    if (organ) document.getElementById("og" + i).value = organ;
    fill(i);
    document.getElementById("og" + i).addEventListener("change", () => fill(i));
    conds.querySelector(`[data-remove="${i}"]`).addEventListener("click", () => conds.querySelector(`[data-i="${i}"]`).remove());
  };
  add(FB + "organ-flower");
  add(FB + "organ-plant");
  document.getElementById("add").addEventListener("click", () => add());
  document.getElementById("run").addEventListener("click", async () => {
    const picked = [...conds.querySelectorAll(".condition")].map((c) => ({ og: c.querySelector("select[id^=og]").value, q: c.querySelector("select[id^=q]").value })).filter((c) => c.q);
    const out = document.getElementById("idresults");
    if (!picked.length) { out.innerHTML = `<p class="muted">Add at least one trait.</p>`; return; }
    out.innerHTML = `<p class="loading">Searching…</p>`;
    const values = picked.map((c, i) => `(${i} ${iriLiteral(c.og)} ${iriLiteral(c.q)})`).join(" ");
    const rows = await sparql(`SELECT ?t (SAMPLE(?l) AS ?label) (SAMPLE(?f) AS ?family) (COUNT(DISTINCT ?i) AS ?hits) (GROUP_CONCAT(DISTINCT STR(?i); separator=",") AS ?which) (GROUP_CONCAT(DISTINCT ?lab; separator="; ") AS ?evidence) WHERE {
      VALUES (?i ?og ?q) { ${values} }
      ?r a fb:TraitRecord ; fb:organGroup ?og ; fb:quality ?rq ; fb:taxon ?t ; fb:negated false ; rdfs:label ?lab .
      ?rq rdfs:subClassOf* ?q .
      ?t rdfs:label ?l . OPTIONAL { ?t fb:family ?f } } GROUP BY ?t ORDER BY DESC(?hits) ?label LIMIT 200`);
    out.innerHTML = rows.length
      ? `<p class="muted">${n(rows.filter((r) => +r.hits === picked.length).length)} taxa state all ${picked.length} traits.</p><table class="results"><thead><tr><th>Match</th><th>Taxon</th><th>Family</th><th>Matching annotations</th></tr></thead><tbody>${rows
          .map((r) => {
            const hit = new Set(r.which.split(","));
            return `<tr><td><span class="score" title="${r.hits} of ${picked.length}">${picked.map((_, i) => `<i class="${hit.has(String(i)) ? "hit" : ""}"></i>`).join("")}</span></td><td><a class="sci" href="${taxonHref(r.t)}">${esc(r.label)}</a></td><td>${esc(r.family || "")}</td><td>${esc(r.evidence)}</td></tr>`;
          })
          .join("")}</tbody></table>`
      : `<p class="muted">No taxon states any of these traits. Try a broader quality.</p>`;
  });
}

/* ---------------------------------------------------------------- query */
const EXAMPLES = {
  "Taxa with yellow flowers (including shades of yellow)": `PREFIX fb: <${FB}>
PREFIX obo: <http://purl.obolibrary.org/obo/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?taxon ?name ?annotation WHERE {
  ?r a fb:TraitRecord ; fb:taxon ?taxon ; fb:bearer obo:PO_0009046 ;
     fb:quality ?colour ; rdfs:label ?annotation ; fb:negated false .
  ?colour rdfs:subClassOf* obo:FLOPO_0988004 .   # ISCC-NBS yellow
  ?taxon rdfs:label ?name .
} ORDER BY ?name`,
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
  "FLOPO classes most used in the Saudi data": `PREFIX fb: <${FB}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?class (SAMPLE(?l) AS ?label) (COUNT(DISTINCT ?t) AS ?taxa) WHERE {
  ?r fb:flopoClass ?class ; fb:taxon ?t . ?class rdfs:label ?l .
} GROUP BY ?class ORDER BY DESC(?taxa) LIMIT 50`,
  "Taxa recorded in both guides": `PREFIX fb: <${FB}>
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
  if (params.get("describe")) text = `DESCRIBE <${params.get("describe")}>`;
  if (params.get("taxon")) text = `PREFIX fb: <${FB}>\nPREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n\nSELECT ?annotation ?bearer ?quality ?flopoClass ?source WHERE {\n  ?r fb:taxon <${params.get("taxon")}> ; rdfs:label ?annotation ;\n     fb:bearer ?bearer ; fb:quality ?quality ; fb:source/rdfs:label ?source .\n  OPTIONAL { ?r fb:flopoClass ?flopoClass }\n} ORDER BY ?annotation`;
  setView(`<h1>Query</h1><p class="muted">All annotations are RDF. Write SPARQL 1.1 against the endpoint at <code>/sparql</code> (all graphs are queried together; the FLOPO class hierarchy is loaded too). Common prefixes such as <code>fb:</code>, <code>obo:</code> and <code>rdfs:</code> are predefined.</p>
    <div class="toolbar"><label for="ex" class="muted">Examples</label><select id="ex">${Object.keys(EXAMPLES).map((k) => `<option>${esc(k)}</option>`).join("")}</select></div>
    <textarea class="sparql" id="q" spellcheck="false" aria-label="SPARQL query">${esc(text)}</textarea>
    <div class="toolbar"><button type="button" id="runq">Run query</button><a id="csv" href="#">Download as CSV</a><span class="muted" id="qinfo"></span></div>
    <div class="tablewrap" id="qout"></div>`);
  const area = document.getElementById("q");
  document.getElementById("ex").addEventListener("change", (e) => { area.value = EXAMPLES[e.target.value]; });
  const run = async () => {
    const out = document.getElementById("qout");
    const info = document.getElementById("qinfo");
    out.innerHTML = `<p class="loading">Running…</p>`;
    const started = performance.now();
    try {
      if (/^\s*(PREFIX[^\n]*\n\s*)*(DESCRIBE|CONSTRUCT)/i.test(area.value)) {
        const r = await fetch("/sparql?" + new URLSearchParams({ query: area.value }), { headers: { Accept: "text/turtle" } });
        const body = await r.text();
        if (!r.ok) throw new Error(body);
        out.innerHTML = `<pre>${esc(body)}</pre>`;
      } else {
        const rows = await sparql(area.value, { raw: true });
        const cols = rows.length ? Object.keys(rows.reduce((a, r) => Object.assign(a, r), {})) : [];
        out.innerHTML = rows.length
          ? `<table class="results"><thead><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${rows
              .map((r) => `<tr>${cols.map((c) => {
                const v = r[c] ?? "";
                if (v.startsWith(TAXON)) return `<td><a href="${taxonHref(v)}">${esc(taxonKey(v))}</a></td>`;
                if (/^https?:\/\//.test(v)) return `<td><a href="${esc(v)}" target="_blank" rel="noopener">${esc(v.includes("purl.obolibrary.org") ? curie(v) : v)}</a></td>`;
                return `<td>${esc(v)}</td>`;
              }).join("")}</tr>`)
              .join("")}</tbody></table>`
          : `<p class="muted">The query returned no results.</p>`;
        info.textContent = `${n(rows.length)} rows in ${Math.round(performance.now() - started)} ms`;
      }
    } catch (err) {
      out.innerHTML = `<p class="error">${esc(err.message)}</p>`;
      info.textContent = "";
    }
  };
  document.getElementById("runq").addEventListener("click", run);
  area.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") run(); });
  document.getElementById("csv").addEventListener("click", (e) => {
    e.preventDefault();
    window.open("/sparql?" + new URLSearchParams({ query: area.value, format: "csv" }));
  });
  if (params.get("describe") || params.get("taxon")) run();
}

/* ---------------------------------------------------------------- coverage */
async function coverage() {
  const [s, src, reasons] = await Promise.all([
    summary(),
    sources(),
    sparql(`SELECT ?src ?reason (COUNT(*) AS ?n) WHERE { ?p a fb:PendingStatement ; fb:reason ?reason ; fb:source/rdfs:label ?src } GROUP BY ?src ?reason ORDER BY DESC(?n)`),
  ]);
  const keys = Object.keys(s).filter((k) => s[k] && s[k].phenotype_rows !== undefined);
  const blocks = keys
    .map((k) => {
      const meta = src.find((x) => x.s.endsWith("/" + k)) || { label: k };
      const sk = s[k];
      const mine = reasons.filter((r) => r.src === meta.label);
      const max = Math.max(1, ...mine.map((r) => +r.n));
      return `<h2>${esc(meta.label)}</h2>
        <dl class="kv">
          <dt>Trait statements transcribed</dt><dd class="num">${n(sk.phenotype_rows)}</dd>
          <dt>Annotated with FLOPO, PO and PATO</dt><dd class="num">${n(sk.rows_formalized)} (${Math.round((100 * sk.rows_formalized) / Math.max(1, sk.phenotype_rows))}%), of which ${n(sk.gate_accepted || 0)} accepted by the gates and ${n(sk.gate_review || 0)} under review</dd>
          <dt>Kept as text, not yet annotated</dt><dd class="num">${n(sk.pending)}</dd>
        </dl>
        <h3>Why statements are not yet annotated</h3>
        <p class="muted">Open a reason to list its phrases, most frequent first; open a phrase to see the sentences it comes from.</p>
        <div class="reasons">${mine
          .map((r) => `<details class="reason" data-src="${esc(meta.label)}" data-reason="${esc(r.reason)}"><summary><span class="reason-name">${esc(reasonLabel(r.reason))}</span><span class="num">${n(r.n)}</span><span class="bar"><i class="part" style="width:${(100 * r.n) / max}%"></i></span></summary><div class="reason-body"></div></details>`)
          .join("")}</div>`;
    })
    .join("");
  setView(`<h1>Coverage</h1><p>Each guide was transcribed into trait statements, one per plant part and quality. A statement becomes an annotation when its part and quality match ontology terms and it passes FLOPO's checks. The rest are kept with the reason, so they can be added later.</p>
    <p class="muted">Taxa: ${n(s.taxa.taxa)} in total, ${n(s.taxa.with_wfo)} matched to World Flora Online, ${n(s.taxa.families)} families${keys.length > 1 ? `, ${n(s.taxa.in_all_sources)} described in every source` : ""}.</p>${blocks}`);
  view.querySelectorAll("details.reason").forEach((d) => d.addEventListener("toggle", () => { if (d.open) pendingPhrases(d); }));
}

const reasonLabel = (reason) => reason.replace(/_/g, " ").replace(/^no ontology term:/, "no ontology term: ");

/* The pending statements of one source and reason, grouped by phrase (case-folded). */
async function pendingPhrases(d) {
  const body = d.querySelector(".reason-body");
  if (body.dataset.loaded) return;
  body.dataset.loaded = "1";
  body.innerHTML = `<p class="muted">Loading…</p>`;
  try {
    const rows = await sparql(`SELECT ?text ?context ?taxon ?name WHERE {
      ?p a fb:PendingStatement ; fb:reason ${JSON.stringify(d.dataset.reason)} ; fb:source/rdfs:label ${JSON.stringify(d.dataset.src)} ;
         fb:text ?text ; fb:taxon ?taxon . OPTIONAL { ?p fb:context ?context } OPTIONAL { ?taxon rdfs:label ?name } }`);
    const groups = new Map();
    for (const r of rows) {
      const key = r.text.trim().toLowerCase();
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(r);
    }
    const phrases = [...groups.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
    body.innerHTML = `<div class="phrase-tools"><input type="search" placeholder="Filter phrases" aria-label="Filter phrases">
      <span class="muted">${n(phrases.length)} distinct phrases</span>
      <a href="#" class="csv">Download as CSV</a></div>
      <ul class="phrases">${phrases
        .map(([key, occ]) => `<li data-key="${esc(key)}"><details><summary><span>${esc(occ[0].text)}</span>${occ.length > 1 ? ` <span class="num muted">× ${n(occ.length)}</span>` : ""}</summary><ul>${occ
          .map((o) => `<li><a href="${taxonHref(o.taxon)}"><i>${esc(o.name || taxonKey(o.taxon))}</i></a>: ${highlight(o.context, o.text)}</li>`)
          .join("")}</ul></details></li>`)
        .join("")}</ul>`;
    const items = body.querySelectorAll("ul.phrases > li");
    const count = body.querySelector(".phrase-tools .muted");
    body.querySelector("input").addEventListener("input", (e) => {
      const q = e.target.value.trim().toLowerCase();
      let shown = 0;
      items.forEach((li) => { const on = !q || li.dataset.key.includes(q); li.hidden = !on; shown += on; });
      count.textContent = q ? `${n(shown)} of ${n(phrases.length)} phrases` : `${n(phrases.length)} distinct phrases`;
    });
    body.querySelector("a.csv").addEventListener("click", (e) => {
      e.preventDefault();
      const cell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
      const lines = [["phrase", "count", "taxon", "sentence"].join(",")];
      for (const [, occ] of phrases) for (const o of occ) lines.push([o.text, occ.length, o.name || taxonKey(o.taxon), o.context].map(cell).join(","));
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

/* ---------------------------------------------------------------- router */
async function route() {
  const [path, qs] = location.hash.replace(/^#/, "").split("?");
  const parts = (path || "/").split("/").filter(Boolean);
  const section = parts[0] || "overview";
  document.querySelectorAll(".mainnav a").forEach((a) => {
    const on = a.dataset.nav === (section === "taxon" ? "taxa" : section);
    if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  try {
    if (section === "overview") await overview();
    else if (section === "taxa") await taxa();
    else if (section === "taxon") await taxa(parts.slice(1).join("/"));
    else if (section === "traits") await traits(parts[1], parts[2], parts[3]);
    else if (section === "identify") await identify();
    else if (section === "query") await query(new URLSearchParams(qs || ""));
    else if (section === "coverage") await coverage();
    else setView(`<h1>Page not found</h1><p><a href="#/">Go to the overview</a>.</p>`);
  } catch (err) {
    setView(`<h1>Something went wrong</h1><p class="error">${esc(err.message)}</p><p>Check that the server is running and reload the page.</p>`);
  }
}
window.addEventListener("hashchange", route);
route();
