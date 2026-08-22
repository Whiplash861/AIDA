import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { GlassPanel } from '@/src/components/glass-panel';
import { PageShell } from '@/src/components/page-shell';
import {
  configureServicesGateway,
  getRuntimeSnapshot,
  MobileRuntimeSnapshot,
  setSpeechEnabled,
  subscribeRuntime,
} from '@/src/core/runtime/aida-runtime';
import {
  GatewayConfiguration,
  loadGatewayConfiguration,
} from '@/src/core/services/gateway-config';
import {
  AIDA_COLORS,
  AIDA_FONTS,
  AIDA_RADIUS,
  AIDA_SPACING,
} from '@/src/theme/aida-theme';

type OperationRow = {
  title: string;
  detail: string;
  badge: string;
  tone: 'ready' | 'staged' | 'protected';
};

const GROUPS: { title: string; items: OperationRow[] }[] = [
  {
    title: 'SYSTEM',
    items: [
      { title: 'Android Device', detail: 'Local platform identity and capability discovery.', badge: 'READY', tone: 'ready' },
      { title: 'Local Storage', detail: 'Persistent instance identity and device-local runtime history.', badge: 'READY', tone: 'ready' },
      { title: 'Notifications', detail: 'Local and autonomous mobile alerts.', badge: 'STAGED', tone: 'staged' },
    ],
  },
  {
    title: 'AIDA',
    items: [
      { title: 'Memory', detail: 'Persistent storage foundation is active; semantic memory parity remains staged.', badge: 'FOUNDATION', tone: 'ready' },
      { title: 'Threats', detail: 'Device-local findings, evidence, and response plans.', badge: 'STAGED', tone: 'staged' },
      { title: 'Tasks', detail: 'Durable background assistance and progress.', badge: 'STAGED', tone: 'staged' },
    ],
  },
  {
    title: 'ENGINES',
    items: [
      { title: 'Artificer', detail: 'Mobile compatibility reviews, proposals, and governance.', badge: 'STAGED', tone: 'staged' },
      { title: 'Technomancer', detail: 'Permission-aware Android application and device assistance.', badge: 'STAGED', tone: 'staged' },
      { title: 'Perception', detail: 'Camera, screenshot, and image evidence intake.', badge: 'STAGED', tone: 'staged' },
    ],
  },
  {
    title: 'CONTROL & SUPPORT',
    items: [
      { title: 'Autonomy', detail: 'Authority remains device-scoped and confirmation-bound.', badge: 'PROTECTED', tone: 'protected' },
      { title: 'Report Bug', detail: 'Submit Early Alpha feedback from this AIDA instance.', badge: 'STAGED', tone: 'staged' },
    ],
  },
];

const EMPTY_GATEWAY: GatewayConfiguration = {
  baseUrl: '',
  token: '',
  source: 'none',
};

export default function MoreScreen() {
  const [runtime, setRuntime] = useState<MobileRuntimeSnapshot>(() => getRuntimeSnapshot());
  const [speechUpdating, setSpeechUpdating] = useState(false);
  const [gateway, setGateway] = useState<GatewayConfiguration>(EMPTY_GATEWAY);
  const [gatewayUrl, setGatewayUrl] = useState('');
  const [gatewayToken, setGatewayToken] = useState('');
  const [gatewaySaving, setGatewaySaving] = useState(false);
  const [gatewayMessage, setGatewayMessage] = useState('');

  useEffect(() => subscribeRuntime(setRuntime), []);
  useEffect(() => {
    void loadGatewayConfiguration().then((configuration) => {
      setGateway(configuration);
      setGatewayUrl(configuration.baseUrl);
    });
  }, []);

  const brainValue = runtime.statuses.find((item) => item.id === 'brain')?.value;
  const gatewayReady = brainValue === 'IDLE';
  const developmentAuto = gateway.source === 'development';
  const voiceCapability = runtime.capabilities.find((item) => item.id === 'voice.input');
  const voiceReady = voiceCapability?.state === 'supported';

  async function toggleSpeech() {
    if (speechUpdating) return;
    setSpeechUpdating(true);
    try {
      await setSpeechEnabled(!runtime.speech_enabled);
    } finally {
      setSpeechUpdating(false);
    }
  }

  async function enrollGateway() {
    if (gatewaySaving || developmentAuto) return;
    setGatewaySaving(true);
    setGatewayMessage('');
    try {
      await configureServicesGateway(gatewayUrl, gatewayToken);
      setGatewayToken('');
      const configuration = await loadGatewayConfiguration();
      setGateway(configuration);
      setGatewayMessage('Gateway enrolled. Native AIDA provider services are available.');
    } catch (error) {
      setGatewayMessage(error instanceof Error ? error.message : 'Gateway enrollment failed.');
    } finally {
      setGatewaySaving(false);
    }
  }

  return (
    <PageShell
      title="Control"
      subtitle="AIDA systems, Engines, authority, and support."
    >
      <GlassPanel variant="header" style={styles.noticeCard}>
        <Text style={styles.noticeTitle}>STANDALONE MOBILE EARLY ALPHA</Text>
        <Text style={styles.noticeBody}>
          This AIDA instance initializes locally on the mobile device. Desktop
          AIDA is not required. Shared provider services supply native AIDA
          reasoning, voice, and transcription without making another AIDA
          instance a dependency.
        </Text>
      </GlassPanel>

      <GlassPanel variant="deep" style={styles.groupCard}>
        <View style={styles.gatewayHeader}>
          <Text style={styles.groupTitle}>AIDA SERVICES GATEWAY</Text>
          <View style={[styles.badge, gatewayReady ? styles.readyBadge : styles.stagedBadge]}>
            <Text style={[styles.badgeText, gatewayReady ? styles.readyText : styles.stagedText]}>
              {developmentAuto && gatewayReady
                ? 'DEVELOPMENT AUTO'
                : gatewayReady
                  ? 'READY'
                  : gateway.source === 'none'
                    ? 'NOT ENROLLED'
                    : 'ATTENTION'}
            </Text>
          </View>
        </View>
        <Text style={styles.gatewayDetail}>
          Native intent resolution, AIDABrain reasoning, configured AIDA ElevenLabs voice, and disposable voice transcription. Provider credentials remain outside the mobile application.
        </Text>

        {developmentAuto ? (
          <View style={styles.developmentCard}>
            <Text style={styles.developmentLabel}>AUTOMATIC DEVELOPMENT SESSION</Text>
            <Text style={styles.developmentValue} numberOfLines={1}>
              {gateway.baseUrl}
            </Text>
            <Text style={styles.gatewayDetail}>
              The development launcher supplied an ephemeral session credential. No manual token entry is required.
            </Text>
          </View>
        ) : (
          <>
            <TextInput
              value={gatewayUrl}
              onChangeText={setGatewayUrl}
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="url"
              placeholder="Gateway URL"
              placeholderTextColor={AIDA_COLORS.textDim}
              style={styles.input}
            />
            <TextInput
              value={gatewayToken}
              onChangeText={setGatewayToken}
              autoCapitalize="none"
              autoCorrect={false}
              secureTextEntry
              placeholder="Gateway enrollment credential"
              placeholderTextColor={AIDA_COLORS.textDim}
              style={styles.input}
            />
            <Pressable
              onPress={() => void enrollGateway()}
              disabled={gatewaySaving}
              style={({ pressed }) => [styles.gatewayButton, pressed && styles.pressed]}
            >
              <Text style={styles.gatewayButtonText}>
                {gatewaySaving ? 'ENROLLING...' : 'ENROLL GATEWAY'}
              </Text>
            </Pressable>
          </>
        )}
        {gatewayMessage ? <Text style={styles.gatewayMessage}>{gatewayMessage}</Text> : null}
      </GlassPanel>

      <GlassPanel variant="deep" style={styles.groupCard}>
        <Text style={styles.groupTitle}>INTERACTION</Text>
        <View style={styles.rows}>
          <View style={[styles.row, styles.rowBorder]}>
            <View style={styles.rowText}>
              <Text style={styles.rowTitle}>Speech Output</Text>
              <Text style={styles.rowDetail}>
                Canonical start tone, configured AIDA ElevenLabs voice, and canonical end tone. No operating-system voice substitutes for AIDA if the voice provider is unavailable.
              </Text>
            </View>
            <Pressable
              accessibilityRole="switch"
              accessibilityState={{ checked: runtime.speech_enabled }}
              onPress={() => void toggleSpeech()}
              style={({ pressed }) => [
                styles.switchTrack,
                runtime.speech_enabled && styles.switchTrackEnabled,
                pressed && styles.pressed,
              ]}
            >
              <View style={[styles.switchThumb, runtime.speech_enabled && styles.switchThumbEnabled]} />
            </Pressable>
          </View>

          <View style={styles.row}>
            <View style={styles.rowText}>
              <Text style={styles.rowTitle}>Voice Input</Text>
              <Text style={styles.rowDetail}>
                {voiceCapability?.detail ?? 'Push-to-talk voice input is initializing.'}
              </Text>
            </View>
            <View style={[styles.badge, voiceReady ? styles.readyBadge : styles.stagedBadge]}>
              <Text style={[styles.badgeText, voiceReady ? styles.readyText : styles.stagedText]}>
                {voiceReady ? 'READY' : 'STAGED'}
              </Text>
            </View>
          </View>
        </View>
      </GlassPanel>

      {GROUPS.map((group) => (
        <GlassPanel key={group.title} variant="deep" style={styles.groupCard}>
          <Text style={styles.groupTitle}>{group.title}</Text>
          <View style={styles.rows}>
            {group.items.map((item, index) => (
              <View key={item.title} style={[styles.row, index < group.items.length - 1 && styles.rowBorder]}>
                <View style={styles.rowText}>
                  <Text style={styles.rowTitle}>{item.title}</Text>
                  <Text style={styles.rowDetail}>{item.detail}</Text>
                </View>
                <View style={[styles.badge, badgeStyle(item.tone)]}>
                  <Text style={[styles.badgeText, badgeTextStyle(item.tone)]}>{item.badge}</Text>
                </View>
              </View>
            ))}
          </View>
        </GlassPanel>
      ))}
    </PageShell>
  );
}

function badgeStyle(tone: OperationRow['tone']) {
  if (tone === 'ready') return styles.readyBadge;
  if (tone === 'protected') return styles.protectedBadge;
  return styles.stagedBadge;
}

function badgeTextStyle(tone: OperationRow['tone']) {
  if (tone === 'ready') return styles.readyText;
  if (tone === 'protected') return styles.protectedText;
  return styles.stagedText;
}

const styles = StyleSheet.create({
  noticeCard: { padding: AIDA_SPACING.md },
  noticeTitle: { color: AIDA_COLORS.cyanStrong, fontFamily: AIDA_FONTS.display, fontSize: 11, fontWeight: '700', letterSpacing: 1.5 },
  noticeBody: { marginTop: AIDA_SPACING.xs, color: AIDA_COLORS.textPrimary, fontSize: 13, lineHeight: 20 },
  groupCard: { padding: AIDA_SPACING.md },
  groupTitle: { color: AIDA_COLORS.cyanStrong, fontFamily: AIDA_FONTS.display, fontSize: 10, fontWeight: '700', letterSpacing: 1.6 },
  gatewayHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: AIDA_SPACING.sm },
  gatewayDetail: { marginTop: AIDA_SPACING.sm, color: AIDA_COLORS.textMuted, fontSize: 12, lineHeight: 18 },
  developmentCard: { marginTop: AIDA_SPACING.sm, borderWidth: 1, borderColor: AIDA_COLORS.borderSoft, borderRadius: AIDA_RADIUS.small, backgroundColor: 'rgba(5, 13, 20, 0.72)', padding: AIDA_SPACING.sm },
  developmentLabel: { color: AIDA_COLORS.mint, fontFamily: AIDA_FONTS.mono, fontSize: 8, fontWeight: '700', letterSpacing: 0.8 },
  developmentValue: { marginTop: 6, color: AIDA_COLORS.textPrimary, fontFamily: AIDA_FONTS.mono, fontSize: 10 },
  input: { marginTop: AIDA_SPACING.sm, minHeight: 42, borderWidth: 1, borderColor: AIDA_COLORS.borderSoft, borderRadius: AIDA_RADIUS.small, backgroundColor: 'rgba(5, 13, 20, 0.88)', color: AIDA_COLORS.textBright, paddingHorizontal: 12, fontFamily: AIDA_FONTS.mono, fontSize: 11 },
  gatewayButton: { marginTop: AIDA_SPACING.sm, minHeight: 40, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: 'rgba(100, 216, 255, 0.45)', borderRadius: AIDA_RADIUS.small, backgroundColor: 'rgba(8, 39, 59, 0.86)' },
  gatewayButtonText: { color: AIDA_COLORS.cyanStrong, fontFamily: AIDA_FONTS.display, fontSize: 10, fontWeight: '700', letterSpacing: 1.2 },
  gatewayMessage: { marginTop: AIDA_SPACING.sm, color: AIDA_COLORS.textMuted, fontSize: 11, lineHeight: 17 },
  rows: { marginTop: AIDA_SPACING.sm },
  row: { minHeight: 68, flexDirection: 'row', alignItems: 'center', gap: AIDA_SPACING.sm },
  rowBorder: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: AIDA_COLORS.borderSoft },
  rowText: { flex: 1, minWidth: 0 },
  rowTitle: { color: AIDA_COLORS.textBright, fontFamily: AIDA_FONTS.display, fontSize: 14, fontWeight: '700', letterSpacing: 0.7 },
  rowDetail: { marginTop: 4, color: AIDA_COLORS.textMuted, fontSize: 12, lineHeight: 18 },
  badge: { minHeight: 28, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderRadius: AIDA_RADIUS.pill, paddingHorizontal: 10, paddingVertical: 5 },
  readyBadge: { backgroundColor: 'rgba(9, 42, 34, 0.90)', borderColor: 'rgba(77, 236, 171, 0.42)' },
  stagedBadge: { backgroundColor: 'rgba(25, 35, 43, 0.90)', borderColor: 'rgba(136, 166, 187, 0.30)' },
  protectedBadge: { backgroundColor: 'rgba(48, 36, 12, 0.88)', borderColor: 'rgba(255, 205, 91, 0.42)' },
  badgeText: { fontFamily: AIDA_FONTS.mono, fontSize: 8, fontWeight: '700', letterSpacing: 0.8 },
  readyText: { color: AIDA_COLORS.mint },
  stagedText: { color: AIDA_COLORS.textMuted },
  protectedText: { color: AIDA_COLORS.warning },
  switchTrack: { width: 50, height: 28, justifyContent: 'center', borderWidth: 1, borderColor: 'rgba(136, 166, 187, 0.35)', borderRadius: AIDA_RADIUS.pill, backgroundColor: 'rgba(25, 35, 43, 0.92)', paddingHorizontal: 3 },
  switchTrackEnabled: { borderColor: 'rgba(77, 236, 171, 0.55)', backgroundColor: 'rgba(9, 72, 52, 0.92)' },
  switchThumb: { width: 20, height: 20, borderRadius: 10, backgroundColor: AIDA_COLORS.textMuted },
  switchThumbEnabled: { alignSelf: 'flex-end', backgroundColor: AIDA_COLORS.mint },
  pressed: { opacity: 0.72 },
});
