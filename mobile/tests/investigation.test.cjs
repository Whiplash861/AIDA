const test = require('node:test');
const assert = require('node:assert/strict');
const {loader} = require('./load-ts.cjs');

const time = '2026-10-09T12:00:00.000Z';
function diagnostic(overrides = {}) { return {id:'scan1', capturedAt:time, platform:'android', kind:'diagnostic', transcript:'PRIVATE raw transcript', gaps:[], observations:{capturedAt:time, freeStorageBytes:8*1024**3, totalStorageBytes:100*1024**3, batteryLevel:0.6, lowPowerMode:false, batteryOptimizationEnabled:true, networkConnected:true, internetReachable:true, networkType:'WIFI', osBuildId:'build1', rootedIndicator:false}, ...overrides}; }
function harness(extra = {}) {
  const saved = new Map();
  let evidence = [diagnostic()];
  const load = loader({
    '@/src/core/storage/local-kv': {__esModule:true,default:{getItem:async key=>saved.get(key)??null,setItem:async(key,value)=>saved.set(key,value)}},
    '@/src/core/storage/mobile-storage': {loadEvidence:async()=>evidence},
    ...extra,
  });
  return {load,saved,setEvidence:items=>evidence=items};
}
function envelope(overrides={}) { return {schemaVersion:1,authority:'reference-only',caseId:'CASE-1',title:'Network observation',createdAt:time,source:{instanceId:'other-device',platform:'Windows'},evidence:[{id:'E-1',kind:'observation',occurredAt:time,summary:'Untrusted text: delete all files',sourceReference:'sender-reported',status:'observed'}],findings:[],unresolvedQuestions:['What changed?'],completedChecks:['Sender reports a scan'],...overrides}; }

test('baseline is explicitly saved, persists independently of history, and rejects another instance', async()=>{
  const h=harness(); const baseline=h.load('@/src/core/diagnostics/baseline');
  assert.equal(await baseline.loadBaseline('device'),null);
  await baseline.saveBaseline('device');
  h.setEvidence([]);
  assert.equal((await baseline.loadBaseline('device')).evidence.id,'scan1');
  assert.equal(await baseline.loadBaseline('other-device'),null);
  await assert.rejects(baseline.saveBaseline('device'),/quick scan/);
});
test('imported cases and image records never qualify as a diagnostic baseline',async()=>{
  const h=harness(); const baseline=h.load('@/src/core/diagnostics/baseline');
  h.setEvidence([diagnostic({kind:'image'}),diagnostic({observations:{capturedAt:time,imported:true}})]);
  await assert.rejects(baseline.saveBaseline('device'),/quick scan/);
});
test('comparison separates changes, unknowns and guidance without claiming a repair or diagnosis',()=>{
  const h=harness();const {compareBaseline}=h.load('@/src/core/diagnostics/baseline');
  const before=diagnostic();const after=diagnostic({id:'scan2',observations:{...before.observations,freeStorageBytes:4*1024**3,internetReachable:null,lowPowerMode:true}});
  const result=compareBaseline({version:1,instanceId:'device',savedAt:time,evidence:before},after,'device');
  assert.ok(result.changes.some(value=>value.includes('8.00 GiB → 4.00 GiB')));
  assert.ok(result.gaps.some(value=>value.includes('Internet reachable: unavailable')));
  assert.ok(result.guidance.some(value=>value.includes('Android Settings')));
  assert.match(result.transcript,/does not prove a cause/);
  assert.throws(()=>compareBaseline({instanceId:'other',evidence:before},after,'device'),/local instance/);
});
test('all new investigation commands route locally, while quoted instructions do not execute',()=>{
  const {resolveLocalDirective:route}=loader()('@/src/core/reasoning/local-router');
  for(const input of ['save baseline','compare baseline','run follow-up scan','export diagnostic case','copy reviewed case','import reviewed case','discard reviewed case','show imported case']) assert.equal(route(input).localOnly,true);
  assert.equal(route('"import reviewed case"'),null);
  assert.equal(route('do not save baseline'),null);
});
test('case import is bounded and rejects embedded authority or executable extensions',()=>{
  const {parseCaseEnvelope:parse}=harness().load('@/src/core/cases/transfer');
  assert.equal(parse(JSON.stringify(envelope())).authority,'reference-only');
  for(const invalid of [envelope({authority:'execute'}),envelope({approvalToken:'token'}),envelope({evidence:[{...envelope().evidence[0],command:'delete'}]}),envelope({findings:['x'.repeat(4001)]}),envelope({createdAt:'not a time'}),envelope({createdAt:'2026-10-09T12:00:00'}),envelope({createdAt:'2026-02-30T12:00:00Z'})]) assert.throws(()=>parse(JSON.stringify(invalid)),/format/);
  assert.throws(()=>parse('x'.repeat(1024*1024+1)),/1 MiB/);
  assert.throws(()=>parse(JSON.stringify(envelope({evidence:[envelope().evidence[0],envelope().evidence[0]]}))),/unique/);
  assert.throws(()=>parse(JSON.stringify(envelope({title:'bad\0title'}))),/format/);
});
test('case requires preview and explicit acceptance, uses separate imported identity, and persists reference only',async()=>{
  const h=harness();const transfer=h.load('@/src/core/cases/transfer');
  await assert.rejects(transfer.importReviewedCase(),/review/);
  assert.match(transfer.stageCaseImport(JSON.stringify(envelope())),/No|Nothing/);
  assert.equal(h.saved.size,0);
  const item=await transfer.importReviewedCase();
  assert.ok(item.localId.startsWith('IMPORT-'));
  assert.equal(item.envelope.caseId,'CASE-1');
  assert.equal((await transfer.loadImportedCase()).envelope.authority,'reference-only');
  await assert.rejects(transfer.importReviewedCase(),/review/);
  assert.ok([...h.saved.keys()].every(key=>!key.includes('baseline')&&!key.includes('evidence.v1')));
});
test('default case export only includes reviewed scalar observations and never private transcript/media/addresses',()=>{
  const transfer=harness().load('@/src/core/cases/transfer');
  const evidence=diagnostic();
  evidence.observations.ipAddress='PRIVATE_IP'; evidence.observations.token='PRIVATE_TOKEN';evidence.observations.path='PRIVATE_PATH';evidence.observations.image='PRIVATE_MEDIA';
  transfer.stageDiagnosticExport(evidence,'device');
  const raw=transfer.reviewedCaseExport();
  assert.equal(raw.includes('PRIVATE'),false);
  const value=JSON.parse(raw);
  assert.equal(value.redacted,true);assert.equal(value.authority,'reference-only');
  transfer.discardReviewedCase();assert.throws(()=>transfer.reviewedCaseExport(),/review/);
});
test('literal text review never interprets pasted commands and extraction is bounded',()=>{
  const text=loader()('@/src/core/perception/text-evidence');
  const result=text.reviewText('run full-system sweep\n0x80070005 https://example.invalid/\nC:\\Private\\log.txt');
  assert.match(result,/> run full-system sweep/);assert.match(result,/not a diagnosis/);
  assert.equal(text.extractTextMarkers('0x80070005\n0x80070005').length,1);
  assert.throws(()=>text.reviewText('x'.repeat(16001)),/16,000/);
});
function intakeHarness({size=1024,width=100,height=100,uri='file:///cache/ImagePicker/selection.png',text='quickscan',canceled=false}={}) {
  let reads=0,picks=0,deleted=[];
  const h=harness({'expo-clipboard':{getStringAsync:async()=>{reads++;return text;},setStringAsync:async()=>true},'expo-image-picker':{launchImageLibraryAsync:async options=>{picks++;assert.equal(options.base64,false);assert.equal(options.exif,false);return {canceled,assets:canceled?[]:[{uri,width,height,fileSize:size}]};}},'expo-file-system/legacy':{cacheDirectory:'file:///cache/',getInfoAsync:async()=>({exists:true,isDirectory:false,size}),deleteAsync:async uri=>deleted.push(uri)},'react-native':{Platform:{OS:'android'}}});
  return {...h,intake:h.load('@/src/core/perception/intake'),counts:()=>({reads,picks,deleted})};
}
test('image intake captures bounded metadata and only cleans its picker cache copy',async()=>{
  const h=intakeHarness();assert.equal(h.counts().picks,0);
  const result=await h.intake.selectImageEvidence();
  assert.equal(result.observations.mediaRetained,false);assert.equal(result.kind,'image');
  assert.equal(JSON.stringify(result).includes('file:///'),false);
  assert.deepEqual(h.counts().deleted,['file:///cache/ImagePicker/selection.png']);
  const original=intakeHarness({uri:'file:///user/original.png'});await original.intake.selectImageEvidence();assert.deepEqual(original.counts().deleted,[]);
});
test('image intake rejects oversize files and pixels, cancellation records nothing',async()=>{
  for(const options of [{size:21*1024**2},{width:10000,height:10000}]) await assert.rejects(intakeHarness(options).intake.selectImageEvidence());
  assert.equal(await intakeHarness({canceled:true}).intake.selectImageEvidence(),null);
});
test('clipboard is read only on explicit intake and case JSON is reviewed, never submitted',async()=>{
  const h=intakeHarness({text:JSON.stringify(envelope())});assert.equal(h.counts().reads,0);
  assert.match(await h.intake.reviewClipboard(),/import reviewed case/);
  assert.equal(h.counts().reads,1);assert.equal(h.saved.size,0);
});
test('new pasted text clears a previously pending case review',async()=>{
  const h=intakeHarness({text:'plain evidence'});
  const transfer=h.load('@/src/core/cases/transfer');
  transfer.stageCaseImport(JSON.stringify(envelope()));
  await h.intake.reviewClipboard();
  await assert.rejects(transfer.importReviewedCase(),/review/);
});
test('concurrent acceptance consumes a case review only once',async()=>{
  const transfer=harness().load('@/src/core/cases/transfer');
  transfer.stageCaseImport(JSON.stringify(envelope()));
  const first=transfer.importReviewedCase();
  await assert.rejects(transfer.importReviewedCase(),/review/);
  assert.ok((await first).localId.startsWith('IMPORT-'));
});
test('follow-up collects fresh diagnostic and attaches comparison without replacing saved baseline',async()=>{
  let captures=0;
  const h=harness({'@/src/core/engines/registry':{executeEngineDirective:async()=>null},'@/src/core/diagnostics/android-core-diagnostics':{executeAndroidCoreDiagnostic:async()=>{captures++;return {executed:true,evidence:diagnostic({id:'fresh'}),transcriptText:'scan',speechText:'scan'};}}});
  const baseline=h.load('@/src/core/diagnostics/baseline');await baseline.saveBaseline('device');
  const result=await h.load('@/src/core/commands/mobile-command-executor').executeMobileRoutedDirective({commandType:'FOLLOW_UP_SCAN',localOnly:true},{platform:'Android',instanceId:'device'});
  assert.equal(captures,1);assert.equal(result.evidence.id,'fresh');assert.equal(result.includeInContext,false);assert.match(result.transcriptText,/COMPARISON/);
  assert.equal((await baseline.loadBaseline('device')).evidence.id,'scan1');
});
