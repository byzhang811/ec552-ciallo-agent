const app = document.getElementById("app");

const state = {
  bootstrap: null,
  mode: "pure_nl",
  currentTab: "diff",
  selectedCollection: null,
  requestText: "",
  baseVersion: "Eco1C1G1T1",
  paperFile: null,
  paperFileLabel: "",
  brief: null,
  customDraftText: "",
  forceHeuristic: false,
  runCello: false,
  baseUcf: null,
  generatedUcf: null,
  diff: null,
  response: null,
  busy: false,
  editorText: "",
  editorError: "",
};

const QUICK_TESTS = [
  {
    id: "official-baseline",
    label: "Official baseline",
    mode: "official_quick_design",
    prompt: "Quickly compile a structured brief into an official-library Cello design.",
    note: "Best first test. No paper needed.",
  },
  {
    id: "paper-assisted",
    label: "Paper-assisted draft",
    mode: "paper_assisted",
    prompt: "Use the paper to help design an E. coli YFP logic circuit and reuse any supported sensors, proteins, promoters, and gates you can identify.",
    note: "Attach a paper or PDF before generating.",
  },
  {
    id: "custom-components",
    label: "Custom component draft",
    mode: "custom_components",
    prompt: "Author a custom UCF fragment for a new blue-light sensor and a fluorescent reporter.",
    note: "Advanced only. Paste a custom JSON fragment before generating.",
  },
];

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

function truncate(text, maxLength = 220) {
  const value = String(text || "").trim();
  if (!value) return "";
  if (value.length <= maxLength) return value;
  return `${value.slice(0, maxLength - 1).trimEnd()}…`;
}

function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function modeTitle(mode) {
  return state.bootstrap?.scenario_presets?.find((preset) => preset.id === mode)?.title || mode;
}

function fileLink(path) {
  if (!path) return "";
  return `/api/file?path=${encodeURIComponent(path)}`;
}

function stableValue(value) {
  if (Array.isArray(value)) {
    return value.map(stableValue);
  }
  if (value && typeof value === "object") {
    return Object.keys(value)
      .sort()
      .reduce((acc, key) => {
        acc[key] = stableValue(value[key]);
        return acc;
      }, {});
  }
  return value;
}

function fingerprint(value) {
  return JSON.stringify(stableValue(value));
}

function diffAny(before, after, path = "$") {
  if (Array.isArray(before) && Array.isArray(after)) {
    return diffList(before, after, path);
  }
  if (
    before &&
    after &&
    typeof before === "object" &&
    typeof after === "object" &&
    !Array.isArray(before) &&
    !Array.isArray(after)
  ) {
    return diffDict(before, after, path);
  }
  if (before === after) return [];
  return [
    {
      path: path || "$",
      before,
      after,
      kind: "updated",
    },
  ];
}

function diffDict(before, after, path) {
  const keys = Array.from(new Set([...Object.keys(before), ...Object.keys(after)])).sort();
  const changes = [];
  for (const key of keys) {
    const child = path ? `${path}.${key}` : key;
    if (!(key in before)) {
      changes.push({ path: child, before: null, after: after[key], kind: "added" });
    } else if (!(key in after)) {
      changes.push({ path: child, before: before[key], after: null, kind: "removed" });
    } else {
      changes.push(...diffAny(before[key], after[key], child));
    }
  }
  return changes;
}

function diffList(before, after, path) {
  if (JSON.stringify(before) === JSON.stringify(after)) return [];
  const shared = Math.min(before.length, after.length);
  const changes = [];
  for (let i = 0; i < shared; i += 1) {
    changes.push(...diffAny(before[i], after[i], `${path}[${i}]`));
  }
  for (let i = shared; i < before.length; i += 1) {
    changes.push({
      path: `${path}[${i}]`,
      before: before[i],
      after: null,
      kind: "removed",
    });
  }
  for (let i = shared; i < after.length; i += 1) {
    changes.push({
      path: `${path}[${i}]`,
      before: null,
      after: after[i],
      kind: "added",
    });
  }
  return changes;
}

function groupByCollection(items) {
  const grouped = new Map();
  for (const item of items || []) {
    if (!item || typeof item !== "object") continue;
    const collection = item.collection || "__unknown__";
    if (!grouped.has(collection)) grouped.set(collection, []);
    grouped.get(collection).push(item);
  }
  return grouped;
}

function namedItems(items) {
  const result = new Map();
  for (const item of items || []) {
    if (item && item.name) result.set(String(item.name), item);
  }
  return result;
}

function unnamedFingerprints(items) {
  const counts = new Map();
  for (const item of items || []) {
    if (item && item.name) continue;
    const key = fingerprint(item);
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  return counts;
}

function collectionChange(collection, baseItems, generatedItems) {
  if (
    (collection === "header" || collection === "logic_constraints") &&
    baseItems.length === 1 &&
    generatedItems.length === 1
  ) {
    const changes = diffAny(baseItems[0], generatedItems[0], collection);
    if (!changes.length) return null;
    return {
      collection,
      base_count: baseItems.length,
      generated_count: generatedItems.length,
      added: 0,
      removed: 0,
      modified: 1,
      items: [
        {
          collection,
          key: collection,
          change_type: "modified",
          before: baseItems[0],
          after: generatedItems[0],
          changes,
        },
      ],
    };
  }

  const beforeNamed = namedItems(baseItems);
  const afterNamed = namedItems(generatedItems);
  const itemChanges = [];

  for (const name of Array.from(new Set([...beforeNamed.keys(), ...afterNamed.keys()])).sort()) {
    const beforeItem = beforeNamed.get(name);
    const afterItem = afterNamed.get(name);
    if (!beforeItem) {
      itemChanges.push({
        collection,
        key: name,
        change_type: "added",
        before: null,
        after: afterItem,
        changes: [],
      });
      continue;
    }
    if (!afterItem) {
      itemChanges.push({
        collection,
        key: name,
        change_type: "removed",
        before: beforeItem,
        after: null,
        changes: [],
      });
      continue;
    }
    const changes = diffAny(beforeItem, afterItem, collection);
    if (changes.length) {
      itemChanges.push({
        collection,
        key: name,
        change_type: "modified",
        before: beforeItem,
        after: afterItem,
        changes,
      });
    }
  }

  const beforeCounts = unnamedFingerprints(baseItems);
  const afterCounts = unnamedFingerprints(generatedItems);
  for (const key of Array.from(new Set([...beforeCounts.keys(), ...afterCounts.keys()])).sort()) {
    const beforeCount = beforeCounts.get(key) || 0;
    const afterCount = afterCounts.get(key) || 0;
    if (beforeCount === afterCount) continue;
    const payload = JSON.parse(key);
    if (beforeCount > afterCount) {
      for (let i = 0; i < beforeCount - afterCount; i += 1) {
        itemChanges.push({
          collection,
          key: `${collection}[]`,
          change_type: "removed",
          before: payload,
          after: null,
          changes: [],
        });
      }
    } else {
      for (let i = 0; i < afterCount - beforeCount; i += 1) {
        itemChanges.push({
          collection,
          key: `${collection}[]`,
          change_type: "added",
          before: null,
          after: payload,
          changes: [],
        });
      }
    }
  }

  if (!itemChanges.length) return null;
  return {
    collection,
    base_count: baseItems.length,
    generated_count: generatedItems.length,
    added: itemChanges.filter((change) => change.change_type === "added").length,
    removed: itemChanges.filter((change) => change.change_type === "removed").length,
    modified: itemChanges.filter((change) => change.change_type === "modified").length,
    items: itemChanges,
  };
}

function buildDiff(baseItems, generatedItems) {
  const baseGrouped = groupByCollection(baseItems);
  const generatedGrouped = groupByCollection(generatedItems);
  const collections = [];
  const changes = [];
  let added = 0;
  let removed = 0;
  let modified = 0;

  for (const collection of Array.from(new Set([...baseGrouped.keys(), ...generatedGrouped.keys()])).sort()) {
    const change = collectionChange(
      collection,
      baseGrouped.get(collection) || [],
      generatedGrouped.get(collection) || []
    );
    if (!change) continue;
    collections.push(change);
    changes.push(...change.items);
    added += change.added;
    removed += change.removed;
    modified += change.modified;
  }

  return {
    summary: {
      base_item_count: baseItems.length,
      generated_item_count: generatedItems.length,
      collection_count: collections.length,
      added,
      removed,
      modified,
    },
    collections,
    changes,
  };
}

function chips(items) {
  return items
    .map((item) => `<span class="chip">${escapeHtml(item)}</span>`)
    .join("");
}

function modeIcon(mode) {
  switch (mode) {
    case "pure_nl":
      return "✦";
    case "paper_assisted":
      return "▣";
    case "custom_components":
      return "⟡";
    case "official_quick_design":
      return "⌘";
    default:
      return "•";
  }
}

function setMode(mode) {
  state.mode = mode;
  state.currentTab = state.currentTab || "diff";
  renderAll();
}

function setTab(tab) {
  state.currentTab = tab;
  renderAll();
}

function setSelectedCollection(name) {
  state.selectedCollection = name;
  renderAll();
}

function buildBriefFromState() {
  const inputRows = [
    {
      logical_name: document.getElementById("brief-input-1-name")?.value || "arabinose",
      description: document.getElementById("brief-input-1-desc")?.value || "Arabinose input signal",
      signal_name: document.getElementById("brief-input-1-signal")?.value || "arabinose",
      preferred_sensor: document.getElementById("brief-input-1-sensor")?.value || "AraC_sensor",
    },
    {
      logical_name: document.getElementById("brief-input-2-name")?.value || "iptg",
      description: document.getElementById("brief-input-2-desc")?.value || "IPTG input signal",
      signal_name: document.getElementById("brief-input-2-signal")?.value || "IPTG",
      preferred_sensor: document.getElementById("brief-input-2-sensor")?.value || "LacI_sensor",
    },
  ];

  return {
    design_name: document.getElementById("brief-design-name")?.value || "and_biosensor",
    summary:
      document.getElementById("brief-summary")?.value ||
      "An AND biosensor compiled from a structured design brief.",
    target_chassis: document.getElementById("brief-chassis")?.value || "Eco",
    logic_operator: document.getElementById("brief-logic")?.value || "AND",
    input_signals: inputRows,
    output_signal: {
      logical_name: document.getElementById("brief-output-name")?.value || "yfp",
      description: document.getElementById("brief-output-desc")?.value || "Fluorescent YFP output",
      signal_name: document.getElementById("brief-output-signal")?.value || "YFP",
      preferred_device: document.getElementById("brief-output-device")?.value || "YFP_reporter",
    },
    constraints: [
      document.getElementById("brief-constraint-1")?.value || "Prefer the official Eco library.",
      document.getElementById("brief-constraint-2")?.value || "Keep the design compact and readable.",
    ].filter(Boolean),
    notes: [],
  };
}

function buildShell() {
  return `
    <div class="background-glow"></div>
    <div class="layout">
      <aside class="sidebar">
        <section class="panel">
          <div class="panel-inner">
            <div class="eyebrow">Scenario Wizard</div>
            <div id="mode-cards" class="wizard-cards"></div>
          </div>
        </section>

        <section class="panel">
          <div class="card-header">
            <h3>Official Library</h3>
            <div class="meta" id="library-meta">Local Cello records</div>
          </div>
          <div class="panel-inner">
            <div id="library-summary" class="status-list"></div>
          </div>
        </section>

        <section class="panel">
          <div class="card-header">
            <h3>Run Flow</h3>
            <div class="meta" id="status-meta">Ready</div>
          </div>
          <div class="panel-inner">
            <div id="pipeline-status" class="status-list"></div>
          </div>
        </section>
      </aside>

      <main class="content">
        <section class="hero">
          <div class="eyebrow">Ciallo Studio</div>
          <h1 id="hero-title">Generate a design bundle</h1>
          <p id="hero-subtitle">
            Type a request, pick an example if you want one, and press Generate Design Bundle. The workspace shows
            the request, the selected official library, and the generated design files.
          </p>
          <div id="hero-stats" class="hero-stats"></div>
        </section>

        <section class="quick-start">
          <div class="start-card start-card-wide">
            <div class="eyebrow">Quick Start</div>
            <h2>Start with a simple test case</h2>
            <p>
              Pick a preset if you want, or just type a request and click <strong>Generate Design Bundle</strong>.
              The studio will use the official library first and will stop early if it needs an extension.
            </p>
            <div id="quick-test-buttons" class="quick-test-buttons"></div>
          </div>
        </section>

        <section class="grid-two">
          <div class="card">
            <div class="card-header">
              <h2>Source Studio</h2>
              <div class="meta">Request, paper, and structured brief inputs</div>
            </div>
            <div class="card-body">
              <div class="grid-two">
                <div class="field">
                  <label for="base-version">Base library</label>
                  <select id="base-version"></select>
                </div>
              <div class="field">
                <label>Execution options</label>
                <div class="pill-row">
                  <label class="pill"><input id="force-heuristic" type="checkbox" /> Heuristic</label>
                  <label class="pill"><input id="run-cello" type="checkbox" /> Run Cello</label>
                </div>
              </div>
              </div>

              <div class="field">
                <label for="request-text">Natural language request</label>
                <textarea id="request-text" placeholder="Describe the design in natural language."></textarea>
              </div>

              <div id="source-upload" class="uploader">
                <div>
                  <strong>Paper / source file</strong>
                <div class="hint">
                    Optional in the simplest mode, required for paper-assisted mode. Upload PDF, TXT, MD,
                    or JSON.
                  </div>
              </div>
                <input id="paper-file" type="file" accept=".pdf,.txt,.md,.json" />
                <div class="tiny" id="paper-file-label">No file selected</div>
              </div>

              <div id="mode-specific"></div>

              <div class="action-row">
                <button id="run-button" class="btn btn-primary">Generate Design Bundle</button>
                <button id="reset-button" class="btn btn-secondary">Reset to Example</button>
                <button id="load-template-button" class="btn btn-ghost">Load Mode Template</button>
              </div>
              <div class="tiny" id="request-help"></div>
              <div class="notice" id="extension-hint" style="display:none;"></div>
            </div>
          </div>

          <div class="card">
            <div class="card-header">
              <h2>Run Summary</h2>
              <div class="meta">Selected sensors, validation, warnings</div>
            </div>
          <div class="card-body">
            <div id="summary-chips" class="chips"></div>
            <div style="height: 14px"></div>
            <div id="run-summary" class="status-list"></div>
            <div style="height: 14px"></div>
            <div class="artifact-grid" id="artifact-links"></div>
          </div>
        </div>
      </section>

        <details class="advanced-panel">
          <summary>
            <div>
              <strong>Advanced</strong>
              <span>Diff, workspace, and manual edits</span>
            </div>
            <div class="advanced-hint">Optional</div>
          </summary>
          <section class="grid-two advanced-grid">
            <div class="card">
              <div class="card-header">
                <h2>Library Diff</h2>
                <div class="meta" id="diff-meta">Base vs generated</div>
              </div>
              <div class="card-body">
                <div id="diff-summary-chips" class="chips"></div>
                <div style="height: 14px"></div>
                <div id="collection-table" class="collection-table"></div>
              </div>
            </div>

            <div class="card">
              <div class="card-header">
                <h2>Workspace</h2>
                <div class="tabs" id="tabs"></div>
              </div>
              <div class="card-body">
                <div id="tab-pane"></div>
              </div>
            </div>
          </section>
        </details>

        <div class="footer">
          Built for Cello v2 workflows. Everything runs locally against your workspace and can be exported as JSON or opened from the browser.
        </div>
      </main>
    </div>
  `;
}

function renderModeCards() {
  const root = document.getElementById("mode-cards");
  root.innerHTML = state.bootstrap.scenario_presets
    .map(
      (preset) => `
        <button class="mode-card ${preset.id === state.mode ? "active" : ""}" data-mode="${preset.id}">
          <div class="mode-top">
            <div class="badge">${preset.badge}</div>
            <div class="tiny">${modeIcon(preset.id)}</div>
          </div>
          <h3>${preset.title}</h3>
          <p>${preset.description}</p>
        </button>
      `
    )
    .join("");
}

function renderLibrarySummary() {
  const root = document.getElementById("library-summary");
  root.innerHTML = state.bootstrap.library_records
    .map(
      (record) => `
        <div class="status-item ${record.version === state.baseVersion ? "active" : ""}">
          <div class="status-dot"></div>
          <div>
            <h4>${escapeHtml(record.version)} · ${escapeHtml(record.chassis)}</h4>
            <p>${escapeHtml(record.summary_line)}</p>
          </div>
        </div>
      `
    )
    .join("");

  document.getElementById("library-meta").textContent = `${state.bootstrap.library_records.length} official records`;
}

function renderHero() {
  const stats = [
    { label: "Scenario", value: modeTitle(state.mode) },
    { label: "Base library", value: state.baseVersion },
    {
      label: "Generated items",
      value: state.diff?.summary ? String(state.diff.summary.generated_item_count) : "—",
    },
    {
      label: "Diff changes",
      value: state.diff?.summary ? `${state.diff.summary.added + state.diff.summary.removed + state.diff.summary.modified}` : "—",
    },
  ];
  document.getElementById("hero-stats").innerHTML = stats
    .map(
      (stat) => `
        <div class="stat">
          <div class="label">${escapeHtml(stat.label)}</div>
          <div class="value">${escapeHtml(stat.value)}</div>
        </div>
      `
    )
    .join("");
}

function renderQuickStart() {
  const buttonsRoot = document.getElementById("quick-test-buttons");
  if (buttonsRoot) {
    buttonsRoot.innerHTML = QUICK_TESTS.map(
      (item) => `
        <button class="quick-test ${item.mode === state.mode ? "active" : ""}" data-example="${escapeHtml(item.id)}">
          <div class="quick-test-top">
            <strong>${escapeHtml(item.label)}</strong>
            <span>${escapeHtml(modeIcon(item.mode))}</span>
          </div>
          <p>${escapeHtml(item.note)}</p>
        </button>
      `
    ).join("");
  }

  const summary = state.response?.result_summary || {};
  const diffSummary = state.diff?.summary || null;
  const helpRoot = document.getElementById("request-help");
  if (helpRoot) {
    const preset = state.bootstrap?.scenario_presets?.find((item) => item.id === state.mode) || null;
    helpRoot.textContent = preset
      ? `Current mode: ${preset.title}. Write the request in plain English, or press a test button above to load an example.`
      : "Write the request in plain English, or press a test button above to load an example.";
  }

  const proof = document.getElementById("story-proof");
  const delta = document.getElementById("story-delta");
  if (proof) {
    const rows = [
      { label: "Selected sensors", value: summary.selected_sensors?.join(", ") || "No sensors reported yet" },
      { label: "Selected output", value: summary.selected_output_device || "No output reported yet" },
      { label: "Validation", value: (summary.validation_issues || []).length ? summary.validation_issues.join(" · ") : "Schema checks passed" },
      { label: "Warnings", value: (summary.warnings || []).length ? summary.warnings.join(" · ") : "No warnings reported" },
    ];
    proof.innerHTML = rows
      .map(
        (row) => `
          <div class="info-row">
            <div class="info-label">${escapeHtml(row.label)}</div>
            <div class="info-value">${escapeHtml(row.value)}</div>
          </div>
        `
      )
      .join("");
  }
  if (delta) {
    if (!diffSummary) {
      delta.innerHTML = `<div class="story-empty">Run a test to see the base library versus generated library diff.</div>`;
      return;
    }
    delta.innerHTML = `
      <div class="delta-grid">
        <div class="delta-metric">
          <span>Added</span>
          <strong>${diffSummary.added}</strong>
        </div>
        <div class="delta-metric">
          <span>Removed</span>
          <strong>${diffSummary.removed}</strong>
        </div>
        <div class="delta-metric">
          <span>Modified</span>
          <strong>${diffSummary.modified}</strong>
        </div>
      </div>
      <div class="delta-list">
        ${(state.diff.collections || []).slice(0, 3).map(
          (item) => `
            <div class="delta-item">
              <strong>${escapeHtml(item.collection)}</strong>
              <span>${escapeHtml(`${item.added} + ${item.removed} − ${item.modified}`)}</span>
            </div>
          `
        ).join("")}
      </div>
    `;
  }
}

function renderModeSpecific() {
  const root = document.getElementById("mode-specific");
  const help = document.getElementById("request-help");
  const sourceUpload = document.getElementById("source-upload");
  sourceUpload.style.display = "grid";

  if (state.mode === "official_quick_design") {
    const brief = state.brief || deepClone(state.bootstrap.default_brief);
    help.textContent =
      "Quick design mode uses a structured brief form. The fields below are compiled directly into a design bundle.";
    root.innerHTML = `
      <div class="panel" style="margin-top: 14px;">
        <div class="panel-inner">
          <div class="field">
            <label for="brief-design-name">Design name</label>
            <input id="brief-design-name" type="text" value="${escapeHtml(brief.design_name)}" />
          </div>
          <div class="field">
            <label for="brief-summary">Summary</label>
            <textarea id="brief-summary" style="min-height: 100px;">${escapeHtml(brief.summary)}</textarea>
          </div>
          <div class="grid-two" style="margin-top: 10px;">
            <div class="field">
              <label for="brief-chassis">Target chassis</label>
                <select id="brief-chassis">
                <option value="Eco"${brief.target_chassis === "Eco" ? " selected" : ""}>Eco</option>
                <option value="SC"${brief.target_chassis === "SC" ? " selected" : ""}>SC</option>
                <option value="Bth"${brief.target_chassis === "Bth" ? " selected" : ""}>Bth</option>
              </select>
            </div>
            <div class="field">
              <label for="brief-logic">Logic operator</label>
              <select id="brief-logic">
                <option value="AND"${brief.logic_operator === "AND" ? " selected" : ""}>AND</option>
                <option value="OR"${brief.logic_operator === "OR" ? " selected" : ""}>OR</option>
                <option value="NOR"${brief.logic_operator === "NOR" ? " selected" : ""}>NOR</option>
                <option value="NAND"${brief.logic_operator === "NAND" ? " selected" : ""}>NAND</option>
                <option value="NOT"${brief.logic_operator === "NOT" ? " selected" : ""}>NOT</option>
              </select>
            </div>
          </div>
          <div class="grid-two">
            <div class="field">
              <label>Input 1</label>
              <input id="brief-input-1-name" type="text" value="${escapeHtml(brief.input_signals[0].logical_name)}" placeholder="logical name" />
              <input id="brief-input-1-desc" type="text" value="${escapeHtml(brief.input_signals[0].description)}" placeholder="description" />
              <input id="brief-input-1-signal" type="text" value="${escapeHtml(brief.input_signals[0].signal_name)}" placeholder="signal name" />
              <input id="brief-input-1-sensor" type="text" value="${escapeHtml(brief.input_signals[0].preferred_sensor)}" placeholder="preferred sensor" />
            </div>
            <div class="field">
              <label>Input 2</label>
              <input id="brief-input-2-name" type="text" value="${escapeHtml(brief.input_signals[1].logical_name)}" placeholder="logical name" />
              <input id="brief-input-2-desc" type="text" value="${escapeHtml(brief.input_signals[1].description)}" placeholder="description" />
              <input id="brief-input-2-signal" type="text" value="${escapeHtml(brief.input_signals[1].signal_name)}" placeholder="signal name" />
              <input id="brief-input-2-sensor" type="text" value="${escapeHtml(brief.input_signals[1].preferred_sensor)}" placeholder="preferred sensor" />
            </div>
          </div>
          <div class="grid-two">
            <div class="field">
              <label for="brief-output-name">Output name</label>
              <input id="brief-output-name" type="text" value="${escapeHtml(brief.output_signal.logical_name)}" />
            </div>
            <div class="field">
              <label for="brief-output-device">Preferred output device</label>
              <input id="brief-output-device" type="text" value="${escapeHtml(brief.output_signal.preferred_device)}" />
            </div>
          </div>
          <div class="grid-two">
            <div class="field">
              <label for="brief-output-desc">Output description</label>
              <input id="brief-output-desc" type="text" value="${escapeHtml(brief.output_signal.description)}" />
            </div>
            <div class="field">
              <label for="brief-output-signal">Output signal name</label>
              <input id="brief-output-signal" type="text" value="${escapeHtml(brief.output_signal.signal_name)}" />
            </div>
          </div>
          <div class="field">
            <label for="brief-constraint-1">Constraint 1</label>
            <input id="brief-constraint-1" type="text" value="${escapeHtml(brief.constraints[0])}" />
          </div>
          <div class="field">
            <label for="brief-constraint-2">Constraint 2</label>
            <input id="brief-constraint-2" type="text" value="${escapeHtml(brief.constraints[1])}" />
          </div>
        </div>
      </div>
    `;
  } else if (state.mode === "custom_components") {
    help.textContent =
      "Custom component mode accepts a draft JSON fragment. Use this only when the official library is not enough.";
    if (!state.customDraftText) {
      state.customDraftText = pretty(state.bootstrap.default_custom_draft);
    }
    root.innerHTML = `
      <div class="panel" style="margin-top: 14px;">
        <div class="panel-inner">
          <div class="field">
            <label for="custom-draft-text">Custom fragment JSON</label>
            <textarea id="custom-draft-text" style="min-height: 320px;">${escapeHtml(state.customDraftText)}</textarea>
          </div>
          <div class="tiny">Tip: paste a draft that matches the PaperUCFDraft schema. The studio will merge it only in the advanced path.</div>
        </div>
      </div>
    `;
  } else {
    help.textContent =
      state.mode === "paper_assisted"
        ? "Paper-assisted mode uses both your request and the uploaded source file."
        : "Pure natural-language mode is the fastest way to generate a first draft.";
    root.innerHTML = "";
  }
}

function renderSummary() {
  const chipsRoot = document.getElementById("summary-chips");
  const summary = state.response?.result_summary || {};
  const libraryStatus = state.response?.library_status || null;
  const chipsList = [];
  if (summary.planner) chipsList.push({ text: `Planner: ${summary.planner}`, kind: "success" });
  if (summary.selected_output_device) chipsList.push({ text: `Output: ${summary.selected_output_device}`, kind: "success" });
  if (libraryStatus) {
    chipsList.push({
      text: libraryStatus.sufficient ? "Library: sufficient" : "Library: needs extension",
      kind: libraryStatus.sufficient ? "success" : "warning",
    });
  }
  const validationIssues = summary.validation_issues || [];
  if (validationIssues.length) {
    chipsList.push({ text: `Validation: ${validationIssues.length} issue(s)`, kind: "danger" });
  } else if (state.response) {
    chipsList.push({ text: "Validation: clean", kind: "success" });
  }
  const warnings = summary.warnings || [];
  if (warnings.length) chipsList.push({ text: `Warnings: ${warnings.length}`, kind: "warning" });
  chipsRoot.innerHTML = chipsList
    .map((chip) => `<span class="chip ${chip.kind}">${escapeHtml(chip.text)}</span>`)
    .join("");

  const runSummary = document.getElementById("run-summary");
  runSummary.innerHTML = state.response
    ? `
      <div class="status-item done">
        <div class="status-dot"></div>
        <div>
          <h4>Run complete</h4>
          <p>Results are ready.</p>
        </div>
      </div>
      <div class="status-item ${validationIssues.length ? "error" : "done"}">
        <div class="status-dot"></div>
        <div>
          <h4>Validation</h4>
          <p>${validationIssues.length ? escapeHtml(validationIssues.join(" · ")) : "Schema checks passed."}</p>
        </div>
      </div>
      <div class="status-item">
        <div class="status-dot"></div>
        <div>
          <h4>Selected sensors</h4>
          <p>${escapeHtml((summary.selected_sensors || []).join(", ") || "No selected sensors reported.")}</p>
        </div>
      </div>
      <div class="status-item ${libraryStatus && !libraryStatus.sufficient ? "error" : "done"}">
        <div class="status-dot"></div>
        <div>
          <h4>Official library</h4>
          <p>${escapeHtml(
            libraryStatus
              ? libraryStatus.sufficient
                ? "The selected official library is enough for this request."
                : libraryStatus.reasons?.[0] || "This request needs a library extension."
              : "Library status not reported."
          )}</p>
        </div>
      </div>
      <div class="status-item ${summary.execution_error ? "error" : "done"}">
        <div class="status-dot"></div>
        <div>
          <h4>Cello</h4>
          <p>${escapeHtml(
            summary.execution_error
              ? summary.execution_error
              : summary.cello_ran
                ? "Cello execution was started."
                : "Cello was skipped."
          )}</p>
        </div>
      </div>
    `
    : `
      <div class="status-item active">
        <div class="status-dot"></div>
        <div>
          <h4>Ready to generate</h4>
          <p>Choose a mode, fill the form, and press Generate Design Bundle.</p>
        </div>
      </div>
    `;

  const artifacts = document.getElementById("artifact-links");
  const artifactEntries = [];
  if (state.response?.design_artifacts?.spec) {
    artifactEntries.push({
      title: "Design spec",
      path: state.response.design_artifacts.spec,
    });
  }
  if (state.response?.design_artifacts?.verilog) {
    artifactEntries.push({
      title: "Verilog",
      path: state.response.design_artifacts.verilog,
    });
  }
  if (state.response?.design_artifacts?.input) {
    artifactEntries.push({
      title: "Input JSON",
      path: state.response.design_artifacts.input,
    });
  }
  if (state.response?.design_artifacts?.output) {
    artifactEntries.push({
      title: "Output JSON",
      path: state.response.design_artifacts.output,
    });
  }
  if (state.response?.design_artifacts?.summary) {
    artifactEntries.push({
      title: "Summary",
      path: state.response.design_artifacts.summary,
    });
  }
  if (state.response?.design_artifacts?.manifest) {
    artifactEntries.push({
      title: "Manifest",
      path: state.response.design_artifacts.manifest,
    });
  }
  if (state.response?.design_artifacts?.cello_output) {
    artifactEntries.push({
      title: "Cello output",
      path: state.response.design_artifacts.cello_output,
    });
  }
  artifacts.innerHTML = artifactEntries
    .map(
      (item) => `
        <a class="artifact-link" href="${fileLink(item.path)}" target="_blank" rel="noreferrer" title="${escapeHtml(item.path)}">
          <div>
            <strong>${escapeHtml(item.title)}</strong>
          </div>
          <span class="artifact-open">Open</span>
        </a>
      `
    )
    .join("");

  const extensionHint = document.getElementById("extension-hint");
  if (extensionHint) {
    const warnings = summary.warnings || [];
    const needsExtension =
      warnings.some((item) =>
        /not present in the chosen library|preferred output device was not available|custom UCF requests/i.test(item)
      ) || (summary.validation_issues || []).length > 0;
    extensionHint.style.display = needsExtension ? "block" : "none";
    extensionHint.textContent = needsExtension
      ? "This request likely needs a library extension. Open Advanced only if you want to inspect the diff or workspace details."
      : "The selected official library is enough for this request.";
  }
}

function renderPipelineStatus() {
  const root = document.getElementById("pipeline-status");
  const steps = [
    {
      title: "Input",
      status: state.response ? "done" : "active",
      body:
        state.mode === "paper_assisted"
          ? "Request + paper upload"
          : state.mode === "custom_components"
            ? "Request + fragment JSON"
            : state.mode === "official_quick_design"
              ? "Structured brief"
              : "Natural language request",
    },
    {
      title: "Library setup",
      status: state.response ? "done" : "active",
      body: "Load the selected library and prepare the compile inputs.",
    },
    {
      title: "Bundle assembly",
      status: state.response ? "done" : "idle",
      body: "Verilog, input/output, and options are compiled into a design bundle.",
    },
    {
      title: "Cello execution",
      status: state.response?.result_summary?.validation_issues?.length ? "error" : state.response ? "done" : "idle",
      body: state.response?.result_summary?.validation_issues?.length
        ? "Validation issues need a quick look."
        : "Optional Docker execution can be triggered from the CLI.",
    },
  ];

  root.innerHTML = steps
    .map(
      (step) => `
        <div class="status-item ${step.status}">
          <div class="status-dot"></div>
          <div>
            <h4>${escapeHtml(step.title)}</h4>
            <p>${escapeHtml(step.body)}</p>
          </div>
        </div>
      `
    )
    .join("");
  document.getElementById("status-meta").textContent = state.busy ? "Running..." : "Ready";
}

function renderDiffSummary() {
  const root = document.getElementById("diff-summary-chips");
  if (!state.diff) {
    root.innerHTML = `
      <span class="chip">No diff yet</span>
      <span class="chip">Load or generate a design to compare</span>
    `;
    return;
  }
  const summary = state.diff.summary;
  root.innerHTML = `
    <span class="chip success">Base: ${summary.base_item_count}</span>
    <span class="chip success">Generated: ${summary.generated_item_count}</span>
    <span class="chip">${summary.collection_count} collections</span>
    <span class="chip warning">Added ${summary.added}</span>
    <span class="chip warning">Removed ${summary.removed}</span>
    <span class="chip success">Modified ${summary.modified}</span>
  `;

  document.getElementById("diff-meta").textContent = `Changes: ${summary.added + summary.removed + summary.modified}`;
}

function renderCollectionTable() {
  const root = document.getElementById("collection-table");
  if (!state.diff) {
    root.innerHTML = `<div class="tiny">No design loaded yet. Generate a bundle or upload two JSON files to begin comparing.</div>`;
    return;
  }
  const rows = state.diff.collections || [];
  root.innerHTML = rows
    .map(
      (row) => `
        <button class="collection-row ${state.selectedCollection === row.collection ? "active" : ""}" data-collection="${escapeHtml(row.collection)}">
          <div>
            <strong>${escapeHtml(row.collection)}</strong>
            <small>${escapeHtml(row.items.length)} changed item(s)</small>
          </div>
          <div><strong>${row.base_count}</strong><small>base</small></div>
          <div><strong>${row.generated_count}</strong><small>generated</small></div>
          <div><strong>${row.modified}</strong><small>modified</small></div>
        </button>
      `
    )
    .join("");
}

function renderTabs() {
  const root = document.getElementById("tabs");
  const tabs = [
    ["base", "Base"],
    ["generated", "Generated"],
    ["diff", "Diff"],
    ["editor", "Editor"],
  ];
  root.innerHTML = tabs
    .map(
      ([key, label]) => `
        <button class="tab ${state.currentTab === key ? "active" : ""}" data-tab="${key}">${label}</button>
      `
    )
    .join("");
}

function renderTabPane() {
  const root = document.getElementById("tab-pane");
  if (state.currentTab === "base") {
    root.innerHTML = `<pre class="code-view">${escapeHtml(pretty(state.baseUcf || {}))}</pre>`;
    return;
  }
  if (state.currentTab === "generated") {
    root.innerHTML = `<pre class="code-view">${escapeHtml(pretty(state.generatedUcf || {}))}</pre>`;
    return;
  }
  if (state.currentTab === "editor") {
    root.innerHTML = `
      <div class="field">
        <label for="generated-editor">Edit generated UCF JSON</label>
        <textarea id="generated-editor" class="editor">${escapeHtml(state.editorText || pretty(state.generatedUcf || {}))}</textarea>
      </div>
      <div class="action-row">
        <button id="apply-editor" class="btn btn-primary">Apply Editor Diff</button>
        <button id="download-generated" class="btn btn-secondary">Download Generated JSON</button>
        <button id="download-diff" class="btn btn-ghost">Download Diff JSON</button>
      </div>
      <div class="tiny">${escapeHtml(state.editorError || "Edit the JSON and apply it to recompute the live diff.")}</div>
    `;
    return;
  }

  const diff = state.diff;
  if (!diff) {
    root.innerHTML = `
      <div class="story-empty">
        No diff loaded yet. Generate a design, or switch to another tab after a run to inspect the base and generated JSON.
      </div>
    `;
    return;
  }
  const filteredCollections = state.selectedCollection
    ? diff.collections.filter((item) => item.collection === state.selectedCollection)
    : diff.collections;
  root.innerHTML = `
    <div class="diff-list">
      ${
        filteredCollections.length
          ? filteredCollections
              .map(
                (collection) => `
                  <div class="diff-card">
                    <div class="top">
                      <div class="title">${escapeHtml(collection.collection)}</div>
                      <div class="meta">${collection.added} added · ${collection.removed} removed · ${collection.modified} modified</div>
                    </div>
                    <pre>${escapeHtml(
                      collection.items
                        .map((item) => {
                          const lines = [
                            `[${item.change_type.toUpperCase()}] ${item.collection}:${item.key}`,
                          ];
                          if (item.changes && item.changes.length) {
                            lines.push(...item.changes.map((change) => `  ${change.kind}: ${change.path}`));
                          }
                          return lines.join("\n");
                        })
                        .join("\n\n")
                    )}</pre>
                  </div>
                `
              )
              .join("")
          : `<div class="tiny">Select a collection from the overview to inspect its item-level changes.</div>`
      }
    </div>
  `;
}

function syncInputsFromState() {
  const request = document.getElementById("request-text");
  if (request) request.value = state.requestText;
  const baseVersion = document.getElementById("base-version");
  if (baseVersion) {
    baseVersion.innerHTML = state.bootstrap.library_records
      .map(
        (record) =>
          `<option value="${escapeHtml(record.version)}"${record.version === state.baseVersion ? " selected" : ""}>${escapeHtml(record.version)} · ${escapeHtml(record.chassis)}</option>`
      )
      .join("");
    baseVersion.value = state.baseVersion;
  }
  const forceHeuristic = document.getElementById("force-heuristic");
  if (forceHeuristic) forceHeuristic.checked = Boolean(state.forceHeuristic);
  const runCello = document.getElementById("run-cello");
  if (runCello) runCello.checked = Boolean(state.runCello);
  const paperFileLabel = document.getElementById("paper-file-label");
  if (paperFileLabel) {
    paperFileLabel.textContent = state.paperFileLabel || "No file selected";
  }
  const customDraft = document.getElementById("custom-draft-text");
  if (customDraft && state.customDraftText) customDraft.value = state.customDraftText;
}

function renderAll() {
  renderModeCards();
  renderLibrarySummary();
  renderHero();
  renderQuickStart();
  renderModeSpecific();
  renderSummary();
  renderPipelineStatus();
  renderDiffSummary();
  renderCollectionTable();
  renderTabs();
  renderTabPane();
  syncInputsFromState();
  bindDynamicEvents();
}

function bindDynamicEvents() {
  document.querySelectorAll("[data-mode]").forEach((button) => {
    button.onclick = () => setMode(button.dataset.mode);
  });
  document.querySelectorAll("[data-example]").forEach((button) => {
    button.onclick = () => {
      const example = QUICK_TESTS.find((item) => item.id === button.dataset.example);
      if (!example) return;
      state.mode = example.mode;
      state.requestText = example.prompt;
      state.paperFile = null;
      state.paperFileLabel = "";
      state.runCello = false;
      state.forceHeuristic = false;
      state.currentTab = "diff";
      state.selectedCollection = null;
      if (example.mode === "official_quick_design") {
        state.brief = deepClone(state.bootstrap.default_brief);
      }
      if (example.mode === "custom_components") {
        state.customDraftText = pretty(state.bootstrap.default_custom_draft);
      }
      renderAll();
    };
  });
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.onclick = () => setTab(button.dataset.tab);
  });
  document.querySelectorAll("[data-collection]").forEach((button) => {
    button.onclick = () => setSelectedCollection(button.dataset.collection);
  });

  const request = document.getElementById("request-text");
  if (request) {
    request.oninput = (event) => {
      state.requestText = event.target.value;
    };
  }
  if (state.mode === "official_quick_design") {
    const briefIds = [
      "brief-design-name",
      "brief-summary",
      "brief-chassis",
      "brief-logic",
      "brief-input-1-name",
      "brief-input-1-desc",
      "brief-input-1-signal",
      "brief-input-1-sensor",
      "brief-input-2-name",
      "brief-input-2-desc",
      "brief-input-2-signal",
      "brief-input-2-sensor",
      "brief-output-name",
      "brief-output-device",
      "brief-output-desc",
      "brief-output-signal",
      "brief-constraint-1",
      "brief-constraint-2",
    ];
    briefIds.forEach((id) => {
      const element = document.getElementById(id);
      if (!element) return;
      const syncBrief = () => {
        state.brief = buildBriefFromState();
      };
      element.oninput = syncBrief;
      element.onchange = syncBrief;
    });
  }
  const baseVersion = document.getElementById("base-version");
  if (baseVersion) {
    baseVersion.onchange = (event) => {
      state.baseVersion = event.target.value;
      renderAll();
    };
  }
  const forceHeuristic = document.getElementById("force-heuristic");
  if (forceHeuristic) {
    forceHeuristic.onchange = (event) => {
      state.forceHeuristic = event.target.checked;
    };
  }
  const runCello = document.getElementById("run-cello");
  if (runCello) {
    runCello.onchange = (event) => {
      state.runCello = event.target.checked;
    };
  }
  const paperFile = document.getElementById("paper-file");
  if (paperFile) {
    paperFile.onchange = (event) => {
      const file = event.target.files?.[0] || null;
      state.paperFile = file;
      state.paperFileLabel = file ? `${file.name} (${Math.round(file.size / 1024)} KB)` : "No file selected";
      document.getElementById("paper-file-label").textContent = state.paperFileLabel;
    };
  }
  const customDraft = document.getElementById("custom-draft-text");
  if (customDraft) {
    customDraft.oninput = (event) => {
      state.customDraftText = event.target.value;
    };
  }
  const resetButton = document.getElementById("reset-button");
  if (resetButton) {
    resetButton.onclick = () => {
      loadExampleDefaults();
    };
  }
  const templateButton = document.getElementById("load-template-button");
  if (templateButton) {
    templateButton.onclick = () => {
      loadModeTemplate();
    };
  }
  const runButton = document.getElementById("run-button");
  if (runButton) {
    runButton.onclick = () => {
      void submitDesign();
    };
  }
  const applyEditor = document.getElementById("apply-editor");
  if (applyEditor) {
    applyEditor.onclick = () => {
      const editor = document.getElementById("generated-editor");
      if (!editor) return;
      try {
        state.generatedUcf = JSON.parse(editor.value);
        state.editorError = "";
        state.editorText = editor.value;
        state.diff = buildDiff(state.baseUcf || [], state.generatedUcf || []);
        renderAll();
      } catch (error) {
        state.editorError = `Invalid JSON: ${error.message}`;
        renderAll();
      }
    };
  }
  const downloadGenerated = document.getElementById("download-generated");
  if (downloadGenerated) {
    downloadGenerated.onclick = () => {
      const blob = new Blob([pretty(state.generatedUcf || {})], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "generated.UCF.json";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    };
  }
  const downloadDiff = document.getElementById("download-diff");
  if (downloadDiff) {
    downloadDiff.onclick = () => {
      const blob = new Blob([pretty(state.diff || {})], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "ucf.diff.json";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    };
  }
}

function loadExampleDefaults() {
  state.mode = "official_quick_design";
  state.currentTab = "diff";
  state.selectedCollection = null;
  state.requestText = state.bootstrap.default_request_text;
  state.baseVersion = state.bootstrap.default_base_version;
  state.paperFile = null;
  state.paperFileLabel = "";
  state.customDraftText = pretty(state.bootstrap.default_custom_draft);
  state.brief = deepClone(state.bootstrap.default_brief);
  state.forceHeuristic = false;
  state.runCello = false;
  state.baseUcf = null;
  state.generatedUcf = null;
  state.diff = null;
  state.response = null;
  state.busy = false;
  state.editorText = "";
  state.editorError = "";
  renderAll();
}

function loadModeTemplate() {
  if (state.mode === "official_quick_design") {
    state.brief = deepClone(state.bootstrap.default_brief);
    renderAll();
    return;
  }
  if (state.mode === "custom_components") {
    state.customDraftText = pretty(state.bootstrap.default_custom_draft);
    renderAll();
    return;
  }
  state.requestText = state.bootstrap.scenario_presets.find((preset) => preset.id === state.mode)?.prompt || state.requestText;
  renderAll();
}

function buildPayload() {
  const form = new FormData();
  form.append("mode", state.mode);
  form.append("request_text", state.requestText || "");
  form.append("base_version", state.baseVersion || state.bootstrap.default_base_version);
  form.append("force_heuristic", String(Boolean(state.forceHeuristic)));
  form.append("run_cello", String(Boolean(state.runCello)));
  form.append("max_source_chars", "60000");

  if (state.mode === "paper_assisted" && state.paperFile) {
    form.append("source_file", state.paperFile, state.paperFile.name);
  }
  if (state.mode === "official_quick_design") {
    form.append("brief_json", JSON.stringify(state.brief || buildBriefFromState()));
  }
  if (state.mode === "custom_components") {
    form.append("custom_draft_json", state.customDraftText || "");
  }
  return form;
}

async function submitDesign() {
  state.busy = true;
  document.getElementById("status-meta").textContent = "Running...";
  const runButton = document.getElementById("run-button");
  if (runButton) runButton.disabled = true;
  try {
    const response = await fetch("/api/design", {
      method: "POST",
      body: buildPayload(),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || `Request failed with status ${response.status}`);
    }
    const data = await response.json();
    state.response = data;
    state.baseUcf = data.base_ucf || [];
    state.generatedUcf = data.generated_ucf || [];
    state.diff = data.ucf_diff || buildDiff(state.baseUcf, state.generatedUcf);
    state.editorText = pretty(state.generatedUcf || []);
    state.editorError = "";
    state.baseVersion = data.base_version || state.baseVersion;
    renderAll();
  } catch (error) {
    state.response = {
      result_summary: {
        warnings: [error.message],
        validation_issues: [error.message],
      },
    };
    renderAll();
  } finally {
    state.busy = false;
    const runButtonInner = document.getElementById("run-button");
    if (runButtonInner) runButtonInner.disabled = false;
    document.getElementById("status-meta").textContent = "Ready";
  }
}

async function init() {
  app.innerHTML = buildShell();
  const response = await fetch("/api/bootstrap");
  state.bootstrap = await response.json();
  state.baseVersion = state.bootstrap.default_base_version;
  state.requestText = state.bootstrap.default_request_text;
  state.brief = deepClone(state.bootstrap.default_brief);
  state.customDraftText = pretty(state.bootstrap.default_custom_draft);
  state.mode = "official_quick_design";
  renderAll();
}

init().catch((error) => {
  app.innerHTML = `
    <div class="loading-card">
      <div class="loading-kicker">Ciallo Studio</div>
      <h1>Unable to launch the frontend</h1>
      <p>${escapeHtml(error.message)}</p>
    </div>
  `;
});
