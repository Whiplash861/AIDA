import Constants from 'expo-constants';
import { StatusBar } from 'expo-status-bar';
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  ActivityIndicator,
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

import { GlassPanel } from '@/src/components/glass-panel';
import {
  MessageCard,
  MobileMessage,
} from '@/src/components/message-card';
import { StatusCore } from '@/src/components/status-core';
import {
  configuredApiUrl,
  getHealth,
  sendChat,
} from '@/src/services/aida-api';
import {
  AIDA_COLORS,
  AIDA_FONTS,
  AIDA_RADIUS,
  AIDA_SPACING,
  AIDA_STATUS_TONES,
  AidaRuntimeStatus,
} from '@/src/theme/aida-theme';

const INITIAL_MESSAGES: MobileMessage[] = [
  {
    id: 'welcome',
    sender: 'aida',
    text: 'AIDA mobile interface online. Establishing paired local bridge.',
  },
];

export default function HomeScreen() {
  const [draft, setDraft] = useState('');
  const [messages, setMessages] = useState<MobileMessage[]>(INITIAL_MESSAGES);
  const [status, setStatus] = useState<AidaRuntimeStatus>('CONNECTING');
  const [connectionNote, setConnectionNote] = useState('CONTACTING LOCAL BRIDGE');
  const scrollRef = useRef<ScrollView>(null);

  const tone = AIDA_STATUS_TONES[status];
  const appVersion = Constants.expoConfig?.version ?? '1.0.0';
  const apiLabel = useMemo(() => {
    const url = configuredApiUrl();
    return url ? url.replace(/^https?:\/\//, '') : 'NOT CONFIGURED';
  }, []);

  const checkConnection = useCallback(async () => {
    setStatus('CONNECTING');
    setConnectionNote('CONTACTING LOCAL BRIDGE');

    try {
      const health = await getHealth();
      if (health.status === 'ready') {
        setStatus('STANDBY');
        setConnectionNote(`PAIRED LOCAL BRIDGE READY • AIDA ${health.version}`);
      } else {
        setStatus('WARNING');
        setConnectionNote(
          health.brain_configured
            ? 'PAIRING REQUIRES CONFIGURATION'
            : 'AIDA BRAIN REQUIRES CONFIGURATION',
        );
      }
    } catch (error) {
      setStatus('OFFLINE');
      setConnectionNote(errorMessage(error));
    }
  }, []);

  useEffect(() => {
    void checkConnection();
  }, [checkConnection]);

  async function submitMessage() {
    const clean = draft.trim();
    if (!clean || status === 'ANALYZING') {
      return;
    }

    const userMessage: MobileMessage = {
      id: `user-${Date.now()}`,
      sender: 'user',
      text: clean,
    };

    const history = messages
      .filter((item) => item.sender !== 'system')
      .slice(-20)
      .map((item) => ({
        role: item.sender === 'user' ? ('user' as const) : ('assistant' as const),
        content: item.text,
      }));

    setMessages((current) => [...current, userMessage]);
    setDraft('');
    setStatus('ANALYZING');
    setConnectionNote('AIDA IS ANALYZING');

    try {
      const response = await sendChat({
        message: clean,
        history,
        device: {
          platform: `${Platform.OS} ${Platform.Version}`,
          model: Platform.OS === 'ios' ? 'Apple mobile device' : 'Mobile device',
          app_version: appVersion,
        },
      });

      setMessages((current) => [
        ...current,
        {
          id: `aida-${response.request_id}`,
          sender: 'aida',
          text: response.reply,
        },
      ]);
      setStatus('STANDBY');
      setConnectionNote('LOCAL BRIDGE READY');
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          id: `system-${Date.now()}`,
          sender: 'system',
          text: errorMessage(error),
        },
      ]);
      setStatus('ERROR');
      setConnectionNote('REQUEST FAILED • TAP STATUS TO RETRY');
    }
  }

  return (
    <SafeAreaView style={styles.safeArea}>
      <StatusBar style="light" />
      <View pointerEvents="none" style={styles.backgroundGlowPrimary} />
      <View pointerEvents="none" style={styles.backgroundGlowSecondary} />

      <KeyboardAvoidingView
        style={styles.keyboardArea}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <View style={styles.contentFrame}>
          <GlassPanel variant="header" style={styles.header}>
            <View style={styles.titleBlock}>
              <Text style={styles.title}>AIDA</Text>
              <Text style={styles.subtitle}>
                ANALYTICAL INTELLIGENT DIAGNOSTIC AGENT
              </Text>
            </View>

            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Retry AIDA bridge connection"
              onPress={() => void checkConnection()}
              style={({ pressed }) => [
                styles.statusBadge,
                {
                  backgroundColor: tone.background,
                  borderColor: tone.border,
                  opacity: pressed ? 0.72 : 1,
                },
              ]}
            >
              <View
                style={[
                  styles.statusDot,
                  { backgroundColor: tone.foreground },
                ]}
              />
              <Text style={[styles.statusText, { color: tone.foreground }]}>
                {status}
              </Text>
            </Pressable>
          </GlassPanel>

          <StatusCore status={status} />

          <GlassPanel variant="deep" style={styles.feedPanel}>
            <View style={styles.feedHeader}>
              <View>
                <Text style={styles.sectionTitle}>COMMUNICATION FEED</Text>
                <Text style={styles.connectionNote} numberOfLines={1}>
                  {connectionNote}
                </Text>
              </View>
              {status === 'ANALYZING' ? (
                <ActivityIndicator color={AIDA_COLORS.cyanGlow} size="small" />
              ) : null}
            </View>

            <ScrollView
              ref={scrollRef}
              style={styles.messageArea}
              contentContainerStyle={styles.messageContent}
              keyboardShouldPersistTaps="handled"
              onContentSizeChange={() =>
                scrollRef.current?.scrollToEnd({ animated: true })
              }
            >
              {messages.map((item) => (
                <MessageCard key={item.id} message={item} />
              ))}
            </ScrollView>
          </GlassPanel>

          <GlassPanel variant="panel" style={styles.composerPanel}>
            <View style={styles.composerHeader}>
              <Text style={styles.sectionTitle}>DIRECTIVE INPUT</Text>
              <Text style={styles.composerHint}>{apiLabel}</Text>
            </View>

            <View style={styles.composerRow}>
              <TextInput
                value={draft}
                onChangeText={setDraft}
                onSubmitEditing={() => void submitMessage()}
                editable={status !== 'ANALYZING'}
                placeholder="State directive or diagnostic question..."
                placeholderTextColor="#657684"
                returnKeyType="send"
                style={styles.input}
              />

              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Send directive to AIDA"
                disabled={!draft.trim() || status === 'ANALYZING'}
                onPress={() => void submitMessage()}
                style={({ pressed }) => [
                  styles.sendButton,
                  (!draft.trim() || status === 'ANALYZING') &&
                    styles.sendButtonDisabled,
                  pressed && styles.sendButtonPressed,
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

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Unknown AIDA bridge error.';
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
    width: '100%',
    maxWidth: 900,
    alignSelf: 'center',
    paddingHorizontal: AIDA_SPACING.sm,
    paddingTop: AIDA_SPACING.sm,
    paddingBottom: AIDA_SPACING.xs,
  },
  backgroundGlowPrimary: {
    position: 'absolute',
    top: -140,
    left: -110,
    width: 360,
    height: 360,
    borderRadius: 180,
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
    minHeight: 82,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: AIDA_SPACING.md,
    paddingVertical: AIDA_SPACING.sm,
  },
  titleBlock: {
    flex: 1,
    paddingRight: AIDA_SPACING.sm,
  },
  title: {
    color: AIDA_COLORS.textBright,
    fontFamily: AIDA_FONTS.display,
    fontSize: 29,
    fontWeight: '700',
    letterSpacing: 5,
  },
  subtitle: {
    marginTop: 3,
    color: AIDA_COLORS.cyan,
    fontFamily: AIDA_FONTS.display,
    fontSize: 8,
    fontWeight: '600',
    letterSpacing: 1.5,
  },
  statusBadge: {
    minHeight: 34,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
    borderWidth: 1,
    borderRadius: AIDA_RADIUS.pill,
    paddingHorizontal: 11,
    paddingVertical: 7,
  },
  statusDot: {
    width: 7,
    height: 7,
    borderRadius: 4,
  },
  statusText: {
    fontFamily: AIDA_FONTS.mono,
    fontSize: 9,
    fontWeight: '700',
    letterSpacing: 1,
  },
  feedPanel: {
    flex: 1,
    minHeight: 220,
    padding: AIDA_SPACING.sm,
  },
  feedHeader: {
    minHeight: 36,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 3,
    paddingBottom: AIDA_SPACING.xs,
  },
  sectionTitle: {
    color: AIDA_COLORS.cyanStrong,
    fontFamily: AIDA_FONTS.display,
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 1.6,
  },
  connectionNote: {
    maxWidth: 280,
    marginTop: 3,
    color: AIDA_COLORS.textDim,
    fontFamily: AIDA_FONTS.mono,
    fontSize: 8,
    letterSpacing: 0.7,
  },
  messageArea: {
    flex: 1,
  },
  messageContent: {
    gap: AIDA_SPACING.sm,
    paddingTop: AIDA_SPACING.xs,
    paddingBottom: AIDA_SPACING.sm,
  },
  composerPanel: {
    marginTop: AIDA_SPACING.sm,
    padding: AIDA_SPACING.sm,
  },
  composerHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 3,
    paddingBottom: AIDA_SPACING.xs,
  },
  composerHint: {
    maxWidth: '55%',
    color: AIDA_COLORS.textDim,
    fontFamily: AIDA_FONTS.mono,
    fontSize: 7,
  },
  composerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: AIDA_SPACING.xs,
  },
  input: {
    flex: 1,
    minHeight: 48,
    color: AIDA_COLORS.textPrimary,
    backgroundColor: AIDA_COLORS.glassInput,
    borderWidth: 1,
    borderColor: 'rgba(107, 181, 218, 0.32)',
    borderRadius: AIDA_RADIUS.small,
    paddingHorizontal: 14,
    fontSize: 14,
  },
  sendButton: {
    minWidth: 72,
    minHeight: 48,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: 'rgba(109, 218, 255, 0.70)',
    borderRadius: AIDA_RADIUS.small,
    backgroundColor: '#116da7',
    shadowColor: AIDA_COLORS.cyanGlow,
    shadowOpacity: 0.22,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 5,
  },
  sendButtonPressed: {
    opacity: 0.72,
    transform: [{ scale: 0.97 }],
  },
  sendButtonDisabled: {
    backgroundColor: 'rgba(30, 43, 54, 0.80)',
    borderColor: 'rgba(88, 109, 122, 0.22)',
    shadowOpacity: 0,
  },
  sendButtonText: {
    color: AIDA_COLORS.textBright,
    fontFamily: AIDA_FONTS.display,
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 1.3,
  },
});
