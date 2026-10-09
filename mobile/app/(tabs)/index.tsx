import Constants from 'expo-constants';
import {
  AudioModule,
  RecordingPresets,
  setAudioModeAsync,
  useAudioRecorder,
  useAudioRecorderState,
} from 'expo-audio';
import { useFocusEffect } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AppState,
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import {
  AidaOrb,
  AidaOrbVisualState,
} from '@/src/components/aida-orb';
import { GlassPanel } from '@/src/components/glass-panel';
import { LocalReviewError } from '@/src/core/perception/local-review-error';
import {
  MessageCard,
  MobileMessage,
} from '@/src/components/message-card';
import {
  discardAidaRecording,
  transcribeAidaRecording,
} from '@/src/core/interaction/transcription-client';
import {
  beginVoiceListening,
  reserveVoiceInput,
  cancelRuntimeOperation,
  refreshServicesGateway,
  beginVoiceProcessing,
  completeVoiceInput,
  failVoiceInput,
  getRuntimeSnapshot,
  LocalRuntimeStatus,
  MobileRuntimeSnapshot,
  submitLocalDirective,
  subscribeRuntime,
} from '@/src/core/runtime/aida-runtime';
import {
  AIDA_COLORS,
  AIDA_FONTS,
  AIDA_RADIUS,
  AIDA_SPACING,
  AIDA_STATUS_TONES,
  AidaRuntimeStatus,
} from '@/src/theme/aida-theme';

const VOICE_RECORDING_LIMIT_MS = 120_000;

const NATIVE_STARTUP_MESSAGES: MobileMessage[] = [
  {
    id: 'startup-system',
    sender: 'system',
    text: 'Analytical Intelligent Diagnostic Agent is activated.',
  },
  {
    id: 'startup-aida',
    sender: 'aida',
    text: 'State malfunction parameters.',
  },
];

export default function HomeScreen() {
  const [runtime, setRuntime] = useState<MobileRuntimeSnapshot>(() =>
    getRuntimeSnapshot(),
  );
  const [draft, setDraft] = useState('');
  const [showQuickActions, setShowQuickActions] = useState(false);
  const [keyboardVisible, setKeyboardVisible] = useState(false);
  const [voiceRecording, setVoiceRecording] = useState(false);
  const [voiceProcessing, setVoiceProcessing] = useState(false);
  const [messages, setMessages] = useState<MobileMessage[]>(() => [
    ...NATIVE_STARTUP_MESSAGES,
  ]);
  const scrollRef = useRef<ScrollView>(null);
  const voiceRecordingRef = useRef(false);
  const voiceBusyRef = useRef(false);
  const voiceStartingRef = useRef(false);
  const voiceGenerationRef = useRef(0);
  const submissionRef = useRef(false);
  const mountedRef = useRef(true);
  const voiceSignalRef = useRef<AbortSignal | null>(null);
  const recordingUriRef = useRef<string | null>(null);
  const messagesRef = useRef(messages);
  messagesRef.current = messages;
  const voiceLimitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const audioRecorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const recorderState = useAudioRecorderState(audioRecorder, 200);

  const status = mapRuntimeStatus(runtime.status);
  const tone = AIDA_STATUS_TONES[status];
  const orb = deriveOrbPresentation(runtime.status);
  const appVersion = Constants.expoConfig?.version ?? '0.1.0';
  const inputReady =
    runtime.status === 'STANDBY' && !voiceRecording && !voiceProcessing;
  const voiceAvailable =
    runtime.capabilities.find((item) => item.id === 'voice.input')?.state ===
    'supported';

  const platformLine = useMemo(
    () =>
      `${runtime.platform.toUpperCase()} ${runtime.platform_version} • LOCAL INSTANCE`,
    [runtime.platform, runtime.platform_version],
  );

  const scrollMessagesToEnd = useCallback((animated = true) => {
    requestAnimationFrame(() => {
      scrollRef.current?.scrollToEnd({ animated });
    });
  }, []);

  useEffect(() => subscribeRuntime(setRuntime), []);

  useEffect(() => {
    const showEvent = Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow';
    const hideEvent = Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide';
    const showSubscription = Keyboard.addListener(showEvent, () => {
      setKeyboardVisible(true);
      setShowQuickActions(false);
    });
    const hideSubscription = Keyboard.addListener(hideEvent, () => {
      setKeyboardVisible(false);
    });

    return () => {
      showSubscription.remove();
      hideSubscription.remove();
    };
  }, []);

  useEffect(() => {
    if (keyboardVisible) {
      scrollMessagesToEnd(false);
    }
  }, [keyboardVisible, scrollMessagesToEnd]);

  const cancelCapture = useCallback(() => {
    const generation = ++voiceGenerationRef.current;
    const ownedUri = recordingUriRef.current;
    cancelRuntimeOperation();
    if (voiceLimitTimerRef.current) clearTimeout(voiceLimitTimerRef.current);
    voiceLimitTimerRef.current = null;
    voiceRecordingRef.current = false;
    void audioRecorder.stop().catch(() => undefined).then(async () => {
      await discardAidaRecording(ownedUri).catch(() => undefined);
      if (generation !== voiceGenerationRef.current) return;
      await setAudioModeAsync({playsInSilentMode: true, allowsRecording: false}).catch(() => undefined);
      if (generation === voiceGenerationRef.current && !voiceStartingRef.current) voiceBusyRef.current = false;
    });
    if (mountedRef.current) { setVoiceRecording(false); setVoiceProcessing(false); }
  }, [audioRecorder]);

  useFocusEffect(useCallback(() => () => cancelCapture(), [cancelCapture]));
  useEffect(() => {
    mountedRef.current = true;
    const subscription = AppState.addEventListener('change', state => {
      if (state !== 'active') cancelCapture();
      else void refreshServicesGateway();
    });
    return () => { mountedRef.current = false; subscription.remove(); cancelCapture(); };
  }, [cancelCapture]);

  async function submitMessage() {
    const clean = draft.trim();
    if (!clean || !inputReady || submissionRef.current) {
      return;
    }
    setDraft('');
    await submitDirectiveText(clean);
  }

  async function submitDirectiveText(clean: string) {
    if (submissionRef.current || !mountedRef.current) return;
    submissionRef.current = true;
    // Native AIDA captures the previous eligible conversation before adding
    // the current User message, then passes that recent context to AIDABrain.
    const conversationContext = buildConversationContext(messagesRef.current);
    const userMessage: MobileMessage = {
      id: `user-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      sender: 'user',
      text: clean,
      includeInContext: false,
    };

    setMessages((current) => [...current.slice(-199), userMessage]);
    setShowQuickActions(false);

    try {
      const result = await submitLocalDirective(clean, conversationContext);
      if (!mountedRef.current) return;
      setMessages((current) => {
        const contextualized = current.map(message =>
          message.id === userMessage.id ? {...message, includeInContext: result.includeInContext} : message,
        );
        return [
          ...contextualized.slice(-199),
          {
            id: `aida-${Date.now()}-${Math.random().toString(36).slice(2)}`,
            sender: 'aida',
            text: result.text,
            includeInContext: result.includeInContext,
          },
        ];
      });
    } catch (error) {
      if (!mountedRef.current) return;
      const detail = error instanceof Error ? error.message : 'AIDA request could not complete.';
      setMessages((current) => [
        ...current.slice(-199),
        {
          id: `system-${Date.now()}-${Math.random().toString(36).slice(2)}`,
          sender: 'system',
          text: `AIDA brain request failed: ${detail}`,
          includeInContext: false,
        },
      ]);
    } finally { submissionRef.current = false; }
  }

  async function toggleVoiceCapture() {
    if (voiceProcessing) return;
    if (voiceRecordingRef.current) {
      await stopVoiceCapture(false);
      return;
    }
    await startVoiceCapture();
  }

  async function startVoiceCapture() {
    if (voiceBusyRef.current || submissionRef.current || runtime.status !== 'STANDBY') return;
    if (!voiceAvailable) { appendSystemMessage('Voice transcription is unavailable. No microphone recording was started.'); return; }
    voiceBusyRef.current = true;
    voiceStartingRef.current = true;
    const generation = ++voiceGenerationRef.current;
    let ownedUri: string | null = null;
    let started = false;
    let ownedSignal: AbortSignal | undefined;
    try {
      const signal = reserveVoiceInput();
      ownedSignal = signal;
      voiceSignalRef.current = signal;
      const check = () => { if (signal.aborted || generation !== voiceGenerationRef.current || !mountedRef.current) throw new Error('Voice input cancelled.'); };
      const permission = await AudioModule.requestRecordingPermissionsAsync();
      check();
      if (!permission.granted) throw new Error('Microphone access was denied by the operating system.');
      await setAudioModeAsync({playsInSilentMode: true, allowsRecording: true});
      check();
      await audioRecorder.prepareToRecordAsync();
      ownedUri = audioRecorder.uri;
      check();
      recordingUriRef.current = ownedUri;
      // Native duration remains bounded even if the JavaScript thread is suspended.
      audioRecorder.record({forDuration: VOICE_RECORDING_LIMIT_MS / 1000});
      voiceRecordingRef.current = true;
      started = true;
      setVoiceRecording(true);
      setShowQuickActions(true);
      await beginVoiceListening(signal);
      check();
      voiceLimitTimerRef.current = setTimeout(() => { void stopVoiceCapture(true); }, VOICE_RECORDING_LIMIT_MS);
    } catch {
      if (!ownedSignal) {
        if (mountedRef.current) appendSystemMessage('AIDA is already processing an operation.');
        return;
      }
      await audioRecorder.stop().catch(() => undefined);
      await discardAidaRecording(ownedUri).catch(() => undefined);
      voiceRecordingRef.current = false;
      started = false;
      if (mountedRef.current) setVoiceRecording(false);
      await failVoiceInput('Microphone capture could not start or was cancelled.', ownedSignal);
      if (mountedRef.current) appendSystemMessage('Microphone capture could not start or was cancelled.');
      await setAudioModeAsync({playsInSilentMode: true, allowsRecording: false}).catch(() => undefined);
    } finally { voiceStartingRef.current = false; if (!started) voiceBusyRef.current = false; }
  }

  async function stopVoiceCapture(limitReached: boolean) {
    if (!voiceRecordingRef.current) return;
    voiceRecordingRef.current = false;
    setVoiceRecording(false);
    if (voiceLimitTimerRef.current) clearTimeout(voiceLimitTimerRef.current);
    voiceLimitTimerRef.current = null;
    let recordingUri: string | null = recordingUriRef.current;
    const generation = voiceGenerationRef.current;
    const signal = voiceSignalRef.current ?? undefined;
    try {
      await audioRecorder.stop();
      if (generation !== voiceGenerationRef.current) throw new Error('Voice input cancelled.');
      recordingUri = audioRecorder.uri;
      recordingUriRef.current = recordingUri;
      await setAudioModeAsync({playsInSilentMode: true, allowsRecording: false});
      if (signal?.aborted) throw new Error('Voice input cancelled.');
      if (limitReached) throw new Error('Recording reached the 120-second limit and was discarded.');
      if (!recordingUri) throw new Error('No microphone audio was captured.');
      setVoiceProcessing(true);
      await beginVoiceProcessing(signal);
      const transcript = await transcribeAidaRecording(recordingUri, signal);
      await discardAidaRecording(recordingUri);
      recordingUri = null;
      recordingUriRef.current = null;
      if (signal?.aborted || generation !== voiceGenerationRef.current || !mountedRef.current) throw new Error('Voice input cancelled.');
      await completeVoiceInput(signal);
      setVoiceProcessing(false);
      voiceBusyRef.current = false;
      await submitDirectiveText(transcript);
    } catch {
      const detail = signal?.aborted ? 'Voice input cancelled.' : 'Voice input could not complete. Check microphone permission and gateway availability.';
      await failVoiceInput(detail, signal);
      if (mountedRef.current && generation === voiceGenerationRef.current) { setVoiceProcessing(false); appendSystemMessage(detail); }
    } finally {
      await discardAidaRecording(recordingUri).catch(() => {
        if (mountedRef.current) appendSystemMessage('Temporary microphone audio could not be removed.');
      });
      if (generation === voiceGenerationRef.current) {
        await setAudioModeAsync({playsInSilentMode: true, allowsRecording: false}).catch(() => undefined);
        if (generation === voiceGenerationRef.current) voiceBusyRef.current = false;
      }
    }
  }

  function appendSystemMessage(text: string) {
    setMessages((current) => [
      ...current.slice(-199),
      {
        id: `system-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        sender: 'system',
        text,
        includeInContext: false,
      },
    ]);
  }

  async function reviewAttachment(label: string) {
    if (!inputReady || submissionRef.current || voiceBusyRef.current) return;
    submissionRef.current = true;
    setShowQuickActions(false);
    try {
      const intake = await import('@/src/core/perception/intake');
      if (!mountedRef.current) return;
      if (label === 'PASTE') {
        const review = await intake.reviewClipboard();
        if (mountedRef.current) appendSystemMessage(review);
      } else {
        const evidence = await intake.selectImageEvidence();
        if (!evidence || !mountedRef.current) return;
        const {saveEvidence} = await import('@/src/core/storage/mobile-storage');
        let saved = true;
        await saveEvidence(evidence).catch(() => { saved = false; });
        if (mountedRef.current) appendSystemMessage(evidence.transcript + (saved ? '' : '\nMetadata could not be saved; this review is available only in the current conversation.'));
      }
    } catch (error) {
      if (mountedRef.current) appendSystemMessage(error instanceof LocalReviewError ? error.message : 'Local evidence review could not complete. Check image or clipboard availability and retry. No content was sent to a service.');
    } finally { submissionRef.current = false; }
  }

  const voiceLabel = voiceProcessing
    ? 'PROCESSING'
    : voiceRecording
      ? `STOP MIC ${Math.floor(recorderState.durationMillis / 1000)}s`
      : 'MIC';

  return (
    <SafeAreaView style={styles.safeArea}>
      <StatusBar style="light" />
      <View pointerEvents="none" style={styles.backgroundGlowPrimary} />
      <View pointerEvents="none" style={styles.backgroundGlowSecondary} />

      <KeyboardAvoidingView
        style={styles.keyboardArea}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      >
        <View style={styles.contentFrame}>
          <GlassPanel
            variant="header"
            style={[styles.header, keyboardVisible && styles.headerKeyboard]}
          >
            <View style={styles.identityBlock}>
              <Text style={styles.title}>AIDA</Text>
              {!keyboardVisible ? (
                <Text style={styles.subtitle}>SYSTEMS DIAGNOSTIC CORE</Text>
              ) : null}
            </View>

            <View style={styles.headerStateBlock}>
              <Text style={styles.headerCaption}>CURRENT STATUS</Text>
              <View style={styles.headerStateRow}>
                <View
                  style={[
                    styles.stateDot,
                    { backgroundColor: tone.foreground },
                  ]}
                />
                <Text style={[styles.headerState, { color: tone.foreground }]}>
                  {runtime.status}
                </Text>
              </View>
            </View>
          </GlassPanel>

          {!keyboardVisible ? (
            <View style={styles.orbSection}>
              <AidaOrb
                label={orb.label}
                runtimeStatus={status}
                state={orb.state}
                size={156}
              />
              <Text style={styles.platformLine}>{platformLine}</Text>
              <Text style={styles.instanceLine} numberOfLines={1}>
                AIDA {appVersion} • {runtime.runtime_mode.toUpperCase()}
              </Text>
            </View>
          ) : null}

          <GlassPanel variant="deep" style={styles.feedPanel}>
            <View style={styles.feedHeader}>
              <View>
                <Text style={styles.sectionTitle}>COMMUNICATION FEED</Text>
                <Text style={styles.feedSubline} numberOfLines={1}>
                  AIDA RUNTIME
                </Text>
              </View>
              <View style={styles.localBadge}>
                <Text style={styles.localBadgeText}>LOCAL</Text>
              </View>
            </View>

            <ScrollView
              ref={scrollRef}
              style={styles.messageArea}
              contentContainerStyle={styles.messageContent}
              keyboardDismissMode={Platform.OS === 'ios' ? 'interactive' : 'on-drag'}
              keyboardShouldPersistTaps="handled"
              onContentSizeChange={() => scrollMessagesToEnd(true)}
            >
              {messages.map((item) => (
                <MessageCard key={item.id} message={item} />
              ))}
            </ScrollView>
          </GlassPanel>

          {showQuickActions && !keyboardVisible ? (
            <GlassPanel variant="panel" style={styles.quickActions}>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={voiceRecording ? 'Stop AIDA microphone recording' : 'Start AIDA microphone recording'}
                disabled={voiceProcessing || (!voiceRecording && runtime.status !== 'STANDBY')}
                onPress={() => void toggleVoiceCapture()}
                style={({ pressed }) => [
                  styles.quickActionButton,
                  voiceRecording && styles.quickActionButtonActive,
                  voiceProcessing && styles.quickActionButtonDisabled,
                  pressed && styles.pressed,
                ]}
              >
                <Text
                  style={[
                    styles.quickActionText,
                    voiceRecording && styles.quickActionTextActive,
                  ]}
                >
                  {voiceLabel}
                </Text>
              </Pressable>

              {['IMAGE', 'PASTE'].map((label) => (
                <Pressable
                  key={label}
                  accessibilityRole="button"
                  disabled={!inputReady}
                  onPress={() => void reviewAttachment(label)}
                  style={({ pressed }) => [
                    styles.quickActionButton,
                    !inputReady && styles.quickActionButtonDisabled,
                    pressed && styles.pressed,
                  ]}
                >
                  <Text style={styles.quickActionText}>{label}</Text>
                </Pressable>
              ))}
            </GlassPanel>
          ) : null}

          <GlassPanel variant="panel" style={styles.composerPanel}>
            <View style={styles.composerHeader}>
              <Text style={styles.sectionTitle}>COMMAND INTERFACE</Text>
              <Text style={styles.composerHint}>
                {voiceProcessing
                  ? 'VOICE PROCESSING'
                  : voiceRecording
                    ? 'LISTENING'
                    : 'ENTER TO SEND'}
              </Text>
            </View>

            <View style={styles.composerRow}>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Show AIDA input options"
                disabled={voiceProcessing}
                onPress={() => setShowQuickActions((current) => !current)}
                style={({ pressed }) => [
                  styles.addButton,
                  voiceProcessing && styles.quickActionButtonDisabled,
                  pressed && styles.pressed,
                ]}
              >
                <Text style={styles.addButtonText}>+</Text>
              </Pressable>

              <TextInput
                maxLength={8000}
                value={draft}
                onChangeText={setDraft}
                onFocus={() => scrollMessagesToEnd(false)}
                onSubmitEditing={() => void submitMessage()}
                editable={inputReady}
                placeholder="State malfunction parameters..."
                placeholderTextColor="#657684"
                returnKeyType="send"
                selectionColor={AIDA_COLORS.cyanGlow}
                style={styles.input}
              />

              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Send directive to AIDA"
                disabled={!draft.trim() || !inputReady}
                onPress={() => void submitMessage()}
                style={({ pressed }) => [
                  styles.sendButton,
                  (!draft.trim() || !inputReady) && styles.sendButtonDisabled,
                  pressed && styles.pressed,
                ]}
              >
                <Text style={styles.sendButtonText}>SEND</Text>
              </Pressable>
            </View>
          </GlassPanel>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function buildConversationContext(messages: MobileMessage[]): string[] {
  return messages
    .filter((message) => message.includeInContext !== false)
    .slice(-12)
    .map((message) => {
      const sender =
        message.sender === 'user'
          ? 'User'
          : message.sender === 'aida'
            ? 'AIDA'
            : 'System';
      return `${sender}: ${message.text.trim()}`;
    });
}

function mapRuntimeStatus(status: LocalRuntimeStatus): AidaRuntimeStatus {
  if (status === 'STARTING') {
    return 'CONNECTING';
  }
  return status;
}

function deriveOrbPresentation(status: LocalRuntimeStatus): {
  state: AidaOrbVisualState;
  label: string;
} {
  // Keep the mobile renderer on native AIDA's live-state resolver semantics.
  if (status === 'ERROR' || status === 'SHUTDOWN') {
    return {
      state: 'RED',
      label: status === 'SHUTDOWN' ? 'SHUTDOWN' : 'SYSTEM FAULT',
    };
  }
  if (
    status === 'STARTING' ||
    status === 'LISTENING' ||
    status === 'ANALYZING' ||
    status === 'SPEAKING'
  ) {
    return {
      state: 'GREEN',
      label: status === 'STARTING' ? 'STARTING' : status,
    };
  }
  if (status === 'WARNING') {
    return { state: 'BLUE', label: 'ATTENTION' };
  }
  return { state: 'BLUE', label: 'STANDBY' };
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: AIDA_COLORS.canvas,
  },
  keyboardArea: {
    flex: 1,
  },
  contentFrame: {
    flex: 1,
    minHeight: 0,
    width: '100%',
    maxWidth: 900,
    alignSelf: 'center',
    paddingHorizontal: AIDA_SPACING.sm,
    paddingTop: AIDA_SPACING.sm,
    paddingBottom: AIDA_SPACING.xs,
    gap: AIDA_SPACING.sm,
  },
  backgroundGlowPrimary: {
    position: 'absolute',
    top: -150,
    left: -120,
    width: 380,
    height: 380,
    borderRadius: 190,
    backgroundColor: 'rgba(27, 89, 119, 0.34)',
  },
  backgroundGlowSecondary: {
    position: 'absolute',
    right: -180,
    bottom: 40,
    width: 360,
    height: 360,
    borderRadius: 180,
    backgroundColor: 'rgba(32, 43, 100, 0.16)',
  },
  header: {
    minHeight: 74,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: AIDA_SPACING.md,
    paddingVertical: AIDA_SPACING.sm,
  },
  headerKeyboard: {
    minHeight: 58,
    paddingVertical: AIDA_SPACING.xs,
  },
  identityBlock: {
    flex: 1,
    minWidth: 0,
  },
  title: {
    color: AIDA_COLORS.textBright,
    fontFamily: AIDA_FONTS.display,
    fontSize: 29,
    fontWeight: '700',
    letterSpacing: 5,
  },
  subtitle: {
    marginTop: 2,
    color: AIDA_COLORS.cyan,
    fontFamily: AIDA_FONTS.display,
    fontSize: 8,
    fontWeight: '600',
    letterSpacing: 1.8,
  },
  headerStateBlock: {
    minWidth: 126,
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderWidth: 1,
    borderColor: AIDA_COLORS.borderSoft,
    borderRadius: AIDA_RADIUS.small,
    backgroundColor: 'rgba(5, 21, 31, 0.72)',
  },
  headerCaption: {
    color: AIDA_COLORS.textDim,
    fontFamily: AIDA_FONTS.display,
    fontSize: 7,
    fontWeight: '700',
    letterSpacing: 1.5,
  },
  headerStateRow: {
    marginTop: 5,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
  },
  stateDot: {
    width: 7,
    height: 7,
    borderRadius: 4,
  },
  headerState: {
    fontFamily: AIDA_FONTS.mono,
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 1,
  },
  orbSection: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingTop: 2,
    paddingBottom: 4,
  },
  platformLine: {
    marginTop: -8,
    color: AIDA_COLORS.cyan,
    fontFamily: AIDA_FONTS.mono,
    fontSize: 9,
    fontWeight: '700',
    letterSpacing: 1.4,
  },
  instanceLine: {
    marginTop: 4,
    color: AIDA_COLORS.textDim,
    fontFamily: AIDA_FONTS.mono,
    fontSize: 8,
    letterSpacing: 0.8,
  },
  feedPanel: {
    flex: 1,
    minHeight: 0,
    padding: AIDA_SPACING.sm,
  },
  feedHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: AIDA_SPACING.sm,
    paddingHorizontal: 2,
    paddingBottom: AIDA_SPACING.xs,
  },
  sectionTitle: {
    color: AIDA_COLORS.cyanStrong,
    fontFamily: AIDA_FONTS.display,
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 1.6,
  },
  feedSubline: {
    marginTop: 3,
    color: AIDA_COLORS.textDim,
    fontFamily: AIDA_FONTS.mono,
    fontSize: 7,
    letterSpacing: 1,
  },
  localBadge: {
    borderWidth: 1,
    borderColor: 'rgba(77, 236, 171, 0.42)',
    borderRadius: AIDA_RADIUS.pill,
    backgroundColor: 'rgba(9, 42, 34, 0.90)',
    paddingHorizontal: 9,
    paddingVertical: 5,
  },
  localBadgeText: {
    color: AIDA_COLORS.mint,
    fontFamily: AIDA_FONTS.mono,
    fontSize: 8,
    fontWeight: '700',
    letterSpacing: 1,
  },
  messageArea: {
    flex: 1,
    minHeight: 0,
  },
  messageContent: {
    gap: AIDA_SPACING.xs,
    paddingVertical: AIDA_SPACING.xs,
  },
  quickActions: {
    flexDirection: 'row',
    gap: AIDA_SPACING.xs,
    padding: AIDA_SPACING.xs,
  },
  quickActionButton: {
    flex: 1,
    minHeight: 38,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: AIDA_COLORS.borderSoft,
    borderRadius: AIDA_RADIUS.small,
    backgroundColor: AIDA_COLORS.glassInput,
  },
  quickActionButtonActive: {
    borderColor: 'rgba(89, 240, 179, 0.72)',
    backgroundColor: 'rgba(9, 72, 52, 0.90)',
  },
  quickActionButtonDisabled: {
    opacity: 0.45,
  },
  quickActionText: {
    color: AIDA_COLORS.textPrimary,
    fontFamily: AIDA_FONTS.mono,
    fontSize: 9,
    fontWeight: '700',
    letterSpacing: 1,
  },
  quickActionTextActive: {
    color: AIDA_COLORS.mint,
  },
  composerPanel: {
    padding: AIDA_SPACING.sm,
  },
  composerHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: AIDA_SPACING.xs,
  },
  composerHint: {
    color: AIDA_COLORS.textDim,
    fontFamily: AIDA_FONTS.mono,
    fontSize: 7,
    fontWeight: '700',
    letterSpacing: 1,
  },
  composerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: AIDA_SPACING.xs,
  },
  addButton: {
    width: 44,
    height: 44,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: AIDA_COLORS.border,
    borderRadius: AIDA_RADIUS.small,
    backgroundColor: 'rgba(18, 36, 48, 0.88)',
  },
  addButtonText: {
    color: AIDA_COLORS.cyan,
    fontSize: 26,
    fontWeight: '300',
    lineHeight: 28,
  },
  input: {
    flex: 1,
    minWidth: 0,
    minHeight: 44,
    color: AIDA_COLORS.textPrimary,
    backgroundColor: AIDA_COLORS.glassInput,
    borderWidth: 1,
    borderColor: AIDA_COLORS.borderSoft,
    borderRadius: AIDA_RADIUS.small,
    paddingHorizontal: 13,
    fontSize: 14,
  },
  sendButton: {
    minWidth: 68,
    minHeight: 44,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: 'rgba(109, 218, 255, 0.70)',
    borderRadius: AIDA_RADIUS.small,
    backgroundColor: '#116da7',
    paddingHorizontal: 12,
  },
  sendButtonDisabled: {
    opacity: 0.42,
  },
  sendButtonText: {
    color: AIDA_COLORS.textBright,
    fontFamily: AIDA_FONTS.display,
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.6,
  },
  pressed: {
    opacity: 0.72,
  },
});
