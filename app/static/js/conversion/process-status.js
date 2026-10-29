(() => {
  const processShell = document.querySelector('.process-shell');

  if (!processShell) {
    return;
  }

  const loadPage = async (url, pushHistory = false) => {
    try {
      const response = await fetch(url, {
        headers: {'X-Requested-With': 'XMLHttpRequest'},
      });

      if (!response.ok) {
        window.location.href = url;
        return;
      }

      const documentHtml = new DOMParser().parseFromString(await response.text(), 'text/html');

      const nextPredictions = documentHtml.querySelector('#predictions-section');

      if (!nextPredictions) {
        window.location.href = url;
        return;
      }

      processShell
        .querySelector('#predictions-section')
        .replaceWith(nextPredictions);

      if (pushHistory) {
        window.history.pushState({}, '', url);
      }

      initializePredictionMatrices();

    } catch {
      window.location.href = url;
    }
  };

  processShell.addEventListener('click', event => {
    const pageLink = event.target.closest('[data-prediction-page]');

    if (!pageLink || !processShell.contains(pageLink)) {
      return;
    }

    event.preventDefault();
    loadPage(pageLink.href, true);
  });

  window.addEventListener('popstate', () => {
    loadPage(window.location.href);
  });
})();

// The name and the organism of the process are shown as text: their pencil shows the form to change them,
// which is saved without reloading the page.
(() => {
  const setEditing = (editor, editing) => {
    editor.querySelector('[data-inline-view]').hidden = editing;
    editor.querySelector('[data-inline-form]').hidden = !editing;

    if (editing) {
      editor.querySelector('input:not([type=hidden]), select').focus();
    }
  };

  const cancel = editor => {
    editor.querySelector('[data-inline-form]').reset();
    setEditing(editor, false);
    editor.querySelector('[data-inline-open]').focus();
  };

  // The view saves the form and redirects to this page: take the new state of the editor from it.
  // The message of the view is not shown, the editor already shows the change.
  const save = async (editor, form) => {
    const button = form.querySelector('[type=submit]');
    button.disabled = true;

    try {
      const response = await fetch(form.action, {method: 'POST', body: new FormData(form)});

      if (!response.ok) {
        throw new Error(response.statusText);
      }

      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      const nextEditor = page.getElementById(editor.id);

      if (!nextEditor) {
        throw new Error('Missing editor');
      }

      editor.replaceWith(nextEditor);
      document.title = page.title;
      nextEditor.querySelector('[data-inline-open]').focus();
    } catch {
      form.submit();
    }
  };

  document.addEventListener('click', event => {
    const editor = event.target.closest('[data-inline-edit]');

    if (!editor) {
      return;
    }

    if (event.target.closest('[data-inline-open]')) {
      setEditing(editor, true);
    } else if (event.target.closest('[data-inline-cancel]')) {
      cancel(editor);
    }
  });

  document.addEventListener('submit', event => {
    const form = event.target.closest('[data-inline-form]');

    if (form) {
      event.preventDefault();
      save(form.closest('[data-inline-edit]'), form);
    }
  });

  document.addEventListener('keydown', event => {
    const editor = event.target.closest?.('[data-inline-edit]');

    if (editor && event.key === 'Escape') {
      cancel(editor);
    }
  });

  // The prediction page links here to set the organism.
  const organism = document.getElementById('organism');

  if (organism && window.location.hash === '#organism') {
    setEditing(organism, true);
  }
})();
