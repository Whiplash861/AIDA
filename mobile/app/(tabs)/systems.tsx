import { useFocusEffect } from '@react-navigation/native';
import { useCallback, useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { GlassPanel } from '@/src/components/glass-panel';
import { PageShell } from '@/src/components/page-shell';
import { StatusPill } from '@/src/components/status-pill';
import {
  getRuntimeSnapshot,
  MobileRuntimeSnapshot,
  StatusTone,
  SubsystemStatus,
} from '@/src/core/runtime/aida-runtime';
import {
  AIDA_COLORS,
  AIDA_FONTS,
  AIDA_RADIUS,
  AIDA_SPACING,
} from '@/src/theme/aida-theme';

const CORE_IDS = new Set([
  'agent',
  'brain',
  'memory',
  'artificer',
  'technomancer',
  'platform',
]);

export default function SystemsScreen() {
  const [snapshot, setSnapshot] = useState<MobileRuntimeSnapshot>(() =>
    getRuntimeSnapshot(),
  );
  const [showAll, setShowAll] = useState(false);

  const load = useCallback(() => {
    setSnapshot({ ...getRuntimeSnapshot() });
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  const attention = useMemo(
    () =>
      snapshot.statuses.filter((item) => {
        if (item.id === 'tasks' && item.value === '0 ACTIVE') {
          return false;
        }
        return ['warning', 'error', 'active'].includes(item.tone);
      }),
    [snapshot],
  );

  const core = useMemo(
    () => snapshot.statuses.filter((item) => CORE_IDS.has(item.id)),
    [snapshot],
  );

  const overallTone: StatusTone = attention.some((item) => item.tone === 'error')
    ? 'error'
    : attention.some((item) => item.tone === 'warning')
      ? 'warning'
      : attention.some((item) => item.tone === 'active')
        ? 'active'
        : 'ready';

  const overallValue =
    overallTone === 'ready'
      ? 'READY'
      : overallTone === 'active'
        ? 'ACTIVE'
        : 'ATTENTION';

  return (
    <PageShell
      title="Systems"
      subtitle="Device-local status for this AIDA mobile instance."
      onRefresh={load}
    >
      <GlassPanel variant="header" style={styles.overallCard}>
        <View style={styles.overallText}>
          <Text style={styles.sectionLabel}>LOCAL INSTANCE</Text>
          <Text style={styles.hostText}>
            {snapshot.platform} {snapshot.platform_version} • {snapshot.device_model}
          </Text>
          <Text style={styles.instanceText} numberOfLines={1}>
            {snapshot.instance_id}
          </Text>
        </View>
        <StatusPill value={overallValue} tone={overallTone} />
      </GlassPanel>

      {attention.length > 0 ? (
        <StatusSection title="CURRENT ATTENTION" items={attention} />
      ) : null}

      <StatusSection
        title={showAll ? 'ALL SYSTEMS' : 'CORE SYSTEMS'}
        items={showAll ? snapshot.statuses : core}
      />

      <GlassPanel variant="deep" style={styles.capabilityCard}>
        <Text style={styles.sectionTitle}>CAPABILITY REGISTRY</Text>
        <View style={styles.capabilityRows}>
          {snapshot.capabilities.map((item, index) => (
            <View
              key={item.id}
              style={[
                styles.capabilityRow,
                index < snapshot.capabilities.length - 1 && styles.statusRowBorder,
              ]}
            >
              <View style={styles.capabilityText}>
                <Text style={styles.statusName}>{item.label}</Text>
                <Text style={styles.capabilityDetail}>{item.detail}</Text>
              </View>
              <StatusPill
                value={item.state.toUpperCase()}
                tone={
                  item.state === 'supported'
                    ? 'ready'
                    : item.state === 'limited'
                      ? 'warning'
                      : 'idle'
                }
              />
            </View>
          ))}
        </View>
      </GlassPanel>

      {snapshot.statuses.length > core.length ? (
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

const styles = StyleSheet.create({
  overallCard: {
    minHeight: 100,
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
    color: AIDA_COLORS.textPrimary,
    fontSize: 13,
  },
  instanceText: {
    marginTop: 5,
    color: AIDA_COLORS.textDim,
    fontFamily: AIDA_FONTS.mono,
    fontSize: 8,
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
  capabilityCard: {
    padding: AIDA_SPACING.md,
  },
  capabilityRows: {
    marginTop: AIDA_SPACING.sm,
  },
  capabilityRow: {
    minHeight: 78,
    flexDirection: 'row',
    alignItems: 'center',
    gap: AIDA_SPACING.sm,
    paddingVertical: AIDA_SPACING.xs,
  },
  capabilityText: {
    flex: 1,
    minWidth: 0,
  },
  capabilityDetail: {
    marginTop: 4,
    color: AIDA_COLORS.textMuted,
    fontSize: 12,
    lineHeight: 18,
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
  pressed: {
    opacity: 0.7,
  },
});
