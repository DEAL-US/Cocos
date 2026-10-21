// Data flow graph, drawn with Cytoscape.js and laid out with dagre (top to bottom: the flow is a
// long chain, so it reads larger than left to right). The nodes and edges come from
// semantics/flow.py, in the flow-data script tag. On the registry page it shows the registry; on
// the flow page of a sample (data-flow-mode="sample") it also shows the state of the sample.
document.addEventListener('DOMContentLoaded', function () {
  const container = document.getElementById('flow-graph');
  const flowData = document.getElementById('flow-data');
  const details = document.getElementById('flow-details');
  if (!container || !flowData || typeof cytoscape === 'undefined') {
    return;
  }
  cytoscape.use(cytoscapeDagre);

  const sampleMode = container.dataset.flowMode === 'sample';
  const filesData = document.getElementById('flow-files');
  const files = filesData ? JSON.parse(filesData.textContent) : {};

  const TYPE_LABELS = { data: 'Data', step: 'Processing step', model: 'Prediction model' };
  const STEP_STATES = {
    completed: ['Done', 'badge-success'],
    running: ['Running', 'badge-warning'],
    pending: ['Waiting to run', 'badge-warning'],
    failed: ['Failed', 'badge-error'],
    planned: ['Would run to prepare a model', 'badge-primary'],
    unused: ['Not used for this sample', 'badge-ghost'],
  };
  const MODEL_STATES = {
    ready: ['Ready', 'badge-success'],
    reachable: ['Needs preparation', 'badge-info'],
    incompatible: ['Not available', 'badge-ghost'],
  };
  const RUN_STATES = { completed: 'Prediction done', running: 'Prediction running', pending: 'Prediction waiting to run', failed: 'Prediction failed' };
  const FONT_SIZE = 13;
  const NODE_SEP = 20;
  // Cytoscape needs the family without quotes, and a fallback
  const fontFamily = getComputedStyle(document.body).fontFamily.replace(/["']/g, '') + ', sans-serif';
  const colors = {
    page: themeColor('--color-base-100', '#ffffff'),
    data: themeColor('--color-base-200', '#eef3f4'),
    text: themeColor('--color-base-content', '#1f2a33'),
    step: themeColor('--color-primary', '#1e9aa0'),
    stepText: themeColor('--color-primary-content', '#ffffff'),
    model: themeColor('--color-secondary', '#2f5d7c'),
    modelText: themeColor('--color-secondary-content', '#ffffff'),
    accent: themeColor('--color-accent', '#2ec4c0'),
    warning: themeColor('--color-warning', '#c9a227'),
    warningText: themeColor('--color-warning-content', '#3a2d05'),
    error: themeColor('--color-error', '#e0605a'),
    errorText: themeColor('--color-error-content', '#3d0f0d'),
    line: themeColor('--color-neutral', '#3c4a57'),
  };

  const flow = JSON.parse(flowData.textContent);
  flow.nodes.forEach(function (node, index) {
    node.data.order = index;  // the order of the registry
    if (sampleMode) {
      node.classes = stateClass(node.data);
    }
  });
  flow.edges.forEach(function (edge) {
    // Several inputs fed by the same kind of data (Illumina r1 and r2) share one edge
    edge.data.label = edge.data.roles.length > 1 ? edge.data.roles.join(' + ') : '';
  });

  const cy = cytoscape({
    container: container,
    elements: flow,
    style: graphStyle(),
    layout: { name: 'preset' },
    minZoom: 0.3,
    maxZoom: 2.5,
    userZoomingEnabled: false,  // the mouse wheel scrolls the page; zoom with the buttons
    boxSelectionEnabled: false,
    autounselectify: true,
  });
  if (sampleMode) {
    // Data the sample does not have but the planned preparation would produce is on the path too
    cy.nodes('[type = "data"].absent').forEach(function (node) {
      if (node.incomers('node.planned').nonempty()) {
        node.removeClass('absent').addClass('planned');
      }
    });
    cy.edges().forEach(function (edge) {
      if (edge.source().hasClass('absent') || edge.target().hasClass('absent')) {
        edge.addClass('absent');
      }
    });
  }
  const layout = cy.layout({ name: 'dagre', rankDir: 'TB', nodeSep: NODE_SEP, rankSep: 35, edgeSep: 10 });
  layout.one('layoutstop', orderLevels);
  layout.run();
  cy.fit(undefined, 24);

  // A link to ?focus=<node id> (from the page of a step or model) selects that node
  const focused = cy.getElementById(new URLSearchParams(window.location.search).get('focus') || '');
  if (focused.nonempty()) {
    focus(focused);
  }

  cy.on('tap', 'node', function (event) { focus(event.target); });
  cy.on('tap', function (event) {
    if (event.target === cy) {
      clearFocus();
    }
  });

  document.querySelectorAll('[data-flow-action]').forEach(function (button) {
    button.addEventListener('click', function () { act(button.dataset.flowAction); });
  });

  // dagre orders each level to cross as few edges as possible. Put it in a fixed, symmetric order
  // instead: the nodes that come from the same node together, in the order of the registry, and
  // mirrored on the left half of the level (Assembly + Annotation · Illumina, Assembly · Illumina,
  // Assembly · ONT, Assembly + Annotation · ONT). The level stays centred where dagre put it.
  function orderLevels() {
    const levels = {};
    cy.nodes().forEach(function (node) {
      const y = Math.round(node.position('y'));
      (levels[y] = levels[y] || []).push(node);
    });
    Object.values(levels).forEach(function (nodes) {
      if (nodes.length < 2) {
        return;
      }
      const left = Math.min.apply(null, nodes.map(function (node) { return node.position('x') - node.width() / 2; }));
      const right = Math.max.apply(null, nodes.map(function (node) { return node.position('x') + node.width() / 2; }));
      const total = nodes.reduce(function (sum, node) { return sum + node.width(); }, NODE_SEP * (nodes.length - 1));
      let x = (left + right) / 2 - total / 2;
      symmetricOrder(nodes).forEach(function (node) {
        node.position('x', x + node.width() / 2);
        x += node.width() + NODE_SEP;
      });
    });
  }

  function symmetricOrder(nodes) {
    const groups = {};
    nodes.forEach(function (node) {
      const parents = node.incomers('node').map(function (parent) { return parent.data('order'); });
      const key = parents.length ? Math.min.apply(null, parents) : node.data('order');
      (groups[key] = groups[key] || []).push(node);
    });
    const ordered = Object.keys(groups).map(Number).sort(function (a, b) { return a - b; }).map(function (key) {
      return groups[key].sort(function (a, b) { return a.data('order') - b.data('order'); });
    });
    return ordered.reduce(function (all, group, index) {
      return all.concat(index < Math.floor(ordered.length / 2) ? group.slice().reverse() : group);
    }, []);
  }

  // Highlight a node with everything that leads to it and everything it leads to

  function focus(node) {
    const related = node.predecessors().union(node.successors()).union(node);
    cy.elements().addClass('faded').removeClass('focused');
    related.removeClass('faded');
    node.addClass('focused');
    showDetails(node);
  }

  function clearFocus() {
    cy.elements().removeClass('faded focused');
    details.replaceChildren(element('p', 'text-base-content/70', 'Select a box in the graph to see its details.'));
  }

  function act(action) {
    const center = { x: container.clientWidth / 2, y: container.clientHeight / 2 };
    if (action === 'zoom-in' || action === 'zoom-out') {
      cy.zoom({ level: cy.zoom() * (action === 'zoom-in' ? 1.25 : 0.8), renderedPosition: center });
    } else if (action === 'fit') {
      cy.fit(undefined, 24);
    } else if (action === 'png') {
      const link = document.createElement('a');
      link.href = cy.png({ full: true, scale: 4, bg: colors.page });
      link.download = sampleMode ? 'cocos-sample-data-flow.png' : 'cocos-data-flow.png';
      link.click();
    }
  }

  // State of the sample (sample mode)

  function stateClass(data) {
    if (data.type === 'data') {
      return data.files.length ? 'available' : 'absent';
    }
    if (data.type === 'step') {
      return { completed: 'done', running: 'in-progress', pending: 'in-progress', failed: 'failed', planned: 'planned', unused: 'absent' }[data.state];
    }
    return { ready: 'ready', reachable: 'planned', incompatible: 'absent' }[data.compatibility];
  }

  function stateBadge(node) {
    const data = node.data();
    let state;
    if (data.type === 'step') {
      state = STEP_STATES[data.state];
    } else if (data.type === 'model') {
      state = MODEL_STATES[data.compatibility];
    } else {
      const planned = node.hasClass('planned');
      state = data.files.length ? ['This sample has it', 'badge-success']
        : planned ? ['The preparation of a model would produce it', 'badge-primary'] : ['This sample does not have it', 'badge-ghost'];
    }
    return element('span', 'badge badge-sm ' + state[1], state[0]);
  }

  function stateSections(node) {
    const data = node.data();
    if (data.type === 'data') {
      return [linkList('Files of this sample', data.files.map(function (id) { return files[id]; }).filter(Boolean))];
    }
    if (data.type === 'step') {
      return [textList('Would prepare', data.for_models)];
    }
    const preparation = cy.nodes('[type = "step"]').filter(function (step) {
      return step.data('state') === 'planned' && step.data('for_models').indexOf(data.identifier) !== -1;
    }).map(function (step) { return step.data('label'); });
    return [
      textList('Preparation it needs', preparation),
      textList('Why not', data.reasons),
      textList('Prediction', data.run ? [RUN_STATES[data.run]] : []),
    ];
  }

  // Details panel

  function showDetails(node) {
    const data = node.data();
    const header = element('div', 'flex flex-wrap items-center gap-x-3 gap-y-1 mb-3');
    header.appendChild(element('span', 'badge badge-sm badge-soft ' + (data.type === 'data' ? 'badge-neutral' : data.type === 'step' ? 'badge-primary' : 'badge-secondary'), TYPE_LABELS[data.type]));
    header.appendChild(element('h3', 'text-base font-semibold break-words', data.label));
    if (sampleMode) {
      header.appendChild(stateBadge(node));
    }
    let sections;

    if (data.type === 'data') {
      header.appendChild(element('span', 'text-base-content/70', data.detail));
      sections = [list('Produced by', node.incomers('node')), list('Used by', node.outgoers('node')), termLinks(data.terms)];
    } else {
      const link = element('a', 'btn btn-sm btn-outline btn-primary ml-auto');
      link.href = data.url;
      link.appendChild(element('i', 'bi bi-box-arrow-up-right'));
      link.appendChild(document.createTextNode('Open its page'));
      header.appendChild(link);
      sections = [list('Needs', node.incomers('node')), list('Produces', node.outgoers('node'))];
      if (data.type === 'model') {
        sections.push(textList('Antibiotics', data.antibiotics), textList('Organisms', data.organisms));
      } else if (data.web_service) {
        sections.push(textList('Runs in', ['Bioinformatics service, as a job']));
      }
    }
    if (sampleMode) {
      sections = stateSections(node).concat(sections);
    }

    const grid = element('div', 'flex flex-wrap justify-center gap-x-16 gap-y-4');
    sections.filter(Boolean).forEach(function (section) { grid.appendChild(section); });
    const children = [header];
    if (data.description) {
      children.push(element('p', 'text-base-content/80 mb-3', data.description));
    }
    children.push(grid);
    details.replaceChildren.apply(details, children);
  }

  function list(title, nodes) {
    const labels = nodes.map(function (other) {
      const data = other.data();
      return data.type === 'data' ? data.label + ' (' + data.detail + ')' : data.label;
    });
    return textList(title, labels.length ? labels : ['Nothing in the registry']);
  }

  function textList(title, items) {
    if (!items || !items.length) {
      return null;
    }
    const section = element('div', 'space-y-1');
    section.appendChild(element('p', 'font-semibold', title));
    const ul = element('ul', 'list-disc pl-5 text-base-content/80');
    items.forEach(function (item) { ul.appendChild(element('li', '', item)); });
    section.appendChild(ul);
    return section;
  }

  function linkList(title, links) {
    if (!links.length) {
      return null;
    }
    const section = element('div', 'space-y-1');
    section.appendChild(element('p', 'font-semibold', title));
    links.forEach(function (target) {
      const link = element('a', 'link link-primary block break-all', target.name);
      link.href = target.url;
      section.appendChild(link);
    });
    return section;
  }

  function termLinks(terms) {
    return linkList('Ontology terms', terms.map(function (term) { return { name: term.label, url: term.url }; }));
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined) {
      node.textContent = text;
    }
    return node;
  }

  // Style

  function graphStyle() {
    return [
      {
        selector: 'node',
        style: {
          'label': 'data(label)',
          'font-family': fontFamily,
          'font-size': FONT_SIZE,
          'text-valign': 'center',
          'text-halign': 'center',
          'text-wrap': 'wrap',
          'shape': 'round-rectangle',
          'width': function (node) { return textWidth(nodeText(node)) + 28; },
          'height': function (node) { return node.data('type') === 'data' ? 44 : 34; },
          'border-width': 1,
          'transition-property': 'opacity',
          'transition-duration': 150,
        },
      },
      {
        selector: 'node[type = "data"]',
        style: {
          'label': function (node) { return nodeText(node); },
          'background-color': colors.data,
          'border-color': colors.text,
          'border-opacity': 0.5,
          'border-style': 'dashed',
          'color': colors.text,
        },
      },
      {
        selector: 'node[type = "step"]',
        style: { 'background-color': colors.step, 'border-color': colors.step, 'color': colors.stepText },
      },
      {
        selector: 'node[type = "model"]',
        style: { 'background-color': colors.model, 'border-color': colors.model, 'color': colors.modelText, 'font-weight': 'bold' },
      },
      {
        selector: 'edge',
        style: {
          'width': 1.5,
          'curve-style': 'bezier',
          'line-color': colors.line,
          'line-opacity': 0.55,
          'target-arrow-shape': 'triangle',
          'target-arrow-color': colors.line,
          'arrow-scale': 0.9,
          'label': 'data(label)',
          'font-family': fontFamily,
          'font-size': FONT_SIZE - 2,
          'color': colors.text,
          'text-background-color': colors.page,
          'text-background-opacity': 1,
          'text-background-padding': 2,
          'transition-property': 'opacity',
          'transition-duration': 150,
        },
      },
      // State of a sample
      { selector: 'node.available', style: { 'border-style': 'solid', 'border-width': 2, 'border-color': colors.step, 'border-opacity': 1 } },
      { selector: 'node[type = "data"].planned', style: { 'border-width': 2, 'border-color': colors.step, 'border-opacity': 1, 'background-color': colors.page } },
      { selector: 'node.in-progress', style: { 'background-color': colors.warning, 'border-color': colors.warning, 'color': colors.warningText } },
      { selector: 'node.failed', style: { 'background-color': colors.error, 'border-color': colors.error, 'color': colors.errorText } },
      { selector: 'node[type = "step"].planned', style: { 'background-color': colors.page, 'border-color': colors.step, 'border-width': 2, 'border-style': 'dashed', 'color': colors.step } },
      { selector: 'node[type = "model"].planned', style: { 'background-color': colors.page, 'border-color': colors.model, 'border-width': 2, 'border-style': 'dashed', 'color': colors.model } },
      { selector: '.absent', style: { 'opacity': 0.3 } },
      // Selection
      { selector: '.faded', style: { 'opacity': 0.12 } },
      {
        selector: 'node.focused',
        style: {
          'opacity': 1,
          'border-width': 2,
          'border-color': colors.accent,
          'border-opacity': 1,
          'underlay-color': colors.accent,
          'underlay-opacity': 0.3,
          'underlay-padding': 6,
          'underlay-shape': 'round-rectangle',
        },
      },
    ];
  }

  function nodeText(node) {
    const data = node.data();
    return data.type === 'data' ? data.label + '\n' + data.detail : data.label;
  }

  function textWidth(text) {
    const context = textWidth.context || (textWidth.context = document.createElement('canvas').getContext('2d'));
    context.font = FONT_SIZE + 'px ' + fontFamily;
    return Math.max.apply(null, text.split('\n').map(function (line) { return context.measureText(line).width; }));
  }

  // Cytoscape does not understand the oklch() colours of the theme: convert them to rgb() on a canvas
  function themeColor(variable, fallback) {
    const value = getComputedStyle(document.body).getPropertyValue(variable).trim();
    if (!value) {
      return fallback;
    }
    const context = document.createElement('canvas').getContext('2d', { willReadFrequently: true });
    context.fillStyle = fallback;
    context.fillStyle = value;  // ignored if the browser cannot parse it
    context.fillRect(0, 0, 1, 1);
    const pixel = context.getImageData(0, 0, 1, 1).data;
    return 'rgb(' + pixel[0] + ', ' + pixel[1] + ', ' + pixel[2] + ')';
  }
});
