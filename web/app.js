const API_KEY_STORAGE_KEY = "sentiment-system-api-key";

const state = {
  apiKey: sessionStorage.getItem(API_KEY_STORAGE_KEY),
  editingThesisId: null,
};

const accountForm = document.querySelector("#account-form");
const thesisForm = document.querySelector("#thesis-form");
const accountMessage = document.querySelector("#account-message");
const thesisMessage = document.querySelector("#thesis-message");
const apiKeyPanel = document.querySelector("#api-key-panel");
const apiKeyValue = document.querySelector("#api-key-value");
const connectionState = document.querySelector("#connection-state");
const thesisList = document.querySelector("#thesis-list");
const thesisSubmit = document.querySelector("#thesis-submit");
const cancelEdit = document.querySelector("#cancel-edit");
const batchForm = document.querySelector("#batch-form");
const batchMessage = document.querySelector("#batch-message");
const batchSubmit = document.querySelector("#batch-submit");
const predictionCard = document.querySelector("#prediction-card");
const predictionMessage = document.querySelector("#prediction-message");
const predictionRunId = document.querySelector("#prediction-run-id");
const predictionBase = document.querySelector("#prediction-base");
const predictionPersonalized = document.querySelector("#prediction-personalized");
const predictionConfidence = document.querySelector("#prediction-confidence");
const predictionEvidence = document.querySelector("#prediction-evidence");

function setMessage(element, text, kind = "") {
  element.textContent = text;
  element.className = `message ${kind}`.trim();
}

function updateSessionView() {
  const hasKey = Boolean(state.apiKey);
  apiKeyPanel.hidden = !hasKey;
  apiKeyValue.textContent = hasKey ? state.apiKey : "";
  connectionState.textContent = hasKey ? "Session connected" : "Session not configured";
  connectionState.classList.toggle("ready", hasKey);
}

function setApiKey(apiKey) {
  state.apiKey = apiKey;
  if (apiKey) {
    sessionStorage.setItem(API_KEY_STORAGE_KEY, apiKey);
  } else {
    sessionStorage.removeItem(API_KEY_STORAGE_KEY);
  }
  updateSessionView();
}

function errorMessage(payload, status) {
  if (typeof payload?.detail === "string") {
    return payload.detail;
  }
  if (Array.isArray(payload?.detail)) {
    return payload.detail.map((item) => item.msg || "Invalid value").join("; ");
  }
  return `Request failed (${status})`;
}

async function request(path, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  if (options.body) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(path, { ...options, headers });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new Error(errorMessage(payload, response.status));
  }
  return payload;
}

function requireApiKey() {
  if (!state.apiKey) {
    throw new Error("Create an account first so the API key is available in this session.");
  }
  return state.apiKey;
}

function apiKeyQuery() {
  return `?api_key=${encodeURIComponent(requireApiKey())}`;
}

function readBatchForm() {
  const company = document.querySelector("#batch-company").value.trim().toUpperCase();
  const asOf = document.querySelector("#batch-as-of").value;
  if (!company || !asOf) {
    throw new Error("Choose a company and as-of date before running the batch.");
  }
  return { company, asOf };
}

function predictionPath(company, asOf) {
  const params = new URLSearchParams({
    api_key: requireApiKey(),
    as_of: asOf,
    forecast_horizon_days: "20",
  });
  return `/companies/${encodeURIComponent(company)}/prediction?${params.toString()}`;
}

function formatSentiment(sentiment) {
  return `${sentiment.label} · ${Number(sentiment.score).toFixed(2)}`;
}

function renderPrediction(prediction) {
  predictionCard.hidden = false;
  predictionRunId.textContent = `Run ${prediction.run_id}`;
  predictionBase.textContent = formatSentiment(prediction.base_sentiment);
  predictionPersonalized.textContent = formatSentiment(prediction.personalized_sentiment);
  predictionConfidence.textContent = `${(Number(prediction.confidence) * 100).toFixed(0)}%`;
  const evidence = prediction.evidence || [];
  const renderEvidenceItem = (item) => `
      <article class="evidence-item">
        <div class="evidence-meta">
           <span>${escapeHtml(item.published_at)}</span>
           <span>Importance ${(Number(item.importance_score) * 100).toFixed(0)}%</span>
           <span class="evidence-sentiment evidence-sentiment-${String(item.sentiment.label).toLowerCase()}" aria-label="Evidence sentiment: ${escapeHtml(item.sentiment.label)}">Sentiment ${escapeHtml(item.sentiment.label)} · ${Number(item.sentiment.score).toFixed(2)}</span>
        </div>
        <p>${escapeHtml(item.excerpt)}</p>
      </article>
    `;
  if (!evidence.length) {
    predictionEvidence.innerHTML = '<div class="empty-state">No qualifying evidence was returned for this snapshot.</div>';
    return;
  }
  const preview = evidence.slice(0, 5).map(renderEvidenceItem).join("");
  const remaining = evidence.slice(5);
  const more = remaining.length
    ? `<details class="evidence-more"><summary><span class="show-more-label">Show more (${remaining.length})</span><span class="show-less-label">Show less</span></summary>${remaining.map(renderEvidenceItem).join("")}</details>`
    : "";
  predictionEvidence.innerHTML = preview + more;
}

function readThesisForm() {
  const companies = document.querySelector("#thesis-companies").value
    .split(",")
    .map((company) => company.trim().toUpperCase())
    .filter(Boolean);
  return {
    companies,
    risk_tolerance: document.querySelector("#risk-tolerance").value,
    investment_horizon: document.querySelector("#investment-horizon").value,
    investment_style: document.querySelector("#investment-style").value,
    description: document.querySelector("#thesis-description").value.trim() || null,
  };
}

function resetThesisForm() {
  state.editingThesisId = null;
  thesisForm.reset();
  document.querySelector("#risk-tolerance").value = "medium";
  document.querySelector("#investment-horizon").value = "long_term";
  document.querySelector("#investment-style").value = "passive";
  thesisSubmit.textContent = "Save thesis";
  cancelEdit.hidden = true;
}

function editThesis(thesis) {
  state.editingThesisId = thesis.thesis_id;
  document.querySelector("#thesis-companies").value = thesis.companies.join(", ");
  document.querySelector("#risk-tolerance").value = thesis.risk_tolerance;
  document.querySelector("#investment-horizon").value = thesis.investment_horizon;
  document.querySelector("#investment-style").value = thesis.investment_style;
  document.querySelector("#thesis-description").value = thesis.description || "";
  thesisSubmit.textContent = "Update thesis";
  cancelEdit.hidden = false;
  document.querySelector("#thesis-title").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderTheses(theses) {
  if (!theses.length) {
    thesisList.innerHTML = '<div class="empty-state">No theses saved for this account yet.</div>';
    return;
  }
  thesisList.innerHTML = theses.map((thesis) => `
    <article class="thesis-card">
      <h3>${escapeHtml(thesis.companies.join(", "))}</h3>
      <div class="thesis-meta">
        <span class="tag">${escapeHtml(thesis.risk_tolerance)} risk</span>
        <span class="tag">${escapeHtml(thesis.investment_horizon.replace("_", " "))}</span>
        <span class="tag">${escapeHtml(thesis.investment_style)}</span>
      </div>
      <p>${escapeHtml(thesis.description || "No description provided.")}</p>
      <button class="button button-quiet edit-thesis" type="button" data-thesis-id="${escapeHtml(thesis.thesis_id)}">Edit thesis</button>
    </article>
  `).join("");
  thesisList.querySelectorAll(".edit-thesis").forEach((button) => {
    button.addEventListener("click", () => {
      const thesis = theses.find((item) => item.thesis_id === button.dataset.thesisId);
      if (thesis) editThesis(thesis);
    });
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function loadTheses() {
  if (!state.apiKey) {
    renderTheses([]);
    thesisList.innerHTML = '<div class="empty-state">Create an account to load saved theses.</div>';
    return;
  }
  try {
    const payload = await request(`/user/strategy${apiKeyQuery()}`);
    renderTheses(payload.theses || []);
  } catch (error) {
    setMessage(thesisMessage, error.message, "error");
  }
}

accountForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage(accountMessage, "Creating account...");
  try {
    const payload = await request("/user/account", {
      method: "POST",
      body: JSON.stringify({
        email: document.querySelector("#account-email").value.trim(),
        username: document.querySelector("#account-username").value.trim(),
      }),
    });
    setApiKey(payload.api_key);
    setMessage(accountMessage, "Account created. The key is available for this session.", "success");
    await loadTheses();
  } catch (error) {
    setMessage(accountMessage, error.message, "error");
  }
});

thesisForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage(thesisMessage, state.editingThesisId ? "Updating thesis..." : "Saving thesis...");
  try {
    const path = state.editingThesisId
      ? `/user/strategy/${encodeURIComponent(state.editingThesisId)}${apiKeyQuery()}`
      : `/user/strategy${apiKeyQuery()}`;
    await request(path, { method: state.editingThesisId ? "PUT" : "POST", body: JSON.stringify(readThesisForm()) });
    setMessage(thesisMessage, state.editingThesisId ? "Thesis updated." : "Thesis saved.", "success");
    resetThesisForm();
    await loadTheses();
  } catch (error) {
    setMessage(thesisMessage, error.message, "error");
  }
});

document.querySelector("#refresh-theses").addEventListener("click", loadTheses);
cancelEdit.addEventListener("click", resetThesisForm);
document.querySelector("#clear-session").addEventListener("click", () => {
  setApiKey(null);
  resetThesisForm();
  setMessage(accountMessage, "Session cleared.");
  setMessage(thesisMessage, "");
  thesisList.innerHTML = '<div class="empty-state">Create an account to load saved theses.</div>';
});

batchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage(batchMessage, "Running batch...");
  setMessage(predictionMessage, "");
  predictionCard.hidden = true;
  batchSubmit.disabled = true;
  try {
    const { company, asOf } = readBatchForm();
    requireApiKey();
    const batch = await request("/batch/run", {
      method: "POST",
      body: JSON.stringify({ company, as_of: asOf }),
    });
    setMessage(
      batchMessage,
      `Batch complete: ${batch.document_count} document(s), ${batch.scored_chunk_count} scored chunk(s).`,
      "success",
    );
    setMessage(predictionMessage, "Loading prediction...");
    const prediction = await request(predictionPath(company, asOf));
    renderPrediction(prediction);
    setMessage(predictionMessage, "Prediction ready.", "success");
  } catch (error) {
    setMessage(batchMessage, error.message, "error");
    setMessage(predictionMessage, "");
    predictionCard.hidden = true;
  } finally {
    batchSubmit.disabled = false;
  }
});

updateSessionView();
document.querySelector("#batch-as-of").value = new Date().toISOString().slice(0, 10);
loadTheses();
