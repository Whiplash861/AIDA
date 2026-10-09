const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {loader, root} = require('./load-ts.cjs');

test('operation ownership rejects overlap and stale completion cannot release replacement', () => {
  const {OperationCoordinator} = loader()('@/src/core/runtime/operation-coordinator');
  const operations = new OperationCoordinator();
  const first = operations.acquire('voice');
  assert.throws(() => operations.acquire('voice'), /already/);
  operations.cancel();
  assert.equal(first.signal.aborted, true);
  const next = operations.acquire('directive');
  operations.release(first);
  assert.equal(operations.current.id, next.id);
  operations.release(next);
  assert.equal(operations.current, null);
});

test('offline routing recognizes supported diagnostics and excludes quoted/negated requests', () => {
  const {resolveLocalDirective: route} = loader()('@/src/core/reasoning/local-router');
  for (const [input, command] of [['run a quick scan', 'QUICKSCAN'], ['performance scan', 'PERFORMANCE_SCAN'], ['check security status', 'SECURITY_STATUS'], ['run surface security scan', 'SECURITY_SURFACE_SCAN'], ['show last diagnostic', 'DIAGNOSTIC_LAST']]) {
    assert.equal(route(input).commandType, command);
    assert.equal(route(input).localOnly, true);
  }
  for (const input of ['Do not run a quick scan', '"run a quick scan"', 'What does run a quick scan do?', 'If I run a quick scan, what happens?']) assert.equal(route(input), null);
  assert.equal(route('remember my private note').commandType, 'MOBILE_UNAVAILABLE');
});

function storageHarness(platform = 'android') {
  const secure = new Map(), local = new Map();
  let fail = false;
  const load = loader({
    'react-native': {Platform: {OS: platform}},
    'expo-secure-store': {getItemAsync: async k => secure.get(k) ?? null, setItemAsync: async (k,v) => {if (fail) throw new Error('disk failed'); secure.set(k,v);}, deleteItemAsync: async k => secure.delete(k)},
    '@/src/core/storage/local-kv': {default: {getItem: async k => local.get(k) ?? null, setItem: async (k,v) => local.set(k,v), removeItem: async k => local.delete(k)}, __esModule: true},
  }, {localStorage: {getItem: k => local.get(k) ?? null, setItem: (k,v) => local.set(k,v)}});
  return {storage: load('@/src/core/storage/mobile-storage'), secure, local, fail: () => {fail = true;}};
}
test('enrollment is stored as one endpoint-token envelope and failed replacement preserves both', async () => {
  const h = storageHarness();
  const old = {version: 2, baseUrl: 'https://old.example', token: 'old-token', deviceId: 'device', expiresAt: 9999999999};
  await h.storage.saveGatewayEnrollment(old);
  h.fail();
  await assert.rejects(h.storage.saveGatewayEnrollment({...old, baseUrl: 'https://new.example', token: 'new-token'}));
  assert.deepEqual(JSON.parse(JSON.stringify(await h.storage.loadGatewayEnrollment())), old);
  assert.equal(h.secure.size, 1);
});
test('browser enrollment never writes bearer credentials to persistent storage', async () => {
  const h = storageHarness('web');
  await h.storage.saveGatewayEnrollment({version: 2, baseUrl: 'https://example', token: 'private-token', deviceId: 'device', expiresAt: 9999999999});
  assert.equal(h.secure.size + h.local.size, 0);
  assert.equal((await h.storage.loadGatewayEnrollment()).token, 'private-token');
});
test('malformed persisted activity and settings cannot poison runtime hydration', async () => {
  const h = storageHarness();
  h.local.set('aida.mobile.activity.v1', '[{"id":1},null,{"id":"a","category":"X","message":"ok","severity":"info","source":"test","created_at":"today"}]');
  h.local.set('aida.mobile.runtime-state.v1', '{"speech_enabled":"yes","autonomy_enabled":"true"}');
  assert.equal((await h.storage.loadActivity()).length, 1);
  assert.equal((await h.storage.loadRuntimeState()).autonomy_enabled, false);
});
test('evidence writes serialize and retain a bounded local history', async () => {
  const h = storageHarness();
  await Promise.all(Array.from({length: 35}, (_,i) => h.storage.saveEvidence({id: String(i), capturedAt: new Date().toISOString(), platform: 'android', kind: 'diagnostic', observations: {value:i}, gaps: [], transcript:'result'})));
  const entries = await h.storage.loadEvidence();
  assert.equal(entries.length, 30);
  assert.equal(entries[0].id, '34');
});

test('release rejects development credentials and enrollment requires HTTPS', async () => {
  const load = loader({'@/src/core/storage/mobile-storage': {loadGatewayEnrollment: async () => null, loadLegacyGateway: async () => null}}, {process: {env: {EXPO_PUBLIC_AIDA_DEV_GATEWAY_TOKEN: 'secret'}}});
  const config = load('@/src/core/services/gateway-config');
  await assert.rejects(config.loadGatewayConfiguration(), /forbidden/);
  assert.throws(() => config.validateGatewayUrl('http://gateway.local'), /HTTPS/);
  assert.throws(() => config.validateGatewayUrl('https://user:pass@gateway.local'), /credentials/);
});

test('gateway request sanitizes remote errors and cancellation settles promptly', async () => {
  const config = {baseUrl: 'https://example', token: 'token', source: 'enrolled'};
  const request = loader({}, {fetch: async () => ({ok: false, status: 503, json: async () => ({detail: 'SECRET'})})})('@/src/core/services/gateway-request').gatewayRequest;
  await assert.rejects(request(config, '/v1/ready'), error => !error.message.includes('SECRET') && error.message.includes('unavailable'));
  const abort = new AbortController();
  const pendingRequest = loader({}, {fetch: (_url, options) => new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(new Error('native-private-url'))))})('@/src/core/services/gateway-request').gatewayRequest;
  const pending = pendingRequest(config, '/v1/ready', undefined, {signal: abort.signal});
  abort.abort();
  await assert.rejects(pending, /cancelled/);
});

test('mobile service routes device operations before touching unavailable gateway', async () => {
  let gatewayReads = 0;
  const load = loader({
    '@/src/core/reasoning/local-provider': {LocalRuntimeReasoningProvider: class {id='local'; async respond(){return {text:'offline', mode:'local_fallback', provider:'local'};}}},
    '@/src/core/services/gateway-config': {loadGatewayConfiguration: async () => {gatewayReads++; throw new Error('offline');}},
    '@/src/core/storage/mobile-storage': {},
  });
  const service = new (load('@/src/core/reasoning/service').MobileReasoningService)();
  const result = await service.respond('run a quick scan', {});
  assert.equal(result.mode, 'routed');
  assert.equal(gatewayReads, 0);
});
test('mobile service retries failed initialization on explicit refresh', async () => {
  let online = false, probes = 0;
  const load = loader({
    '@/src/core/reasoning/local-provider': {LocalRuntimeReasoningProvider: class {id='local';}},
    '@/src/core/services/gateway-config': {loadGatewayConfiguration: async () => ({baseUrl:'https://example', token:'session', kind:'session', source:'enrolled'})},
    '@/src/core/services/gateway-request': {gatewayRequest: async () => {probes++; if (!online) throw new Error('offline'); return {protocol_version:2, reasoning_configured:true, speech_configured:true, transcription_configured:true};}},
    '@/src/core/storage/mobile-storage': {},
  });
  const service = new (load('@/src/core/reasoning/service').MobileReasoningService)();
  await service.initialize();
  assert.equal(service.isRemoteConfigured(), false);
  online = true;
  await service.initialize(true);
  assert.equal(service.isRemoteConfigured(), true);
  assert.equal(probes, 2);
});

test('confirmation-required and unsupported-platform commands never call Android provider', async () => {
  let calls = 0;
  const load = loader({
    '@/src/core/diagnostics/android-core-diagnostics': {executeAndroidCoreDiagnostic: async () => {calls++;}},
    '@/src/core/engines/registry': {executeEngineDirective: async () => null},
    '@/src/core/storage/mobile-storage': {loadEvidence: async () => []},
  });
  const execute = load('@/src/core/commands/mobile-command-executor').executeMobileRoutedDirective;
  assert.equal((await execute({commandType:'QUICKSCAN', requiresConfirmation:true}, {platform:'Android'})).executed, false);
  assert.equal((await execute({commandType:'QUICKSCAN', localOnly:true}, {platform:'iOS'})).executed, false);
  assert.equal(calls, 0);
});

test('speech mute cancels active player and queued utterance without waiting for watchdog', async () => {
  let players = 0, removed = 0, done = 0;
  const load = loader({
    'expo-audio': {setAudioModeAsync: async () => {}, createAudioPlayer: () => {players++; return {addListener: () => ({remove(){}}), play(){}, pause(){}, remove(){removed++;}};}},
    'expo-file-system/legacy': {},
    '@/src/core/services/gateway-config': {loadGatewayConfiguration: async () => ({})},
  });
  const speech = load('@/src/core/interaction/speech-output');
  const first = speech.speakAidaText('first', {onDone: () => done++});
  const second = speech.speakAidaText('second');
  await new Promise(resolve => setImmediate(resolve));
  await speech.stopAidaSpeech();
  assert.equal(await first, 'cancelled');
  assert.equal(await second, 'cancelled');
  assert.equal(players, 1);
  assert.equal(removed, 1);
  assert.equal(done, 1);
});

test('audio mode failure always settles speech lifecycle', async () => {
  let done = 0, errors = 0;
  const speech = loader({
    'expo-audio': {setAudioModeAsync: async () => {throw new Error('native SECRET');}},
    'expo-file-system/legacy': {},
    '@/src/core/services/gateway-config': {},
  })('@/src/core/interaction/speech-output');
  assert.equal(await speech.speakAidaText('hello', {onDone: () => done++, onError: message => {assert.equal(message.includes('SECRET'), false); errors++;}}), 'silent');
  assert.equal(done, 1);
  assert.equal(errors, 1);
});

test('release validator rejects dotenv credentials without disclosing values', () => {
  const {validateRelease} = require('../scripts/validate-release');
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'aida-release-test-'));
  try {
    fs.writeFileSync(path.join(directory, '.env.local'), 'EXPO_PUBLIC_AIDA_DEV_GATEWAY_TOKEN=SECRET_VALUE\n');
    assert.throws(() => validateRelease({}, directory), error => error.message.includes('blocked') && !error.message.includes('SECRET_VALUE'));
    assert.doesNotThrow(() => validateRelease({EAS_BUILD_PROFILE:'development'}, directory));
  } finally { fs.rmSync(directory, {recursive: true}); }
});

function runtimeHarness(options = {}) {
  let resolveReply;
  let calls = 0;
  const reply = new Promise(resolve => resolveReply = resolve);
  const load = loader({
    'expo-constants': {default: {expoConfig:{version:'test'}}, __esModule:true},
    'react-native': {Platform:{OS:'android', Version:36, constants:{Model:'test'}}},
    '@/src/core/engines/aegis/runtime': {MOBILE_AEGIS:{restoreObservation(){}}},
    '@/src/core/commands/mobile-command-executor': {executeMobileRoutedDirective: async () => ({transcriptText:'local',speechText:'local',includeInContext:false,executed:true})},
    '@/src/core/interaction/speech-output': {cleanupAidaSpeechCache: async()=>{}, stopAidaSpeech: async()=>{}, speakAidaText: options.speakAidaText ?? (async()=> 'silent'), testAidaSpeech: options.testAidaSpeech ?? (async()=> 'silent')},
    '@/src/core/reasoning/service': {MOBILE_REASONING:{initialize:async()=>{}, isRemoteConfigured:()=>true, gatewayRuntimeState:()=>({reasoningConfigured:true,speechConfigured:true,transcriptionConfigured:true,source:'enrolled'}),respond:()=>{calls++;return reply;}}},
    '@/src/core/storage/mobile-storage': {loadOrCreateInstanceId:async()=>({instanceId:'test',created:false}),loadRuntimeState:async()=>({speech_enabled:true,autonomy_enabled:false}),loadActivity:async()=>[],loadEvidence:async()=>[],saveActivity:options.saveActivity ?? (async()=>{}),saveRuntimeState:options.saveRuntimeState ?? (async()=>{}),saveEvidence:async()=>{}},
  });
  return {runtime:load('@/src/core/runtime/aida-runtime'), resolve:resolveReply, calls:()=>calls};
}
test('muting during a Brain request does not release its operation or change status to standby', async () => {
  const h = runtimeHarness();
  await h.runtime.initializeAidaRuntime();
  const request = h.runtime.submitLocalDirective('question');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.runtime.getRuntimeSnapshot().status,'ANALYZING');
  await h.runtime.setSpeechEnabled(false);
  assert.equal(h.runtime.getRuntimeSnapshot().status,'ANALYZING');
  await assert.rejects(h.runtime.submitLocalDirective('duplicate'), /already/);
  assert.equal(h.calls(),1);
  h.resolve({text:'answer',provider:'fake',mode:'remote'});
  await request;
  assert.equal(h.runtime.getRuntimeSnapshot().status,'STANDBY');
});
test('late voice cleanup cannot release a replacement capture lease', async () => {
  const h = runtimeHarness();
  await h.runtime.initializeAidaRuntime();
  const first = h.runtime.reserveVoiceInput();
  h.runtime.cancelRuntimeOperation();
  const second = h.runtime.reserveVoiceInput();
  await h.runtime.failVoiceInput('old capture', first);
  assert.throws(()=>h.runtime.reserveVoiceInput(), /already/);
  await h.runtime.completeVoiceInput(second);
  const third = h.runtime.reserveVoiceInput();
  assert.equal(third.aborted,false);
  h.runtime.cancelRuntimeOperation();
});

function homeHarness(options = {}) {
  let capture, stateCursor=0, refCursor=0;
  const states=[], refs=[];
  let permissionResolve, prepared=0, recorded=0, stopped=0, discarded=0, submitted=0;
  const audioModes=[], discardedUris=[];
  let directiveResolve, directiveReject;
  const permission = new Promise(resolve=>permissionResolve=resolve);
  const directive = new Promise((resolve,reject)=>{directiveResolve=resolve;directiveReject=reject;});
  let controller;
  const runtime = {status:'STANDBY',platform:'Android',platform_version:'36',runtime_mode:'standalone',capabilities:[{id:'voice.input',state:'supported'}]};
  const recorder = {uri:'file:///temporary-test.m4a',prepareToRecordAsync:async()=>{prepared++;recorder.uri='file:///temporary-'+prepared+'.m4a';},record:options=>{assert.equal(options.forDuration,120);recorded++;},stop:async()=>{stopped++;}};
  const react = {
    useState(initial) {const index=stateCursor++; if (!(index in states)) states[index]=typeof initial==='function'?initial():initial; return [states[index],next=>{states[index]=typeof next==='function'?next(states[index]):next;}];},
    useRef(initial) {const index=refCursor++; return refs[index]??(refs[index]={current:initial});},
    useCallback: fn=>fn, useMemo:fn=>fn(), useEffect:()=>{},
  };
  const load = loader({
    react,
    'react/jsx-runtime': {jsx:()=>null,jsxs:()=>null},
    'expo-constants': {default:{expoConfig:{version:'test'}},__esModule:true},
    'expo-router': {useFocusEffect:()=>{}},
    'expo-status-bar': {StatusBar:()=>null},
    'expo-audio': {AudioModule:{requestRecordingPermissionsAsync:()=>permission},RecordingPresets:{HIGH_QUALITY:{}},setAudioModeAsync:async mode=>{audioModes.push(mode);},useAudioRecorder:()=>recorder,useAudioRecorderState:()=>({durationMillis:0})},
    'react-native': {Platform:{OS:'android',Version:36},StyleSheet:{create:value=>value},Keyboard:{},AppState:{},Text:()=>null},
    'react-native-safe-area-context': {SafeAreaView:()=>null},
    '@/src/components/aida-orb': {AidaOrb:()=>null},
    '@/src/components/glass-panel': {GlassPanel:()=>null},
    '@/src/components/message-card': {MessageCard:()=>null},
    '@/src/core/perception/intake': options.intake ?? {},
    '@/src/core/storage/mobile-storage': {saveEvidence:options.saveEvidence ?? (async()=>{})},
    '@/src/core/interaction/transcription-client': {discardAidaRecording:async uri=>{if(uri){discarded++;discardedUris.push(uri);}},transcribeAidaRecording:options.transcribe ?? (async()=> 'quickscan')},
    '@/src/core/runtime/aida-runtime': {
      getRuntimeSnapshot:()=>runtime, subscribeRuntime:()=>()=>{}, refreshServicesGateway:async()=>{},
      reserveVoiceInput:()=>{controller=new AbortController();return controller.signal;},
      cancelRuntimeOperation:()=>controller?.abort(), beginVoiceListening:async()=>{},beginVoiceProcessing:async()=>{},completeVoiceInput:async()=>{},failVoiceInput:async()=>{},
      submitLocalDirective:()=>{submitted++;return directive;},
    },
    '@/src/theme/aida-theme': {AIDA_COLORS:{},AIDA_FONTS:{},AIDA_RADIUS:{},AIDA_SPACING:{},AIDA_STATUS_TONES:{STANDBY:{foreground:'blue'}}},
  }, {__capture:value=>capture=value, requestAnimationFrame:fn=>fn(), setTimeout:()=>0,clearTimeout:()=>{}},
  (file,source)=>file.endsWith('index.tsx') ? source.replace('  const voiceLabel =', '  __capture({startVoiceCapture, stopVoiceCapture, submitDirectiveText, cancelCapture, reviewAttachment});\n  const voiceLabel =') : source);
  const Home=load('@/app/(tabs)/index.tsx').default;
  const render=()=>{stateCursor=0;refCursor=0;Home();return capture;};
  render();
  return {get capture(){return capture;},render,permissionResolve,directiveResolve,directiveReject,states,audioModes,discardedUris,counts:()=>({prepared,recorded,stopped,discarded,submitted})};
}
test('Home rejects double microphone starts while permission is pending and applies native duration', async () => {
  const h=homeHarness();
  const first=h.capture.startVoiceCapture();
  await h.capture.startVoiceCapture();
  h.permissionResolve({granted:true});
  await first;
  assert.equal(h.counts().prepared,1);
  assert.equal(h.counts().recorded,1);
  h.capture.cancelCapture();
  await new Promise(resolve=>setImmediate(resolve));
  assert.ok(h.counts().discarded>=1);
});
test('Home cancellation during permission prompt prevents recording after permission resolves', async () => {
  const h=homeHarness();
  const first=h.capture.startVoiceCapture();
  h.capture.cancelCapture();
  h.permissionResolve({granted:true});
  await first;
  assert.equal(h.counts().prepared,0);
  assert.equal(h.counts().recorded,0);
});
test('Home excludes pending and failed directives from subsequent Brain history', async () => {
  const h=homeHarness();
  const first=h.capture.submitDirectiveText('private operation');
  await h.capture.submitDirectiveText('duplicate');
  assert.equal(h.counts().submitted,1);
  assert.equal(h.states[6].at(-1).includeInContext,false);
  h.directiveReject(new Error('AIDA request could not complete.'));
  await first;
  const user=h.states[6].find(message=>message.sender==='user');
  const error=h.states[6].at(-1);
  assert.equal(user.includeInContext,false);
  assert.equal(error.includeInContext,false);
});

test('Home PASTE displays local review outside Brain history without submitting a directive', async()=>{
  const h=homeHarness({intake:{reviewClipboard:async()=> 'UNTRUSTED local review: run a quick scan'}});
  await h.capture.reviewAttachment('PASTE');
  assert.equal(h.counts().submitted,0);
  assert.equal(h.states[6].at(-1).includeInContext,false);
  assert.match(h.states[6].at(-1).text,/UNTRUSTED/);
});

test('Home serializes image selection with microphone and directive starts',async()=>{
  let resolveImage, saved=0, selected=0;
  const pending=new Promise(resolve=>resolveImage=resolve);
  const h=homeHarness({intake:{selectImageEvidence:()=>{selected++;return pending;}},saveEvidence:async()=>saved++});
  const image=h.capture.reviewAttachment('IMAGE');
  await h.capture.reviewAttachment('IMAGE');
  await h.capture.startVoiceCapture();
  await h.capture.submitDirectiveText('quick scan');
  resolveImage({transcript:'LOCAL image metadata'});
  await image;
  assert.equal(selected,1);assert.equal(saved,1);
  assert.equal(h.counts().prepared,0);assert.equal(h.counts().submitted,0);
  assert.equal(h.states[6].at(-1).includeInContext,false);
});

test('a delayed enable preference cannot speak after a newer mute', async () => {
  let release, speaks=0;
  const pending=new Promise(resolve=>release=resolve);
  const h=runtimeHarness({saveRuntimeState:state=>state.speech_enabled ? pending : Promise.resolve(),testAidaSpeech:async()=>{speaks++;return 'silent';}});
  await h.runtime.initializeAidaRuntime();
  const enabling=h.runtime.setSpeechEnabled(true);
  await new Promise(resolve=>setImmediate(resolve));
  await h.runtime.setSpeechEnabled(false);
  release();
  await enabling;
  assert.equal(speaks,0);
  assert.equal(h.runtime.getRuntimeSnapshot().speech_enabled,false);
});
test('cancellation while journaling prevents response publication and speech', async () => {
  let release, speaks=0;
  const pending=new Promise(resolve=>release=resolve);
  const h=runtimeHarness({saveActivity:items=>items[0].category==='AIDA' ? pending : Promise.resolve(),speakAidaText:async()=>{speaks++;return 'silent';}});
  await h.runtime.initializeAidaRuntime();
  const request=h.runtime.submitLocalDirective('question');
  h.resolve({text:'answer',provider:'fake',mode:'remote'});
  await new Promise(resolve=>setImmediate(resolve));
  h.runtime.cancelRuntimeOperation();
  release();
  await assert.rejects(request,/cancelled/);
  assert.equal(speaks,0);
});
test('enrollment and disconnect serialize across delayed secure persistence', async () => {
  let release, stored=null, revoked=0;
  const write=new Promise(resolve=>release=resolve);
  const ready={protocol_version:2,reasoning_configured:true,speech_configured:true,transcription_configured:true};
  const load=loader({
    '@/src/core/reasoning/local-provider':{LocalRuntimeReasoningProvider:class {id='local';}},
    '@/src/core/services/gateway-config':{validateGatewayUrl:value=>value,setDevelopmentSession:()=>{},loadGatewayConfiguration:async()=>stored ? {...stored,kind:'session',source:'enrolled'} : {baseUrl:'',token:''}},
    '@/src/core/services/gateway-request':{gatewayRequest:async (_config,url)=>url==='/v1/enroll' ? {token:'A'.repeat(48),device_id:'device',expires_at:Date.now()/1000+1000,protocol_version:2} : url==='/v1/ready' ? ready : (revoked++,{revoked:true})},
    '@/src/core/storage/mobile-storage':{saveGatewayEnrollment:async value=>{await write;stored=value;},clearGatewayEnrollment:async()=>{stored=null;}},
  });
  const service=new (load('@/src/core/reasoning/service').MobileReasoningService)();
  const enrolling=service.configureGateway('https://example','bootstrap');
  await new Promise(resolve=>setImmediate(resolve));
  const disconnecting=service.disconnect();
  release();
  await Promise.all([enrolling,disconnecting]);
  assert.equal(stored,null);
  assert.equal(revoked,1);
  assert.equal(service.isRemoteConfigured(),false);
  await service.initialize(true);
  assert.equal(service.isRemoteConfigured(),false);
});

test('late transcription cleanup cannot reset or delete a replacement recording', async () => {
  let rejectOld;
  const oldTranscription=new Promise((_resolve,reject)=>rejectOld=reject);
  const h=homeHarness({transcribe:()=>oldTranscription});
  h.permissionResolve({granted:true});
  await h.capture.startVoiceCapture();
  const oldStop=h.capture.stopVoiceCapture(false);
  await new Promise(resolve=>setImmediate(resolve));
  h.capture.cancelCapture();
  await new Promise(resolve=>setImmediate(resolve));
  await h.capture.startVoiceCapture();
  assert.equal(h.counts().recorded,2);
  const modesBefore=h.audioModes.length;
  rejectOld(new Error('old transcription cancelled'));
  await oldStop;
  assert.equal(h.audioModes.length,modesBefore);
  assert.equal(h.discardedUris.includes('file:///temporary-2.m4a'),false);
  await h.capture.startVoiceCapture();
  assert.equal(h.counts().recorded,2);
  h.capture.cancelCapture();
});
