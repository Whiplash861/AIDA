const fs = require('fs');
const path = require('path');

const repositoryRoot = path.resolve(__dirname, '..', '..');
const sourceDirectory = path.join(repositoryRoot, 'assets', 'sounds');
const destinationDirectory = path.resolve(__dirname, '..', 'assets', 'sounds');
const files = ['aida_start.wav', 'aida_end.wav'];

fs.mkdirSync(destinationDirectory, { recursive: true });

for (const fileName of files) {
  const source = path.join(sourceDirectory, fileName);
  const destination = path.join(destinationDirectory, fileName);
  if (!fs.existsSync(source)) {
    throw new Error(`Canonical AIDA sound asset not found: ${source}`);
  }
  fs.copyFileSync(source, destination);
}

console.log('AIDA mobile audio assets synchronized from repository source.');
