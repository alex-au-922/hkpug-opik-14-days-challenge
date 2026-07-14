"use strict";

const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
const SERIES_COLORS = [
  "#2f6fd3",
  "#df493f",
  "#f08a00",
  "#168a3a",
  "#8754c7",
  "#0f8c99",
  "#c33f78",
  "#795548",
  "#3e6b91",
  "#9a7b00",
  "#256d4f",
  "#a54921",
  "#4764a8",
  "#8b4f86",
  "#447a1d",
];
const SCORE_CHART = {
  width: 1200,
  height: 500,
  top: 28,
  right: 176,
  bottom: 62,
  left: 72,
};

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
  historyChart: document.getElementById("score-history-chart"),
  historyEmpty: document.getElementById("score-history-empty"),
  historyLegend: document.getElementById("score-history-legend"),
  historyRange: document.getElementById("score-history-range"),
  historySubmissions: document.getElementById("score-history-submissions"),
  body: document.getElementById("leaderboard-body"),
  detail: document.getElementById("team-detail"),
  detailTitle: document.getElementById("team-detail-title"),
  teamRank: document.getElementById("team-rank"),
  teamIdentifier: document.getElementById("team-identifier"),
  detailBest: document.getElementById("detail-best"),
  detailLatest: document.getElementById("detail-latest"),
  detailDiscovery: document.getElementById("detail-discovery"),
  detailHoldout: document.getElementById("detail-holdout"),
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
    payload.challenge.max_daily_attempts !== 8 ||
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
    typeof run.completed_at !== "string" ||
    Number.isNaN(Date.parse(run.completed_at)) ||
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
  renderScoreHistory(
    payload.teams,
    payload.generated_at,
    payload.challenge.timezone,
  );
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
  renderCriterionBreakdown(team.best.criteria);
}

function renderScoreHistory(teams, updatedAt, timezone) {
  const scoredRunCount = teams.reduce((total, team) => total + team.runs.length, 0);
  elements.historySubmissions.textContent = `${scoredRunCount} scored run${scoredRunCount === 1 ? "" : "s"}`;

  if (scoredRunCount === 0) {
    elements.historyChart.setAttribute("hidden", "");
    elements.historyEmpty.hidden = false;
    elements.historyLegend.replaceChildren();
    elements.historyRange.textContent = "No score range yet";
    return;
  }

  const scores = teams.flatMap((team) =>
    team.runs.map((run) => run.overall_score),
  );
  const timestamps = teams.flatMap((team) =>
    team.runs.map((run) => Date.parse(run.completed_at)),
  );
  const yBounds = scoreBounds(scores);
  const xBounds = timestampBounds(timestamps, updatedAt);
  const plotRight = SCORE_CHART.width - SCORE_CHART.right;
  const plotBottom = SCORE_CHART.height - SCORE_CHART.bottom;
  const plotWidth = plotRight - SCORE_CHART.left;
  const plotHeight = plotBottom - SCORE_CHART.top;
  const scaleX = (timestamp) =>
    SCORE_CHART.left +
    ((timestamp - xBounds.minimum) / (xBounds.maximum - xBounds.minimum)) *
      plotWidth;
  const scaleY = (score) =>
    SCORE_CHART.top +
    ((yBounds.maximum - score) / (yBounds.maximum - yBounds.minimum)) *
      plotHeight;

  elements.historyRange.textContent = `Visible range: ${formatScore(yBounds.minimum)} to ${formatScore(yBounds.maximum)} points`;
  elements.historyLegend.replaceChildren(
    ...teams.map((team, index) => {
      const item = document.createElement("span");
      item.className = "score-history-legend-item";
      item.title = team.display_name;
      const swatch = document.createElement("span");
      swatch.className = "score-history-legend-swatch";
      swatch.style.setProperty(
        "--series-color",
        SERIES_COLORS[index % SERIES_COLORS.length],
      );
      const label = document.createElement("span");
      label.textContent = team.team_id;
      item.append(swatch, label);
      return item;
    }),
  );

  elements.historyChart.replaceChildren(
    createSvgElement(
      "title",
      { id: "score-history-svg-title" },
      "Official score history by team",
    ),
    createSvgElement(
      "desc",
      { id: "score-history-svg-description" },
      `Step lines show ${scoredRunCount} scored runs. The visible score range is ${formatScore(yBounds.minimum)} to ${formatScore(yBounds.maximum)} points.`,
    ),
  );

  const grid = createSvgElement("g", { "aria-hidden": "true" });
  const yTickCount = Math.min(
    7,
    Math.max(3, Math.round((yBounds.maximum - yBounds.minimum) / yBounds.step) + 1),
  );
  for (let index = 0; index < yTickCount; index += 1) {
    const ratio = index / (yTickCount - 1);
    const score = yBounds.maximum - ratio * (yBounds.maximum - yBounds.minimum);
    const y = SCORE_CHART.top + ratio * plotHeight;
    grid.append(
      createSvgElement("line", {
        class: "score-chart-grid-line",
        x1: SCORE_CHART.left,
        y1: y,
        x2: plotRight,
        y2: y,
      }),
      createSvgElement(
        "text",
        {
          class: "score-chart-axis-label",
          x: SCORE_CHART.left - 12,
          y: y + 4,
          "text-anchor": "end",
        },
        formatScore(score),
      ),
    );
  }

  const xTickCount = 6;
  for (let index = 0; index < xTickCount; index += 1) {
    const ratio = index / (xTickCount - 1);
    const timestamp =
      xBounds.minimum + ratio * (xBounds.maximum - xBounds.minimum);
    const x = SCORE_CHART.left + ratio * plotWidth;
    grid.append(
      createSvgElement("line", {
        class: "score-chart-grid-line",
        x1: x,
        y1: SCORE_CHART.top,
        x2: x,
        y2: plotBottom,
      }),
      createSvgElement(
        "text",
        {
          class: "score-chart-axis-label",
          x,
          y: plotBottom + 30,
          "text-anchor": "middle",
        },
        formatChartDate(timestamp, timezone, xBounds.maximum - xBounds.minimum),
      ),
    );
  }
  grid.append(
    createSvgElement("line", {
      class: "score-chart-axis-line",
      x1: SCORE_CHART.left,
      y1: SCORE_CHART.top,
      x2: SCORE_CHART.left,
      y2: plotBottom,
    }),
    createSvgElement("line", {
      class: "score-chart-axis-line",
      x1: SCORE_CHART.left,
      y1: plotBottom,
      x2: plotRight,
      y2: plotBottom,
    }),
  );
  elements.historyChart.append(grid);

  const labels = [];
  teams.forEach((team, index) => {
    const color = SERIES_COLORS[index % SERIES_COLORS.length];
    const runs = [...team.runs].sort(
      (left, right) => Date.parse(left.completed_at) - Date.parse(right.completed_at),
    );
    const points = runs.map((run) => ({
      x: scaleX(Date.parse(run.completed_at)),
      y: scaleY(run.overall_score),
      run,
    }));
    let path = `M ${points[0].x} ${points[0].y}`;
    for (const point of points.slice(1)) {
      path += ` H ${point.x} V ${point.y}`;
    }
    path += ` H ${plotRight}`;

    const series = createSvgElement("g", {
      class: "score-chart-series",
      style: `--series-color: ${color}`,
    });
    series.append(
      createSvgElement("path", {
        class: "score-chart-series-line",
        d: path,
      }),
    );
    points.forEach((point) => {
      const marker = createSvgElement("circle", {
        class: "score-chart-point",
        cx: point.x,
        cy: point.y,
        r: 5,
      });
      marker.append(
        createSvgElement(
          "title",
          {},
          `${team.display_name}, run ${point.run.attempt}: ${formatScore(point.run.overall_score)} points at ${formatDateTime(point.run.completed_at, timezone)}`,
        ),
      );
      series.append(marker);
    });
    elements.historyChart.append(series);
    labels.push({
      color,
      score: points.at(-1).run.overall_score,
      targetY: points.at(-1).y,
      teamId: team.team_id,
    });
  });

  distributeLabels(labels, SCORE_CHART.top + 12, plotBottom - 12, 27).forEach(
    (label) => {
      const labelX = plotRight + 14;
      const shortTeamId =
        label.teamId.length > 15
          ? `${label.teamId.slice(0, 14)}...`
          : label.teamId;
      const group = createSvgElement("g", {
        style: `--series-color: ${label.color}`,
      });
      group.append(
        createSvgElement("line", {
          class: "score-chart-label-connector",
          x1: plotRight,
          y1: label.targetY,
          x2: labelX,
          y2: label.labelY,
        }),
        createSvgElement("rect", {
          class: "score-chart-label-box",
          x: labelX,
          y: label.labelY - 12,
          width: 154,
          height: 24,
          rx: 4,
        }),
        createSvgElement(
          "text",
          {
            class: "score-chart-label-text",
            x: labelX + 8,
            y: label.labelY + 4,
          },
          `${shortTeamId} ${formatScore(label.score)}`,
        ),
      );
      elements.historyChart.append(group);
    },
  );

  elements.historyEmpty.hidden = true;
  elements.historyChart.removeAttribute("hidden");
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

function createSvgElement(name, attributes, text) {
  const element = document.createElementNS(SVG_NAMESPACE, name);
  Object.entries(attributes || {}).forEach(([key, value]) => {
    element.setAttribute(key, String(value));
  });
  if (text !== undefined) {
    element.textContent = text;
  }
  return element;
}

function scoreBounds(scores) {
  const rawMinimum = Math.min(...scores);
  const rawMaximum = Math.max(...scores);
  const spread = rawMaximum - rawMinimum;
  const padding = Math.max(spread * 0.12, 0.5);
  const targetSpan = Math.max(spread + padding * 2, 2);
  const step = niceStep(targetSpan / 5);
  let minimum = Math.max(0, Math.floor((rawMinimum - padding) / step) * step);
  let maximum = Math.min(100, Math.ceil((rawMaximum + padding) / step) * step);

  if (maximum - minimum < step * 2) {
    minimum = Math.max(0, minimum - step);
    maximum = Math.min(100, maximum + step);
  }
  if (minimum === maximum) {
    minimum = Math.max(0, minimum - 1);
    maximum = Math.min(100, maximum + 1);
  }
  return {
    minimum: round(minimum),
    maximum: round(maximum),
    step,
  };
}

function niceStep(value) {
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const fraction = value / magnitude;
  const niceFraction = fraction < 1.5 ? 1 : fraction < 3 ? 2 : fraction < 7 ? 5 : 10;
  return niceFraction * magnitude;
}

function timestampBounds(timestamps, updatedAt) {
  const validTimestamps = timestamps.filter(Number.isFinite);
  let minimum = Math.min(...validTimestamps);
  let maximum = Math.max(...validTimestamps, Date.parse(updatedAt));
  const twelveHours = 12 * 60 * 60 * 1000;

  if (maximum - minimum < twelveHours * 2) {
    minimum -= twelveHours;
    maximum += twelveHours;
  }
  return { minimum, maximum };
}

function distributeLabels(labels, minimum, maximum, gap) {
  const sorted = [...labels].sort((left, right) => left.targetY - right.targetY);
  let previous = minimum - gap;
  sorted.forEach((label) => {
    label.labelY = Math.max(label.targetY, previous + gap);
    previous = label.labelY;
  });
  if (sorted.length && sorted.at(-1).labelY > maximum) {
    const shift = sorted.at(-1).labelY - maximum;
    sorted.forEach((label) => {
      label.labelY -= shift;
    });
  }
  for (let index = sorted.length - 2; index >= 0; index -= 1) {
    sorted[index].labelY = Math.min(
      sorted[index].labelY,
      sorted[index + 1].labelY - gap,
    );
  }
  return sorted;
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

function formatChartDate(value, timezone, visibleSpan) {
  const withinThreeDays = visibleSpan <= 3 * 24 * 60 * 60 * 1000;
  return new Intl.DateTimeFormat("en-HK", {
    day: "2-digit",
    hour: withinThreeDays ? "2-digit" : undefined,
    minute: withinThreeDays ? "2-digit" : undefined,
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
