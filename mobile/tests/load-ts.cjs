const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
function loader(mocks = {}, globals = {}, transform = (_file, source) => source) {
  const cache = new Map();
  function load(name, parent = root) {
    if (Object.hasOwn(mocks, name)) return mocks[name];
    if (name.endsWith('.wav')) return name;
    let file = name.startsWith('@/') ? path.join(root, name.slice(2)) : path.resolve(parent, name);
    if (!path.extname(file)) file += '.ts';
    if (cache.has(file)) return cache.get(file).exports;
    const source = transform(file, fs.readFileSync(file, 'utf8'));
    const result = ts.transpileModule(source, {fileName: file, reportDiagnostics: true, compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX}});
    const diagnostics = result.diagnostics?.filter(item => item.category === ts.DiagnosticCategory.Error) || [];
    if (diagnostics.length) throw new Error(ts.formatDiagnosticsWithColorAndContext(diagnostics, {getCanonicalFileName: f => f, getCurrentDirectory: () => root, getNewLine: () => '\n'}));
    const module = {exports: {}};
    cache.set(file, module);
    vm.runInNewContext(result.outputText, {module, exports: module.exports, require: dep => load(dep, path.dirname(file)), console, URL, AbortController, setTimeout, clearTimeout, setImmediate, process: {env: {}}, __DEV__: false, ...globals}, {filename: file});
    return module.exports;
  }
  return name => load(name);
}
module.exports = {loader, root};
