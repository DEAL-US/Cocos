const LOW_THRESHOLD = 0.35;
const HIGH_THRESHOLD = 0.65;

// How each verdict of a model is shown (see prediction/results.py)
const CALLS = {
  R: { label: 'Resistant', level: 'prediction-high' },
  S: { label: 'Susceptible', level: 'prediction-low' },
  not_detected: { label: 'Not detected', level: 'prediction-no-result' },
};

// How each judgement of the trust of a prediction is shown (see trust_rules.toml)
const TRUST_STYLES = {
  for: { badge: 'badge-success', icon: 'bi-check-circle', text: 'text-success', soft: 'bg-success/10', circle: 'bg-success/15 text-success' },
  caution: { badge: 'badge-warning', icon: 'bi-exclamation-triangle', text: 'text-warning', soft: 'bg-warning/10', circle: 'bg-warning/15 text-warning' },
  serious: { badge: 'badge-error', icon: 'bi-x-octagon', text: 'text-error', soft: 'bg-error/10', circle: 'bg-error/15 text-error' },
};


function initializeMatrix(container) {
  const lowThresholdElement = container.querySelector('.prediction-low-threshold');

  const highThresholdElement = container.querySelector('.prediction-high-threshold');

  if (lowThresholdElement) {
    lowThresholdElement.textContent = LOW_THRESHOLD;
  }

  if (highThresholdElement) {
    highThresholdElement.textContent = HIGH_THRESHOLD;
  }
}


function renderMatrix(container, matrix) {
  const template = document.getElementById('prediction-matrix-template');

  if (!template) {
    console.error('Prediction matrix template not found.');
    return;
  }

  container.innerHTML = template.innerHTML;

  initializeMatrix(container);

  const header = container.querySelector('.prediction-header');
  const body = container.querySelector('.prediction-body');

  if (!header || !body) {
    console.error('Prediction matrix elements not found.');
    return;
  }

  renderHeaders(header, matrix.models);
  renderRows(body, matrix);
}


function renderHeaders(header, models) {
  const averageHeader = header.querySelector('.prediction-average-header');

  models.forEach(model => {
    const th = document.createElement('th');

    th.className = 'prediction-table-header prediction-model-header';
    th.textContent = model;

    header.insertBefore(th, averageHeader);
  });
}

function renderRows(body, matrix) {
  body.innerHTML = '';

  matrix.antibiotics.forEach((antibiotic, index) => {
    const values = matrix.data[index];

    const row = document.createElement('tr');
    row.className = 'prediction-row';

    const antibioticCell = document.createElement('td');
    antibioticCell.className = 'prediction-antibiotic';
    antibioticCell.textContent = antibiotic;

    row.appendChild(antibioticCell);

    values.forEach((value, column) => {
      const trust = matrix.trust?.[index]?.[column];
      row.appendChild(createPredictionCell(value, trust, matrix.models[column], antibiotic));
    });

    row.appendChild(createAverageCell(values));

    body.appendChild(row);
  });
}


function createPredictionCell(result, trust, model, antibiotic) {
  const cell = document.createElement('td');
  cell.className = 'prediction-cell';

  if (result === 'NO_RESULT') {
    cell.classList.add('prediction-no-result');

    const content = document.createElement('div');
    content.className = 'prediction-cell-content';

    const label = document.createElement('span');
    label.className = 'prediction-value';
    label.textContent = 'No results';

    content.appendChild(label);
    cell.appendChild(content);

    return cell;
  }

  const content = document.createElement('div');
  content.className = 'prediction-cell-content';

  // A probability is shown as a value and a bar; a verdict, as its label. With both, the colour is the
  // probability's.
  const call = CALLS[result.call];
  const hasScore = result.score !== undefined && result.score !== null;

  if (hasScore) {
    const value = result.score;
    const level = getPredictionLevel(value);
    cell.classList.add(level);

    const valueElement = document.createElement('span');
    valueElement.className = 'prediction-value';
    valueElement.textContent = value.toFixed(2);

    const bar = document.createElement('div');
    bar.className = 'prediction-bar';

    const fill = document.createElement('div');
    fill.className = `prediction-bar-fill ${level}`;
    fill.style.width = `${(value * 100).toFixed(0)}%`;

    bar.appendChild(fill);

    content.append(valueElement, bar);
  } else {
    cell.classList.add(call.level);
  }

  if (call) {
    const callElement = document.createElement('span');
    callElement.className = 'prediction-value prediction-call';
    callElement.textContent = call.label;
    content.appendChild(callElement);
  }

  if (trust) {
    content.appendChild(createTrustBadge(trust, model, antibiotic));
  }
  cell.appendChild(content);

  return cell;
}


function createTrustBadge(trust, model, antibiotic) {
  const badge = document.createElement('button');
  badge.type = 'button';
  const style = TRUST_STYLES[trust.judgement];
  badge.className = `badge badge-sm badge-soft ${style.badge} prediction-trust-badge`;
  badge.title = 'Why? See the evidence';
  badge.setAttribute('aria-haspopup', 'dialog');

  const icon = document.createElement('i');
  icon.className = `bi ${style.icon}`;

  const label = document.createElement('span');
  label.textContent = `Trust: ${trust.level}`;

  const more = document.createElement('i');
  more.className = 'bi bi-chevron-right prediction-trust-more';

  badge.append(icon, label, more);
  badge.addEventListener('click', () => openTrustDialog(trust, model, antibiotic));
  return badge;
}


function openTrustDialog(trust, model, antibiotic) {
  const dialog = document.getElementById('trust-dialog');

  if (!dialog) {
    return;
  }

  const style = TRUST_STYLES[trust.judgement];
  dialog.querySelector('.trust-dialog-icon').className =
    `trust-dialog-icon shrink-0 w-11 h-11 rounded-full flex items-center justify-center text-xl ${style.circle}`;
  dialog.querySelector('.trust-dialog-icon i').className = `bi ${style.icon}`;
  dialog.querySelector('.trust-dialog-title').textContent = trust.level;
  dialog.querySelector('.trust-dialog-subject').textContent = `${model} · ${antibiotic}`;

  const groups = dialog.querySelector('.trust-dialog-groups');
  groups.innerHTML = '';

  const against = trust.evidence.filter(item => item.judgement !== 'for');
  const inFavour = trust.evidence.filter(item => item.judgement === 'for');

  if (against.length) {
    groups.appendChild(createEvidenceGroup('Why to be careful', against));
  }

  if (inFavour.length) {
    groups.appendChild(createEvidenceGroup('In favour', inFavour));
  }

  dialog.showModal();
}


function createEvidenceGroup(title, items) {
  const group = document.createElement('section');

  const heading = document.createElement('h4');
  heading.className = 'text-sm font-semibold mb-2';
  heading.textContent = title;

  const list = document.createElement('ul');
  list.className = 'space-y-2';

  items.forEach(item => {
    const style = TRUST_STYLES[item.judgement];

    const entry = document.createElement('li');
    entry.className = `flex items-start gap-3 rounded-box px-3 py-2.5 text-sm ${style.soft}`;

    const icon = document.createElement('i');
    icon.className = `bi ${style.icon} ${style.text} text-base leading-5 shrink-0`;
    icon.setAttribute('aria-hidden', 'true');

    const text = document.createElement('span');
    text.textContent = item.text;

    entry.append(icon, text);
    list.appendChild(entry);
  });

  group.append(heading, list);
  return group;
}


function createAverageCell(values) {
  const cell = document.createElement('td');
  cell.className = 'prediction-cell prediction-average';

  // The average is of the probabilities only: a verdict has none.
  const numericValues = values
    .filter(result => result !== 'NO_RESULT' && result?.score !== undefined && result?.score !== null)
    .map(result => result.score);

  if (numericValues.length === 0) {
    cell.classList.add('prediction-no-result');

    const content = document.createElement('div');
    content.className = 'prediction-cell-content';

    const label = document.createElement('span');
    label.className = 'prediction-value';
    label.textContent = 'N/A';

    content.appendChild(label);
    cell.appendChild(content);

    return cell;
  }

  const average =
    numericValues.reduce((sum, value) => sum + value, 0) /
    numericValues.length;

  const roundedAverage = Number(average.toFixed(2));
  const level = getPredictionLevel(roundedAverage);

  cell.classList.add(level);

  const content = document.createElement('div');
  content.className = 'prediction-cell-content';

  const valueElement = document.createElement('span');
  valueElement.className = 'prediction-value';
  valueElement.textContent = roundedAverage.toFixed(2);

  const bar = document.createElement('div');
  bar.className = 'prediction-bar';

  const fill = document.createElement('div');
  fill.className = `prediction-bar-fill ${level}`;
  fill.style.width = `${(roundedAverage * 100).toFixed(0)}%`;

  bar.appendChild(fill);

  const riskElement = document.createElement('span');
  riskElement.className = `prediction-risk ${level}`;
  riskElement.textContent = getRiskLabel(roundedAverage);

  content.append(valueElement, bar, riskElement);
  cell.appendChild(content);

  return cell;
}


function getPredictionLevel(value) {
  if (value < LOW_THRESHOLD) {
    return 'prediction-low';
  }

  if (value < HIGH_THRESHOLD) {
    return 'prediction-medium';
  }

  return 'prediction-high';
}


function getRiskLabel(value) {
  if (value < LOW_THRESHOLD) {
    return 'Low';
  }

  if (value < HIGH_THRESHOLD) {
    return 'Medium';
  }

  return 'High';
}


function initializePredictionMatrices() {
  document.querySelectorAll('.prediction-matrix').forEach(container => {
    const matrixId = container.dataset.matrixId;

    if (!matrixId) {
      return;
    }

    const matrixElement = document.getElementById(matrixId);

    if (!matrixElement) {
      return;
    }

    try {
      const matrix = JSON.parse(matrixElement.textContent);
      renderMatrix(container, matrix);
    } catch (error) {
      console.error('Could not parse prediction matrix:', error);
    }
  });
}


document.addEventListener(
  'DOMContentLoaded',
  initializePredictionMatrices
);