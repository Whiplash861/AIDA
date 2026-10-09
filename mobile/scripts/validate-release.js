// Release bundles must never contain development or legacy public bearer tokens.
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const forbidden = ['EXPO_PUBLIC_AIDA_DEV_GATEWAY_URL', 'EXPO_PUBLIC_AIDA_DEV_GATEWAY_TOKEN', 'EXPO_PUBLIC_AIDA_PAIRING_TOKEN'];
function validateRelease(env = process.env, directory = root) {
  if (env.EAS_BUILD_PROFILE === 'development') return;
  for (const key of forbidden) if ((env[key] || '').trim()) throw new Error('Release blocked: remove public development credentials before building.');
  for (const name of ['.env', '.env.local', '.env.production', '.env.production.local']) {
    const file = path.join(directory, name);
    if (!fs.existsSync(file)) continue;
    const text = fs.readFileSync(file, 'utf8');
    if (text.split(/\r?\n/).some(line => forbidden.some(key => new RegExp('^\\s*(?:export\\s+)?' + key + '\\s*=\\s*[^\\s#]').test(line)))) {
      throw new Error('Release blocked: a local dotenv file defines public development credentials.');
    }
  }
}
if (require.main === module) validateRelease();
module.exports = { validateRelease };
