// Metro selects local-kv.web.ts for browsers, avoiding native SQLite initialization.
import Storage from 'expo-sqlite/kv-store';
export default Storage;
