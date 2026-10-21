// Copies the browser builds of the JavaScript dependencies from node_modules to static/vendor/,
// which is not versioned (run by `npm run build:vendor`).
const fs = require('fs');
const path = require('path');

const FILES = {
  'cytoscape.min.js': 'cytoscape/dist/cytoscape.min.js',
  'cytoscape-dagre.min.js': 'cytoscape-dagre/dist/cytoscape-dagre.min.js',
};

const root = path.join(__dirname, '..');
const target = path.join(root, 'static', 'vendor');
fs.mkdirSync(target, { recursive: true });
for (const [name, source] of Object.entries(FILES)) {
  fs.copyFileSync(path.join(root, 'node_modules', source), path.join(target, name));
}
