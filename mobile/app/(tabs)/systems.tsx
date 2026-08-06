import { useFocusEffect } from '@react-navigation/native';
import { useCallback, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { GlassPanel } from '@/src/components/glass-panel';
import { PageShell } from '@/src/components/page-shell';
import { StatusPill } from '@/src/components/status-pill';
import {
  getOperationalStatus,
  OperationalStatusResponse,
  StatusTone,
  SubsystemStatus,
} from '@/src/services/aida-api';
import {
  AIDA_COLORS,
  AIDA_FONTS,
  AIDA_RADIUS,
  AIDA_SPACING,
} from '@/src/theme/aida-theme';

const CORE_IDS = new Set(['agent', 'brain', 'memory', 'artificer']);

export default function SystemsScreen() {
  const [snapshot, setSnapshot] = useState<OperationalStatusResponse | null>(null);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [showAll, setShowAll] = useState(false);

  const load = useCallback(async (manual = false) => {
    if (manual) {
      setRefreshing(true);
    }
    try {
      const next = await getOperationalStatus();
      setSnapshot(next);
      setError('');
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : 'Unable to load AIDA status.',
      );
    } finally {
      if (manual) {
        setRefreshing(false);
      }
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  const attention = useMemo(
    () =>
      snapshot?.statuses.filter((item) => {
        if (item.id === 'tasks' && item.value === '0 ACTIVE') {
          return false;
        }
        return ['warning', 'error', 'active'].includes(item.tone);
      }) ?? [],
    [snapshot],
  );

  const core = useMemo(
    () => snapshot?.statuses.filter((item) => CORE_IDS.has(item.id)) ?? [],
    [snapshot],
  );

  const overallTone: StatusTone = !snapshot?.desktop_online
    ? 'offline'
    : attention.some((item) => item.tone === 'error')
      ? 'error'
      : attention.some((item) => item.tone === 'warning')
        ? 'warning'
        : 'ready';

  const overallValue = !snapshot?.desktop_online
    ? 'DESKTOP OFFLINE'
    : overallTone === 'ready'
      ? 'READY'
      : 'ATTENTION';

  return (
    <PageShell
      title="Systems"
      subtitle="A concise read-only view of AIDA's desktop runtime."
      refreshing={refreshing}
      onRefresh={() => void load(true)}
    >
      <GlassPanel variant="header" style={styles.overallCard}>
        <View style={styles.overallText}>
          <Text style={styles.sectionLabel}>OVERALL STATUS</Text>
          <Text style={styles.hostText}>
            {snapshot
              ? `${snapshot.host_platform} host • ${formatTimestamp(snapshot.heartbeat_at)}`
              : 'Waiting for the desktop bridge'}
          </Text>
        </View>
        {snapshot ? (
          <StatusPill value={overallValue} tone={overallTone} />
        ) : (
          <ActivityIndicator color={AIDA_COLORS.cyanGlow} />
        )}
      </GlassPanel>

      {error ? (
        <GlassPanel variant="panel" style={styles.errorCard}>
          <Text style={styles.errorTitle}>STATUS UNAVAILABLE</Text>
          <Text style={styles.errorBody}>{error}</Text>
          <Pressable
            accessibilityRole="button"
            onPress={() => void load(true)}
            style={({ pressed }) => [
              styles.retryButton,
              pressed && styles.pressed,
            ]}
          >
            <Text style={styles.retryText}>RETRY</Text>
          </Pressable>
        </GlassPanel>
      ) : null}

      {attention.length > 0 ? (
        <StatusSection title="NEEDS ATTENTION" items={attention} />
      ) : null}

      <StatusSection
        title={showAll ? 'ALL SYSTEMS' : 'CORE SYSTEMS'}
        items={showAll ? snapshot?.statuses ?? [] : core}
      />

      {snapshot && snapshot.statuses.length > core.length ? (
        <Pressable
          accessibilityRole="button"
          onPress={() => setShowAll((current) => !current)}
          style={({ pressed }) => [
            styles.toggleButton,
            pressed && styles.pressed,
          ]}
        >
          <Text style={styles.toggleText}>
            {showAll ? 'SHOW CORE SYSTEMS' : 'VIEW ALL SYSTEMS'}
          </Text>
        </Pressable>
      ) : null}
    </PageShell>
  );
}

function StatusSection({
  title,
  items,
}: {
  title: string;
  items: SubsystemStatus[];
}) {
  if (items.length === 0) {
    return null;
  }

  return (
    <GlassPanel variant="deep" style={styles.sectionCard}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <View style={styles.rows}>
        {items.map((item, index) => (
          <View
            key={item.id}
            style={[
              styles.statusRow,
              index < items.length - 1 && styles.statusRowBorder,
            ]}
          >
            <Text style={styles.statusName}>{item.label}</Text>
            <StatusPill value={item.value} tone={item.tone} />
          </View>
        ))}
      </View>
    </GlassPanel>
  );
}

function formatTimestamp(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return 'time unavailable';
  }
  return `updated ${parsed.toLocaleTimeString([], {
    hour: 'numeric',
    minute: '2-digit',
  })}`;
}

const styles = StyleSheet.create({
  overallCard: {
    minHeight: 88,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: AIDA_SPACING.sm,
    padding: AIDA_SPACING.md,
  },
  overallText: {
    flex: 1,
    minWidth: 0,
  },
  sectionLabel: {
    color: AIDA_COLORS.cyanStrong,
    fontFamily: AIDA_FONTS.display,
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 1.6,
  },
  hostText: {
    marginTop: 6,
    color: AIDA_COLORS.textMuted,
    fontSize: 12,
  },
  sectionCard: {
    padding: AIDA_SPACING.md,
  },
  sectionTitle: {
    color: AIDA_COLORS.cyanStrong,
    fontFamily: AIDA_FONTS.display,
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 1.6,
  },
  rows: {
    marginTop: AIDA_SPACING.sm,
  },
  statusRow: {
    minHeight: 52,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: AIDA_SPACING.sm,
  },
  statusRowBorder: {
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: AIDA_COLORS.borderSoft,
  },
  statusName: {
    flex: 1,
    color: AIDA_COLORS.textPrimary,
    fontFamily: AIDA_FONTS.display,
    fontSize: 13,
    fontWeight: '600',
    letterSpacing: 0.8,
  },
  toggleButton: {
    minHeight: 46,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: AIDA_COLORS.border,
    borderRadius: AIDA_RADIUS.small,
    backgroundColor: AIDA_COLORS.glassPanel,
  },
  toggleText: {
    color: AIDA_COLORS.cyan,
    fontFamily: AIDA_FONTS.mono,
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 1.2,
  },
  errorCard: {
    padding: AIDA_SPACING.md,
  },
  errorTitle: {
    color: AIDA_COLORS.error,
    fontFamily: AIDA_FONTS.display,
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 1.4,
  },
  errorBody: {
    marginTop: AIDA_SPACING.xs,
    color: AIDA_COLORS.textPrimary,
    fontSize: 13,
    lineHeight: 19,
  },
  retryButton: {
    minHeight: 42,
    marginTop: AIDA_SPACING.sm,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: AIDA_COLORS.borderStrong,
    borderRadius: AIDA_RADIUS.small,
    backgroundColor: AIDA_COLORS.glassInput,
  },
  retryText: {
    color: AIDA_COLORS.cyan,
    fontFamily: AIDA_FONTS.mono,
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 1.2,
  },
  pressed: {
    opacity: 0.7,
  },
});
