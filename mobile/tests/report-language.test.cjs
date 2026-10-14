const test = require('node:test');
const assert = require('node:assert/strict');
const {loader} = require('./load-ts.cjs');

function observation(overrides = {}) {
  return {capturedAt:'2026-10-10T12:00:00Z',platform:'android',platformVersion:'16',osName:'Android',osVersion:'16',apiLevel:36,
    manufacturer:'Example',modelName:'Phone',totalMemoryBytes:8*1024**3,maxAppMemoryBytes:256*1024**2,cpuArchitectures:['arm64'],
    totalStorageBytes:100*1024**3,freeStorageBytes:40*1024**3,batteryLevel:0.8,batteryState:'UNPLUGGED',lowPowerMode:false,
    batteryOptimizationEnabled:false,networkType:'WIFI',networkConnected:true,internetReachable:true,uptimeMs:600000,
    platformFeatureCount:10,rootedIndicator:false,osBuildFingerprint:'release-keys',osBuildId:'build',gaps:[],...overrides};
}
function harness(evidence) {
  let internalFindings;
  const load=loader({'@/src/core/platform/android/system-evidence':{
    captureAndroidSystemEvidence:async()=>evidence,
    formatBytes:value=>value==null?'Unavailable':String(value)+' bytes',
    formatDuration:()=> '10 minutes',
    storageUsedPercent:input=>input.totalStorageBytes && input.freeStorageBytes!=null ? Math.round((1-input.freeStorageBytes/input.totalStorageBytes)*100) : null,
  }}, {__captureFindings: findings=>{internalFindings=findings;}}, (file,source)=>{
    if(file.endsWith('android-provider.ts')) return source.replace('  const highCount =', '  __captureFindings(findings);\n  const highCount =');
    if(file.endsWith('android-core-diagnostics.ts')) return source+'\nexport {quickscanFindings};\n';
    return source;
  });
  const core=load('@/src/core/diagnostics/android-core-diagnostics');
  const aegis=load('@/src/core/engines/aegis/android-provider');
  return {core,security:commandType=>aegis.executeAndroidAegisCommand({commandType,localOnly:true},{platform:'Android'}),findings:()=>internalFindings};
}

test('unavailable root check is a missing result, not a spoken security warning',async()=>{
  const evidence=observation({rootedIndicator:null,gaps:[{id:'security.root-indicator',detail:'OPAQUE INTERNAL ROOT POSTURE'}]});
  const h=harness(evidence), report=await h.security('SECURITY_SURFACE_SCAN');
  assert.match(report.transcriptText,/What remains unknown/);
  assert.match(report.transcriptText,/missing result, not a detected threat/);
  assert.ok(report.transcriptText.indexOf('System access check unavailable:')>report.transcriptText.indexOf('What remains unknown'));
  assert.doesNotMatch(report.speechText,/\b1 (?:condition|item)|high-risk|threat.*detected/i);
  assert.doesNotMatch(report.transcriptText,/\[(?:WARNING|HIGH|INFO)\]|OPAQUE INTERNAL/);
  assert.equal(h.findings()[0].severity,'WARNING');
  assert.deepEqual(JSON.parse(JSON.stringify(report.evidence.observations)),evidence);
});

test('missing device readings stay separate and retain original stored evidence',async()=>{
  const evidence=observation({networkConnected:null,internetReachable:null,freeStorageBytes:null,gaps:[{id:'network.state',detail:'TECHNICAL_CONNECTION_FAILURE'},{id:'storage.free',detail:'TECHNICAL_STORAGE_FAILURE'}]});
  const report=await harness(evidence).core.executeAndroidCoreDiagnostic('QUICKSCAN',false);
  assert.match(report.transcriptText,/does not mean the internet is disconnected/);
  assert.match(report.transcriptText,/does not mean the storage is full/);
  assert.doesNotMatch(report.transcriptText,/TECHNICAL_|\[(?:WARNING|HIGH|INFO)\]/);
  assert.match(report.speechText,/results are missing/);
  assert.deepEqual(JSON.parse(JSON.stringify(report.evidence.observations)),evidence);
  assert.deepEqual(Array.from(report.evidence.gaps),['TECHNICAL_CONNECTION_FAILURE','TECHNICAL_STORAGE_FAILURE']);
  assert.equal(report.includeInContext,false);
});

test('low battery and network concern give practical steps without claiming malware',async()=>{
  const evidence=observation({batteryLevel:0.1,networkConnected:true,internetReachable:false});
  const h=harness(evidence), report=await h.core.executeAndroidCoreDiagnostic('QUICKSCAN',false);
  assert.match(report.transcriptText,/Battery low: 10%/);
  assert.match(report.transcriptText,/Connect a charger/);
  assert.match(report.transcriptText,/power reminder, not a security alert/);
  assert.match(report.transcriptText,/Check|checking Wi-Fi/);
  assert.match(report.transcriptText,/does not indicate a security threat/);
  assert.deepEqual(Array.from(h.core.quickscanFindings(evidence,60),item=>item.severity),['WARNING','WARNING']);
});

test('positive root and test key retain severity but explain uncertainty and next steps',async()=>{
  const evidence=observation({rootedIndicator:true,osBuildFingerprint:'test-keys'});
  const h=harness(evidence), report=await h.security('SECURITY_SURFACE_SCAN');
  assert.deepEqual(Array.from(h.findings(),item=>item.severity),['HIGH','WARNING','INFO']);
  assert.match(report.transcriptText,/intentional modification/);
  assert.match(report.transcriptText,/does not establish that malware is present/);
  assert.match(report.transcriptText,/device manufacturer/);
  assert.doesNotMatch(report.speechText,/high-risk|malware detected/i);
  assert.equal(report.evidence.observations.rootedIndicator,true);
});

test('coverage remains unchanged and explicitly describes information rather than risk',async()=>{
  const complete=await harness(observation()).security('SECURITY_SURFACE_SCAN');
  assert.match(complete.transcriptText,/3 of 6 \(50%\)/);
  assert.match(complete.transcriptText,/available information, not your risk level/);
  assert.match(complete.transcriptText,/cannot establish whether a file is safe/);
  const missing=await harness(observation({rootedIndicator:null,osBuildFingerprint:null,osBuildId:null,networkConnected:null})).security('SECURITY_SURFACE_SCAN');
  assert.match(missing.transcriptText,/0 of 6 \(0%\)/);
  assert.match(missing.speechText,/not a full assessment/);
});

test('performance report explains normal battery settings and leaves unavailable checks unknown',async()=>{
  const report=await harness(observation({lowPowerMode:true,batteryOptimizationEnabled:true,freeStorageBytes:5*1024**3,gaps:[{id:'memory.app-ceiling',detail:'MEMORY TELEMETRY'}]})).core.executeAndroidCoreDiagnostic('PERFORMANCE_SCAN',false);
  assert.match(report.transcriptText,/Storage almost full: 95%/);
  assert.match(report.transcriptText,/Power saver is on/);
  assert.match(report.transcriptText,/normal battery-saving setting/);
  assert.match(report.transcriptText,/does not show a memory problem/);
  assert.match(report.transcriptText,/Review Storage in Android Settings/);
  assert.doesNotMatch(report.transcriptText,/\[(?:WARNING|HIGH|INFO)\]|MEMORY TELEMETRY|critical/i);
});

test('security status explains unavailable Play Protect results without assuming it is disabled',async()=>{
  const report=await harness(observation({rootedIndicator:null,osBuildFingerprint:null})).security('SECURITY_STATUS');
  assert.match(report.transcriptText,/cannot tell whether Play Protect found a problem/);
  assert.match(report.transcriptText,/Check Play Protect in the Play Store/);
  assert.match(report.transcriptText,/missing information, not evidence that the software is unsafe/);
  assert.doesNotMatch(report.transcriptText,/\bDETECTED\b|TEST-KEYS REPORTED|Play Protect is disabled/);
});

function assertReport(text) {
  const headings=['What AIDA found','What remains unknown','What to do next'];
  const positions=headings.map(heading=>text.indexOf('\n'+heading+'\n'));
  assert.ok(positions.every(position=>position>=0),text);
  assert.ok(positions[0]<positions[1] && positions[1]<positions[2]);
}
test('every available diagnostic report has observations, unknowns and actionable follow-up',async()=>{
  const h=harness(observation());
  for(const report of [await h.core.executeAndroidCoreDiagnostic('QUICKSCAN',false),await h.core.executeAndroidCoreDiagnostic('PERFORMANCE_SCAN',false),await h.security('SECURITY_STATUS'),await h.security('SECURITY_SURFACE_SCAN')]) {
    assertReport(report.transcriptText);
    assert.equal(report.evidence.transcript,report.transcriptText);
    assert.equal(report.executed,true); assert.equal(report.includeInContext,false);
  }
});
test('staged Aegis and Technomancer requests explain no execution and preserve context flags',async()=>{
  const load=loader();
  const engines=[load('@/src/core/engines/aegis/manifest').AEGIS_ENGINE,load('@/src/core/engines/technomancer/manifest').TECHNOMANCER_ENGINE];
  for(const engine of engines) for(const localOnly of [true,false]) {
    const result=await engine.execute({commandType:engine.commandTypes[2],localOnly},{platform:'Android'});
    assertReport(result.transcriptText);
    assert.equal(result.executed,false);assert.equal(result.includeInContext,!localOnly);
    assert.match(result.transcriptText,/No operation was executed/);
    assert.match(result.transcriptText,/not available/);
    assert.doesNotMatch(result.transcriptText,/Registered AIDA intent|provider status|Subprocess:/);
  }
});
test('local fallback reports do not imply a device assessment or verified persistent storage',async()=>{
  const Provider=loader()('@/src/core/reasoning/local-provider').LocalRuntimeReasoningProvider;
  const provider=new Provider(),context={instanceId:'ephemeral_1',platform:'Android',platformVersion:'16',deviceModel:'Phone',supportedCapabilities:['Local AIDA runtime'],conversationContext:[]};
  for(const input of ['who are you','status','device','instance id','what can you do']) {
    const reply=await provider.respond(input,context);assertReport(reply.text);assert.equal(reply.mode,'local_fallback');
    assert.doesNotMatch(reply.text,/Storage: secure|^- (?:The |Your )?device is healthy|all checks passed/m);
  }
  const short=await provider.respond('help with my unreadable error',context);
  assert.match(short.text,/not connected/);assert.ok(short.text.length<450);
});
test('status labels preserve urgent meaning without changing internal values',()=>{
  const {displayStatus}=loader()('@/src/core/reporting');
  const states=['THREAT_CONFIRMED','DEGRADED','STAGED','WARNING','LIMITED'];
  assert.deepEqual(states.map(displayStatus),['Threat confirmed','Some checks unavailable','Not available yet','Needs review','Some checks available']);
  assert.equal(states[0],'THREAT_CONFIRMED');assert.equal(displayStatus('unrecognized-state'),'unrecognized-state');
});
