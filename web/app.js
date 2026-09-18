const state = {
  data: null,
  query: "",
  organ: "",
  quality: "",
  selectedTaxon: "",
  selectedTrait: "",
  identifyTraits: new Set(),
};

const el = (id) => document.getElementById(id);

function fmt(n) {
  return Number(n).toLocaleString();
}

function inatUrl(taxon) {
  return `https://www.inaturalist.org/taxa/search?q=${encodeURIComponent(taxon)}`;
}

async function load() {
  const res = await fetch("data/flopo-site-data.json");
  state.data = await res.json();
  state.selectedTaxon = state.data.taxa[0]?.name || "";
  state.selectedTrait = state.data.traits[0]?.id || "";
  renderStatic();
  bindEvents();
  render();
}

function renderStatic() {
  const { summary } = state.data;
  el("metrics").innerHTML = [
    ["Taxa", summary.taxa],
    ["Trait types", summary.traits],
    ["Phenotypes", summary.phenotype_assertions],
  ].map(([label, value]) => `<div class="metric"><strong>${fmt(value)}</strong><span>${label}</span></div>`).join("");

  renderFilter("qualityFilters", Object.keys(summary.quality_groups), "quality");
  renderFilter("organFilters", Object.keys(summary.organ_groups), "organ");
  for (const select of [el("compareA"), el("compareB")]) {
    select.innerHTML = state.data.taxa
      .map((t) => `<option value="${escapeHtml(t.name)}">${escapeHtml(t.name)}</option>`)
      .join("");
  }
  el("compareB").selectedIndex = Math.min(1, state.data.taxa.length - 1);
}

function renderFilter(id, values, key) {
  el(id).innerHTML = values.sort().map((value) => (
    `<button class="chip" data-${key}="${escapeHtml(value)}" type="button">${escapeHtml(value)}</button>`
  )).join("");
}

function bindEvents() {
  el("search").addEventListener("input", (event) => {
    state.query = event.target.value.trim().toLowerCase();
    render();
  });
  el("clearFilters").addEventListener("click", () => {
    state.query = "";
    state.organ = "";
    state.quality = "";
    el("search").value = "";
    render();
  });
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
      button.classList.add("active");
      el(`${button.dataset.view}View`).classList.add("active");
    });
  });
  el("qualityFilters").addEventListener("click", (event) => {
    const value = event.target.dataset.quality;
    if (!value) return;
    state.quality = state.quality === value ? "" : value;
    render();
  });
  el("organFilters").addEventListener("click", (event) => {
    const value = event.target.dataset.organ;
    if (!value) return;
    state.organ = state.organ === value ? "" : value;
    render();
  });
  el("compareA").addEventListener("change", renderCompare);
  el("compareB").addEventListener("change", renderCompare);
}

function assertionsForTaxon(taxon) {
  return state.data.assertions.filter((a) => a.taxon === taxon);
}

function assertionsForTrait(traitId) {
  return state.data.assertions.filter((a) => a.trait_id === traitId);
}

function traitById(id) {
  return state.data.traits.find((t) => t.id === id);
}

function passesFilters(assertion) {
  const trait = traitById(assertion.trait_id);
  const q = state.query;
  const text = [
    assertion.taxon,
    assertion.source_text,
    trait?.label,
    trait?.po_label,
    trait?.pato_label,
  ].join(" ").toLowerCase();
  return (!q || text.includes(q))
    && (!state.organ || trait?.organ_group === state.organ)
    && (!state.quality || trait?.quality_group === state.quality);
}

function filteredTaxa() {
  return state.data.taxa.filter((taxon) => assertionsForTaxon(taxon.name).some(passesFilters));
}

function filteredTraits() {
  return state.data.traits.filter((trait) => assertionsForTrait(trait.id).some(passesFilters));
}

function render() {
  document.querySelectorAll("[data-quality]").forEach((b) => b.classList.toggle("active", b.dataset.quality === state.quality));
  document.querySelectorAll("[data-organ]").forEach((b) => b.classList.toggle("active", b.dataset.organ === state.organ));
  renderTaxa();
  renderTraits();
  renderIdentify();
  renderCompare();
}

function renderTaxa() {
  const taxa = filteredTaxa();
  el("taxonCount").textContent = `${fmt(taxa.length)} shown`;
  el("taxonList").innerHTML = taxa.slice(0, 250).map((taxon) => `
    <button class="row ${taxon.name === state.selectedTaxon ? "active" : ""}" data-taxon="${escapeHtml(taxon.name)}" type="button">
      <span class="row-title">${escapeHtml(taxon.name)}</span>
      <span class="row-meta">${fmt(taxon.trait_count)} majority traits</span>
    </button>
  `).join("");
  el("taxonList").onclick = (event) => {
    const taxon = event.target.closest("[data-taxon]")?.dataset.taxon;
    if (!taxon) return;
    state.selectedTaxon = taxon;
    renderTaxa();
  };
  renderTaxonDetail();
}

function renderTaxonDetail() {
  const taxon = state.selectedTaxon;
  const rows = assertionsForTaxon(taxon).filter(passesFilters);
  el("taxonDetail").innerHTML = `
    <h2>${escapeHtml(taxon)}</h2>
    <p>${fmt(rows.length)} phenotype assertions. Trait types are attribute-level PO+PATO pairs; value states are shown separately and grounded to PATO where possible.</p>
    <div class="toolbar">
      <a class="inat" href="${inatUrl(taxon)}" target="_blank" rel="noopener">iNaturalist images and observations</a>
    </div>
    ${traitTable(rows)}
  `;
}

function renderTraits() {
  const traits = filteredTraits();
  el("traitCount").textContent = `${fmt(traits.length)} shown`;
  el("traitList").innerHTML = traits.slice(0, 250).map((trait) => `
    <button class="row ${trait.id === state.selectedTrait ? "active" : ""}" data-trait="${escapeHtml(trait.id)}" type="button">
      <span class="row-title">${escapeHtml(trait.label)}</span>
      <span class="row-meta">${escapeHtml(trait.organ_group)} / ${escapeHtml(trait.quality_group)} · ${fmt(trait.taxon_count)} taxa</span>
    </button>
  `).join("");
  el("traitList").onclick = (event) => {
    const trait = event.target.closest("[data-trait]")?.dataset.trait;
    if (!trait) return;
    state.selectedTrait = trait;
    renderTraits();
  };
  renderTraitDetail();
}

function renderTraitDetail() {
  const trait = traitById(state.selectedTrait);
  if (!trait) return;
  const rows = assertionsForTrait(trait.id).filter(passesFilters);
  el("traitDetail").innerHTML = `
    <h2>${escapeHtml(trait.label)}</h2>
    <p><span class="badge">${escapeHtml(trait.po_id)}</span> <span class="badge">${escapeHtml(trait.pato_id)}</span></p>
    <p>${fmt(rows.length)} taxon-specific phenotype assertions instantiate this trait type.</p>
    ${traitTable(rows)}
  `;
}

function traitTable(rows) {
  if (!rows.length) return `<p class="muted">No matching phenotype assertions.</p>`;
  return `
    <table class="trait-table">
      <thead><tr><th>Taxon</th><th>Trait Attribute</th><th>Value</th><th>Evidence</th><th>Support</th></tr></thead>
      <tbody>
        ${rows.slice(0, 120).map((row) => {
          const trait = traitById(row.trait_id);
          return `<tr>
            <td>${escapeHtml(row.taxon)}</td>
            <td>${escapeHtml(trait?.label || row.trait_id)}</td>
            <td>${valueCell(row)}</td>
            <td>${escapeHtml(row.source_text || "")}</td>
            <td>${row.support}/3</td>
          </tr>`;
        }).join("")}
      </tbody>
    </table>
  `;
}

function valueCell(row) {
  const numeric = row.value_low && row.value_high
    ? `${escapeHtml(row.value_low)}${row.value_low === row.value_high ? "" : `-${escapeHtml(row.value_high)}`} ${escapeHtml(row.unit || "")}`.trim()
    : "";
  const valueText = row.value_text ? escapeHtml(row.value_text) : "";
  const grounded = (row.value_pato_labels || []).map((label, index) => {
    const id = row.value_pato_ids?.[index] || "";
    return `<span class="badge" title="${escapeHtml(id)}">${escapeHtml(label)}</span>`;
  }).join(" ");
  const flopo = (row.value_flopo_labels || []).map((label, index) => {
    const id = row.value_flopo_ids?.[index] || "";
    return `<span class="badge" title="${escapeHtml(id)}">FLOPO ${escapeHtml(label)}</span>`;
  }).join(" ");
  const badges = [grounded, flopo].filter(Boolean).join(" ");
  if (numeric && valueText) return `${valueText}<br><span class="badge">${numeric}</span> ${badges}`;
  if (numeric) return `<span class="badge">${numeric}</span>`;
  if (valueText || badges) return `${valueText}${badges ? `<br>${badges}` : ""}`;
  return `<span class="muted">attribute only</span>`;
}

function renderCompare() {
  const a = el("compareA").value || state.data.taxa[0]?.name;
  const b = el("compareB").value || state.data.taxa[1]?.name;
  const traitsA = new Set(state.data.taxon_traits[a] || []);
  const traitsB = new Set(state.data.taxon_traits[b] || []);
  const shared = [...traitsA].filter((id) => traitsB.has(id));
  const onlyA = [...traitsA].filter((id) => !traitsB.has(id));
  const onlyB = [...traitsB].filter((id) => !traitsA.has(id));
  const semantic = semanticSimilarity(traitsA, traitsB);
  el("compareResult").innerHTML = `
    <h2>${escapeHtml(a)} vs ${escapeHtml(b)}</h2>
    <p>Exact trait Jaccard: ${(jaccard(traitsA, traitsB) * 100).toFixed(1)}%. Semantic group similarity: ${(semantic * 100).toFixed(1)}%.</p>
    <div class="compare-grid">
      ${traitSetBlock("Shared traits", shared)}
      ${traitSetBlock(`${a} only`, onlyA)}
      ${traitSetBlock(`${b} only`, onlyB)}
    </div>
  `;
}

function traitSetBlock(title, ids) {
  return `<div><h3>${escapeHtml(title)} <span class="badge">${fmt(ids.length)}</span></h3>
    <p>${ids.slice(0, 24).map((id) => escapeHtml(traitById(id)?.label || id)).join("<br>") || "<span class='muted'>None</span>"}</p></div>`;
}

function renderIdentify() {
  const popular = state.data.traits.slice(0, 60);
  el("identifyTraits").innerHTML = popular.map((trait) => `
    <button class="trait-pill ${state.identifyTraits.has(trait.id) ? "active" : ""}" data-pick="${escapeHtml(trait.id)}" type="button">
      ${escapeHtml(trait.label)}
    </button>
  `).join("");
  el("identifyTraits").onclick = (event) => {
    const id = event.target.closest("[data-pick]")?.dataset.pick;
    if (!id) return;
    if (state.identifyTraits.has(id)) state.identifyTraits.delete(id);
    else state.identifyTraits.add(id);
    renderIdentify();
  };
  const selected = [...state.identifyTraits];
  if (!selected.length) {
    el("identifyResult").innerHTML = `<p class="muted">Select traits above to rank candidate taxa.</p>`;
    return;
  }
  const selectedSet = new Set(selected);
  const ranked = state.data.taxa.map((taxon) => {
    const traits = new Set(state.data.taxon_traits[taxon.name] || []);
    return {
      taxon: taxon.name,
      exact: jaccard(selectedSet, traits),
      semantic: semanticSimilarity(selectedSet, traits),
    };
  }).sort((a, b) => (b.exact + b.semantic * 0.35) - (a.exact + a.semantic * 0.35)).slice(0, 20);
  el("identifyResult").innerHTML = `
    <h2>Candidate taxa</h2>
    <table class="trait-table">
      <thead><tr><th>Taxon</th><th>Exact trait overlap</th><th>Semantic similarity</th><th>Images</th></tr></thead>
      <tbody>${ranked.map((r) => `<tr><td>${escapeHtml(r.taxon)}</td><td>${(r.exact * 100).toFixed(1)}%</td><td>${(r.semantic * 100).toFixed(1)}%</td><td><a href="${inatUrl(r.taxon)}" target="_blank" rel="noopener">iNaturalist</a></td></tr>`).join("")}</tbody>
    </table>
  `;
}

function jaccard(a, b) {
  const union = new Set([...a, ...b]);
  if (!union.size) return 0;
  let hit = 0;
  for (const item of a) if (b.has(item)) hit += 1;
  return hit / union.size;
}

function semanticSimilarity(a, b) {
  const groupsA = new Set([...a].map((id) => {
    const t = traitById(id);
    return `${t?.organ_group}|${t?.quality_group}`;
  }));
  const groupsB = new Set([...b].map((id) => {
    const t = traitById(id);
    return `${t?.organ_group}|${t?.quality_group}`;
  }));
  return jaccard(groupsA, groupsB);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[ch]));
}

load().catch((error) => {
  document.body.innerHTML = `<main class="detail wide"><h1>Could not load FLOPO data</h1><p>${escapeHtml(error.message)}</p></main>`;
});
