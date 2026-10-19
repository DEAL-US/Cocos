document.addEventListener('DOMContentLoaded', function () {
  const computeBtn = document.getElementById('compute-matrix');
  const sampleSelect = document.getElementById('sample-select');

  const predictionStatus = document.getElementById('prediction-status');

  const modelsSelectEl = document.getElementById('models-select');
  const antibioticsSelectEl = document.getElementById('antibiotics-select');

  const csrftoken = (() => {
    const el = document.querySelector('input[name=csrfmiddlewaretoken]');
    return el ? el.value : null;
  })();

  // Selection

  function initializeSelection() {
    if (modelsSelectEl) {
      modelsSelectEl.addEventListener('change', updateButtonsState);
    }

    if (antibioticsSelectEl) {
      antibioticsSelectEl.addEventListener('change', updateButtonsState);
    }

    if (sampleSelect) {
      sampleSelect.addEventListener('change', updateButtonsState);
    }

    updateButtonsState();
  }


  function collectSelection() {
    const models = (
      modelsSelectEl &&
      Array.isArray(modelsSelectEl.value)
    )
      ? modelsSelectEl.value.slice()
      : [];

    const antibiotics = (
      antibioticsSelectEl &&
      Array.isArray(antibioticsSelectEl.value)
    )
      ? antibioticsSelectEl.value.slice()
      : [];

    return {
      models: models,
      antibiotics: antibiotics,
      sample_id: sampleSelect ? sampleSelect.value : '',
    };
  }


  function updateButtonsState() {
    if (!computeBtn) {
      return;
    }

    const selection = collectSelection();

    const hasModels = selection.models.length > 0;
    const hasAntibiotics = selection.antibiotics.length > 0;
    const hasSample = Boolean(selection.sample_id);

    const enabled = hasModels && hasAntibiotics && hasSample;

    computeBtn.disabled = !enabled;
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


  // Multi-select initialization

  customElements.whenDefined('multi-select').then(() => {
    initializeSelection();
  });

  updateButtonsState();
});