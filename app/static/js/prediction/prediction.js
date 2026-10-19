document.addEventListener('DOMContentLoaded', function () {
  const computeBtn = document.getElementById('compute-matrix');
  const sampleSelect = document.getElementById('sample-select');
  const predictionStatus = document.getElementById('prediction-status');
  const antibioticsSelectEl = document.getElementById('antibiotics-select');

  const modelsList = document.getElementById('models-list');
  const modelsChips = document.getElementById('models-chips');
  const chipsPlaceholder = modelsChips.querySelector('[data-chips-placeholder]');
  const modelsCount = document.getElementById('models-count');
  const rowTemplate = document.getElementById('model-row-template');
  const stepTemplate = document.getElementById('model-step-template');
  const chipTemplate = document.getElementById('model-chip-template');
  const messageTemplate = document.getElementById('models-message-template');
  const preparationNote = document.getElementById('preparation-note');
  const sampleOrganism = document.getElementById('sample-organism');

  const STATUS_LABELS = { ready: 'Ready', reachable: 'Needs preparation', incompatible: 'Not available' };

  const csrftoken = (() => {
    const el = document.querySelector('input[name=csrfmiddlewaretoken]');
    return el ? el.value : null;
  })();

  // What the discovery says about each model for the selected sample
  let models = [];
  let loading = false;
  let sampleRequest = 0;

  // Models of the selected sample

  async function loadModels() {
    const sampleId = sampleSelect ? sampleSelect.value : '';
    const request = ++sampleRequest;
    models = [];
    loading = Boolean(sampleId);
    renderOrganism(null, null);
    renderModels();
    if (!sampleId) {
      return;
    }

    try {
      const response = await fetch(`/prediction/samples/${sampleId}/models/`);
      const data = await response.json();
      if (request !== sampleRequest) {
        return;  // another sample was selected meanwhile
      }
      loading = false;
      if (!response.ok) {
        renderModels();
        showError(data.error || 'Could not load the models of this sample.');
        return;
      }
      models = data.models.map(model => ({ ...model, selected: false }));
      renderOrganism(sampleId, data.organism);
      renderModels();
    } catch (error) {
      console.error('Error loading models:', error);
      loading = false;
      renderModels();
      showError('Could not load the models of this sample.');
    }
  }

  function renderOrganism(sampleId, organism) {
    if (!sampleOrganism) {
      return;
    }
    sampleOrganism.classList.toggle('hidden', !sampleId);
    if (sampleId) {
      sampleOrganism.querySelector('[data-organism-name]').textContent = organism || 'unknown';
      sampleOrganism.querySelector('[data-organism-link]').href = `/processes/${sampleId}/#organism`;
    }
  }

  function renderModels() {
    modelsList.replaceChildren(...(models.length ? models.map(renderRow) : [renderMessage()]));
    modelsCount.textContent = models.length;

    // The chips row keeps its height, so the page does not move when the first model is selected.
    const selected = models.filter(model => model.selected);
    modelsChips.replaceChildren(...(selected.length ? selected.map(renderChip) : [chipsPlaceholder]));

    const preparing = selected.filter(model => model.status === 'reachable');
    preparationNote.classList.toggle('hidden', preparing.length === 0);
    preparationNote.querySelector('[data-preparation-models]').textContent =
      preparing.map(model => model.model).join(', ');

    updateButtonsState();
  }

  function renderMessage() {
    const message = messageTemplate.content.firstElementChild.cloneNode(true);
    if (!(sampleSelect && sampleSelect.value)) {
      message.textContent = 'Select a sample first to see which models can run on it.';
    } else if (loading) {
      message.textContent = 'Checking which models can run on this sample…';
    } else {
      message.textContent = 'There are no prediction models available.';
    }
    return message;
  }

  function renderRow(model) {
    const row = rowTemplate.content.firstElementChild.cloneNode(true);
    const checkbox = row.querySelector('[data-model-checkbox]');

    checkbox.value = model.model;
    checkbox.checked = model.selected;
    checkbox.disabled = model.status === 'incompatible';
    checkbox.addEventListener('change', () => {
      model.selected = checkbox.checked;
      renderModels();
    });

    row.querySelector('[data-model-name]').textContent = model.model;

    const badge = row.querySelector('[data-model-status]');
    badge.textContent = STATUS_LABELS[model.status];
    badge.classList.add(...classesOf(model.status));

    const detail = row.querySelector('[data-model-detail]');
    const steps = row.querySelector('[data-model-steps]');
    if (model.status === 'reachable') {
      detail.textContent = 'To use this model Cocos will have to run first:';
      steps.replaceChildren(...model.steps.map(renderStep));
    } else if (model.status === 'incompatible') {
      detail.textContent = model.reasons.join(' ');
    }

    if (checkbox.disabled) {
      row.querySelector('[data-model-row]').classList.add(...classesOf('unavailable'));
    }
    return row;
  }

  function renderStep(label, index, labels) {
    const step = stepTemplate.content.firstElementChild.cloneNode(true);
    step.querySelector('[data-step-name]').textContent = `${index + 1}. ${label}`;
    if (index === labels.length - 1) {
      step.querySelector('[data-step-arrow]').remove();
    }
    return step;
  }

  function classesOf(status) {
    const key = `class${status.charAt(0).toUpperCase()}${status.slice(1)}`;
    return modelsList.dataset[key].split(' ');
  }

  function renderChip(model) {
    const chip = chipTemplate.content.firstElementChild.cloneNode(true);
    chip.querySelector('[data-chip-name]').textContent = model.model;
    chip.querySelector('[data-chip-remove]').addEventListener('click', () => {
      model.selected = false;
      renderModels();
    });
    return chip;
  }

  // Selection

  function collectSelection() {
    const antibiotics = (antibioticsSelectEl && Array.isArray(antibioticsSelectEl.value))
      ? antibioticsSelectEl.value.slice()
      : [];

    return {
      models: models.filter(model => model.selected).map(model => model.model),
      antibiotics: antibiotics,
      sample_id: sampleSelect ? sampleSelect.value : '',
    };
  }

  function updateButtonsState() {
    if (!computeBtn) {
      return;
    }
    const selection = collectSelection();
    computeBtn.disabled = !(selection.models.length && selection.antibiotics.length && selection.sample_id);
  }

  // Prediction

  async function computeMatrix() {
    const selection = collectSelection();
    const params = new URLSearchParams();

    selection.models.forEach(model => {
      params.append('models', model);
    });

    selection.antibiotics.forEach(antibiotic => {
      params.append('antibiotics', antibiotic);
    });

    params.append('sample_id', selection.sample_id);

    hideError();

    try {
      const response = await fetch('/prediction/matrix/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          'X-CSRFToken': csrftoken,
        },
        body: params.toString(),
      });

      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        showError(data.error || 'Error computing the prediction matrix.');
        return;
      }

      window.location.href = `/processes/${data.process_id}/`;

    } catch (error) {
      console.error('Error during fetch:', error);
      showError('Error computing the prediction matrix.');
    }
  }

  function showError(message) {
    if (!predictionStatus) {
      return;
    }
    predictionStatus.textContent = message;
    predictionStatus.classList.remove('hidden');
  }

  function hideError() {
    if (predictionStatus) {
      predictionStatus.classList.add('hidden');
    }
  }

  // Event listeners

  if (computeBtn) {
    computeBtn.addEventListener('click', event => {
      event.preventDefault();
      computeMatrix();
    });
  }

  if (sampleSelect) {
    sampleSelect.addEventListener('change', () => {
      hideError();
      loadModels();
    });
  }

  renderModels();

  customElements.whenDefined('multi-select').then(() => {
    if (antibioticsSelectEl) {
      antibioticsSelectEl.addEventListener('change', updateButtonsState);
    }
    updateButtonsState();
  });

  updateButtonsState();
});
