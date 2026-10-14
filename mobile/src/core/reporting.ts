/** Presentation only: never use these labels to route commands or assess risk. */
export function renderReport(title: string, found: readonly string[], unknown: readonly string[], next: readonly string[]): string {
  const section = (heading: string, entries: readonly string[]) => [heading, ...entries.map(text => `- ${text}`)].join('\n');
  return [title, section('What AIDA found', found), section('What remains unknown', unknown), section('What to do next', next)].join('\n\n');
}

export function displayStatus(value: string): string {
  const labels: Record<string, string> = {
    STAGED: 'Not available yet', LIMITED: 'Some checks available', SUPPORTED: 'Available',
    READY: 'Ready', IDLE: 'Ready', STANDBY: 'Ready', STARTING: 'Starting', LOADING: 'Loading',
    ACTIVE: 'In progress', ANALYZING: 'Reviewing', PROCESSING: 'Processing', LISTENING: 'Listening',
    SPEAKING: 'Speaking', TESTING: 'Testing audio', MUTED: 'Muted',
    WARNING: 'Needs review', ATTENTION: 'Needs review', ERROR: 'Could not complete',
    DEGRADED: 'Some checks unavailable', OFFLINE: 'Offline', STOPPED: 'Stopped', SHUTDOWN: 'Stopped',
    ELEVATED: 'Needs investigation', THREAT_CONFIRMED: 'Threat confirmed', OBSERVING: 'Observing', INVESTIGATING: 'Investigating',
    '0 ACTIVE': 'No active tasks', FOUNDATION: 'Basic storage', PROTECTED: 'Approval required',
    ANDROID: 'Android', IOS: 'iOS', WEB: 'Web', WIFI: 'Wi-Fi', CELLULAR: 'Mobile data',
    ETHERNET: 'Ethernet', UNKNOWN: 'Unknown', NONE: 'None reported',
  };
  return labels[value.toUpperCase()] ?? value;
}

export function unavailableReport(engine: string, capability: string, platform: string): string {
  return renderReport(`${engine}: requested feature unavailable`,
    [`AIDA recognized your request for ${capability}. No operation was executed.`],
    [`This feature is not available in the ${platform} app. AIDA did not collect results or change device settings for this request.`],
    ['Open Systems to see which checks are available on this device. If you use AIDA on another device, review its capabilities there before requesting the check.']);
}

export function activityCategory(value: string): string {
  const labels: Record<string, string> = {GATEWAY: 'Service connection', RUNTIME: 'AIDA session', STORAGE: 'Saved information',
    SPEECH: 'Voice output', VOICE: 'Voice input', DIRECTIVE: 'Your request', COMMAND: 'Local check', BRAIN: 'Reasoning service', AIDA: 'AIDA'};
  return labels[value] ?? value;
}
