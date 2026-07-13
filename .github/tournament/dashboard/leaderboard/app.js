"use strict";

const elements = {
  status: document.getElementById("challenge-status"),
  dates: document.getElementById("challenge-dates"),
  updated: document.getElementById("last-updated"),
  teamCount: document.getElementById("team-count"),
  runCount: document.getElementById("run-count"),
  topScore: document.getElementById("top-score"),
  weights: document.getElementById("score-weights"),
  loading: document.getElementById("loading-state"),
  empty: document.getElementById("empty-state"),
  error: document.getElementById("error-state"),
  content: document.getElementById("dashboard-content"),
  body: document.getElementById("leaderboard-body"),
  detail: document.getElementById("team-detail"),
  detailTitle: document.getElementById("team-detail-title"),
  teamRank: document.getElementById("team-rank"),
  teamIdentifier: document.getElementById("team-identifier"),
  detailBest: document.getElementById("detail-best"),
  detailLatest: document.getElementById("detail-latest"),
  detailDiscovery: document.getElementById("detail-discovery"),
  detailHoldout: document.getElementById("detail-holdout"),
  trend: document.getElementById("run-trend"),
  criteria: document.getElementById("criterion-breakdown"),
  announcement: document.getElementById("screen-reader-status"),
};

const criterionDefinitions = [
  ["deterministic", "Deterministic checks", 40],
  ["answer_relevance", "Answer relevance", 20],
  ["instruction_following", "Instruction following", 15],
  ["faithfulness", "Faithfulness", 25],
];

let leaderboard = null;
let selectedTeamId = null;

loadLeaderboard();

async function loadLeaderboard() {
  try {
    const response = await fetch("leaderboard.json", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Leaderboard request returned ${response.status}.`);
    }
    const payload = await response.json();
    validatePayload(payload);
    leaderboard = payload;
    renderDashboard(payload);
  } catch (_error) {
    showError();
  }
}

function validatePayload(payload) {
  if (!isRecord(payload) || payload.schema_version !== 1) {
    throw new Error("Unsupported leaderboard schema.");
  }
  if (!isRecord(payload.challenge) || !Array.isArray(payload.teams)) {
    throw new Error("Leaderboard is missing challenge or team data.");
  }
  if (
    payload.challenge.max_attempts !== 8 ||
    payload.challenge.max_daily_attempts !== 4 ||
    !isRecord(payload.challenge.weights) ||
    payload.challenge.weights.discovery !== 0.75 ||
    payload.challenge.weights.holdout !== 0.25
  ) {
    throw new Error("Leaderboard scoring contract is invalid.");
  }
  if (!["upcoming", "live", "ended"].includes(payload.challenge.status)) {
    throw new Error("Leaderboard challenge status is invalid.");
  }
  assertNoPrivateFields(payload);
  payload.teams.forEach(validateTeam);
}

function validateTeam(team, index) {
  if (
    !isRecord(team) ||
    team.rank !== index + 1 ||
    typeof team.team_id !== "string" ||
    typeof team.display_name !== "string" ||
    !Array.isArray(team.runs) ||
    team.runs.length < 1 ||
    !isRecord(team.best) ||
    !isRecord(team.latest)
  ) {
    throw new Error("Leaderboard contains an invalid team record.");
  }
  if (
    !Number.isInteger(team.attempts_used) ||
    team.attempts_used < team.runs.length ||
    team.attempts_used > 8 ||
    team.attempts_remaining !== 8 - team.attempts_used
  ) {
    throw new Error("Leaderboard contains invalid attempt counts.");
  }
  team.runs.forEach(validateRun);
}

function validateRun(run) {
  if (
    !isRecord(run) ||
    !Number.isInteger(run.attempt) ||
    run.attempt < 1 ||
    run.attempt > 8 ||
    !isScore(run.overall_score) ||
    !isScore(run.discovery_score) ||
    !isScore(run.holdout_score) ||
    !isRecord(run.criteria)
  ) {
    throw new Error("Leaderboard contains an invalid run record.");
  }
}

function assertNoPrivateFields(value) {
  if (Array.isArray(value)) {
    value.forEach(assertNoPrivateFields);
    return;
  }
  if (!isRecord(value)) {
    return;
  }
  const forbidden = /prompt|context|question|reference|submission_identity|head_sha|private_case/i;
  Object.entries(value).forEach(([key, child]) => {
    if (forbidden.test(key)) {
      throw new Error("Leaderboard includes a non-public field.");
    }
    assertNoPrivateFields(child);
  });
}

function renderDashboard(payload) {
  renderChallenge(payload.challenge, payload.generated_at);
  const scoredRuns = payload.teams.reduce(
    (count, team) => count + team.runs.length,
    0,
  );
  elements.teamCount.textContent = String(payload.teams.length);
  elements.runCount.textContent = String(scoredRuns);
  elements.topScore.textContent = payload.teams.length
    ? formatScore(payload.teams[0].best.overall_score)
    : "-";
  elements.weights.textContent = `${Math.round(payload.challenge.weights.discovery * 100)} / ${Math.round(payload.challenge.weights.holdout * 100)}`;
  elements.loading.hidden = true;

  if (payload.teams.length === 0) {
    elements.empty.hidden = false;
    elements.error.hidden = true;
    elements.content.hidden = true;
    document.documentElement.dataset.ready = "empty";
    return;
  }

  elements.empty.hidden = true;
  elements.error.hidden = true;
  elements.content.hidden = false;
  selectedTeamId = payload.teams[0].team_id;
  renderTable(payload.teams);
  renderTeam(payload.teams[0]);
  document.documentElement.dataset.ready = "loaded";
}

function renderChallenge(challenge, generatedAt) {
  const timezone = challenge.timezone;
  elements.status.textContent = challenge.status;
  elements.status.dataset.status = challenge.status;
  elements.dates.textContent = `${formatDate(challenge.starts_at, timezone)} - ${formatDate(challenge.ends_at, timezone)} · ${timezone}`;
  elements.updated.textContent = `Updated ${formatDateTime(generatedAt, timezone)}`;
}

function renderTable(teams) {
  const rows = teams.map((team) => {
    const row = document.createElement("tr");
    row.dataset.teamId = team.team_id;
    row.dataset.selected = String(team.team_id === selectedTeamId);

    const rankCell = createCell("Rank", "cell-rank");
    const rank = document.createElement("span");
    rank.className = "rank-value";
    rank.dataset.podium = String(team.rank <= 3);
    rank.textContent = String(team.rank).padStart(2, "0");
    rankCell.append(rank);

    const teamCell = createCell("Team", "cell-team");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "team-button";
    button.dataset.teamId = team.team_id;
    button.setAttribute("aria-controls", "team-detail");
    button.setAttribute("aria-pressed", String(team.team_id === selectedTeamId));
    button.textContent = team.display_name;
    button.addEventListener("click", () => selectTeam(team.team_id));
    const teamId = document.createElement("span");
    teamId.className = "team-id";
    teamId.textContent = team.team_id;
    teamCell.append(button, teamId);

    const bestCell = createCell("Best", "cell-best");
    bestCell.append(scoreFragment(team.best.overall_score));

    const latestCell = createCell("Latest", "cell-latest");
    latestCell.append(scoreFragment(team.latest.overall_score));

    const movementCell = createCell("Movement", "cell-movement");
    movementCell.append(movementFragment(team.runs));

    const attemptsCell = createCell("Attempts", "cell-attempts");
    attemptsCell.append(attemptFragment(team.attempts_used));

    row.append(
      rankCell,
      teamCell,
      bestCell,
      latestCell,
      movementCell,
      attemptsCell,
    );
    return row;
  });
  elements.body.replaceChildren(...rows);
}

function selectTeam(teamId) {
  if (!leaderboard) {
    return;
  }
  const team = leaderboard.teams.find((candidate) => candidate.team_id === teamId);
  if (!team) {
    return;
  }
  selectedTeamId = teamId;
  elements.body.querySelectorAll("tr").forEach((row) => {
    row.dataset.selected = String(row.dataset.teamId === teamId);
  });
  elements.body.querySelectorAll("button").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.teamId === teamId));
  });
  renderTeam(team);
  elements.announcement.textContent = `Showing ${team.display_name}, rank ${team.rank}.`;
}

function renderTeam(team) {
  elements.teamRank.textContent = `Rank ${team.rank} · ${team.attempts_used} of 8 attempts`;
  elements.detailTitle.textContent = team.display_name;
  elements.teamIdentifier.textContent = team.team_id;
  elements.detailBest.textContent = formatScore(team.best.overall_score);
  elements.detailLatest.textContent = formatScore(team.latest.overall_score);
  elements.detailDiscovery.textContent = formatScore(team.best.discovery_score);
  elements.detailHoldout.textContent = formatScore(team.best.holdout_score);
  renderRunTrend(team.runs, team.best.attempt);
  renderCriterionBreakdown(team.best.criteria);
}

function renderRunTrend(runs, bestAttempt) {
  const items = runs.map((run) => {
    const item = document.createElement("li");
    item.dataset.best = String(run.attempt === bestAttempt);
    item.setAttribute(
      "aria-label",
      `Attempt ${run.attempt}: ${formatScore(run.overall_score)} points${run.attempt === bestAttempt ? ", best run" : ""}.`,
    );

    const score = document.createElement("span");
    score.className = "run-score";
    score.textContent = formatScore(run.overall_score);

    const track = document.createElement("span");
    track.className = "run-track";
    track.setAttribute("aria-hidden", "true");
    const bar = document.createElement("span");
    bar.className = "run-bar";
    bar.style.setProperty("--score", String(run.overall_score));
    track.append(bar);

    const label = document.createElement("span");
    label.className = "run-label";
    label.textContent = `Run ${run.attempt}`;
    item.append(score, track, label);
    return item;
  });
  elements.trend.replaceChildren(...items);
}

function renderCriterionBreakdown(criteria) {
  const rows = criterionDefinitions.map(([key, label, maximum]) => {
    const value = criteria[key];
    const row = document.createElement("div");
    row.className = "criterion-row";

    const labelElement = document.createElement("label");
    const progressId = `criterion-${key}`;
    labelElement.htmlFor = progressId;
    labelElement.textContent = label;

    const score = document.createElement("span");
    score.className = "criterion-value";
    score.textContent = `${formatScore(value)} / ${maximum}`;

    const progress = document.createElement("progress");
    progress.id = progressId;
    progress.max = maximum;
    progress.value = value;
    progress.textContent = `${formatScore(value)} out of ${maximum}`;
    row.append(labelElement, score, progress);
    return row;
  });
  elements.criteria.replaceChildren(...rows);
}

function createCell(label, className) {
  const cell = document.createElement("td");
  cell.className = className;
  cell.dataset.label = label;
  return cell;
}

function scoreFragment(value) {
  const wrapper = document.createElement("span");
  const score = document.createElement("span");
  score.className = "score-value";
  score.textContent = formatScore(value);
  const suffix = document.createElement("span");
  suffix.className = "score-suffix";
  suffix.textContent = "pts";
  wrapper.append(score, suffix);
  return wrapper;
}

function movementFragment(runs) {
  const value = document.createElement("span");
  value.className = "movement";
  if (runs.length === 1) {
    value.dataset.direction = "new";
    value.textContent = "First run";
    return value;
  }
  const change = round(runs.at(-1).overall_score - runs.at(-2).overall_score);
  value.dataset.direction = change > 0 ? "up" : change < 0 ? "down" : "flat";
  value.textContent = change > 0 ? `+${formatScore(change)}` : formatScore(change);
  return value;
}

function attemptFragment(used) {
  const meter = document.createElement("span");
  meter.className = "attempt-meter";
  const dots = document.createElement("span");
  dots.className = "attempt-dots";
  dots.setAttribute("aria-hidden", "true");
  for (let attempt = 1; attempt <= 8; attempt += 1) {
    const dot = document.createElement("span");
    dot.dataset.used = String(attempt <= used);
    dots.append(dot);
  }
  const label = document.createElement("span");
  label.textContent = `${used} / 8`;
  meter.append(dots, label);
  meter.setAttribute("aria-label", `${used} of 8 attempts used`);
  return meter;
}

function showError() {
  elements.loading.hidden = true;
  elements.empty.hidden = true;
  elements.content.hidden = true;
  elements.error.hidden = false;
  elements.status.textContent = "Unavailable";
  elements.updated.textContent = "No published data";
  document.documentElement.dataset.ready = "error";
}

function formatDate(value, timezone) {
  return new Intl.DateTimeFormat("en-HK", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: timezone,
  }).format(new Date(value));
}

function formatDateTime(value, timezone) {
  return new Intl.DateTimeFormat("en-HK", {
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    month: "short",
    timeZone: timezone,
  }).format(new Date(value));
}

function formatScore(value) {
  return Number(value).toFixed(2);
}

function round(value) {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isScore(value) {
  return Number.isFinite(value) && value >= 0 && value <= 100;
}
