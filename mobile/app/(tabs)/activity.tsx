import { useFocusEffect } from '@react-navigation/native';
import { useCallback, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { GlassPanel } from '@/src/components/glass-panel';
import { PageShell } from '@/src/components/page-shell';
import {
  getRuntimeActivity,
  RuntimeActivityItem,
} from '@/src/core/runtime/aida-runtime';
import {
  AIDA_COLORS,
  AIDA_FONTS,
  AIDA_RADIUS,
  AIDA_SPACING,
} from '@/src/theme/aida-theme';

const SEVERITY = {
  info: {
    foreground: AIDA_COLORS.cyanGlow,
    background: 'rgba(8, 39, 59, 0.82)',
  },
  warning: {
    foreground: AIDA_COLORS.warning,
    background: 'rgba(48, 36, 12, 0.84)',
  },
  error: {
    foreground: AIDA_COLORS.error,
    background: 'rgba(49, 18, 25, 0.86)',
  },
} as const;

export default function ActivityScreen() {
  const [items, setItems] = useState<RuntimeActivityItem[]>(() =>
    getRuntimeActivity(30),
  );

  const load = useCallback(() => {
    setItems([...getRuntimeActivity(30)]);
  }, []);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );

  return (
    <PageShell
      title="Activity"
      subtitle="Recent events produced by this device-local AIDA runtime."
      onRefresh={load}
    >
      {items.length === 0 ? (
        <GlassPanel variant="deep" style={styles.emptyCard}>
          <Text style={styles.emptyTitle}>NO RECENT ACTIVITY</Text>
          <Text style={styles.emptyBody}>
            Local runtime events, diagnostics, Engine activity, and warnings will
            appear here as this Android instance develops.
          </Text>
        </GlassPanel>
      ) : null}

      {items.map((item) => (
        <ActivityCard key={item.id} item={item} />
      ))}
    </PageShell>
  );
}

function ActivityCard({ item }: { item: RuntimeActivityItem }) {
  const palette = SEVERITY[item.severity];

  return (
    <GlassPanel variant="deep" style={styles.activityCard}>
      <View style={styles.activityHeader}>
        <View
          style={[
            styles.categoryBadge,
            { backgroundColor: palette.background },
          ]}
        >
          <View
            style={[
              styles.severityDot,
              { backgroundColor: palette.foreground },
            ]}
          />
          <Text
            style={[
              styles.categoryText,
              { color: palette.foreground },
            ]}
          >
            {item.category}
          </Text>
        </View>

        <Text style={styles.timestamp}>{formatTimestamp(item.created_at)}</Text>
      </View>

      <Text style={styles.message}>{item.message}</Text>
      <Text style={styles.source}>SOURCE • {item.source.toUpperCase()}</Text>
    </GlassPanel>
  );
}

function formatTimestamp(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return 'TIME UNKNOWN';
  }

  const today = new Date();
  const sameDay = parsed.toDateString() === today.toDateString();
  if (sameDay) {
    return parsed.toLocaleTimeString([], {
      hour: 'numeric',
      minute: '2-digit',
    });
  }
  return parsed.toLocaleDateString([], {
    month: 'short',
    day: 'numeric',
  });
}

const styles = StyleSheet.create({
  activityCard: {
    padding: AIDA_SPACING.md,
  },
  activityHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: AIDA_SPACING.sm,
  },
  categoryBadge: {
    minHeight: 28,
    maxWidth: '68%',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
    borderRadius: AIDA_RADIUS.pill,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  severityDot: {
    width: 7,
    height: 7,
    borderRadius: 4,
  },
  categoryText: {
    flexShrink: 1,
    fontFamily: AIDA_FONTS.mono,
    fontSize: 9,
    fontWeight: '700',
    letterSpacing: 0.8,
  },
  timestamp: {
    color: AIDA_COLORS.textDim,
    fontFamily: AIDA_FONTS.mono,
    fontSize: 9,
  },
  message: {
    marginTop: AIDA_SPACING.sm,
    color: AIDA_COLORS.textPrimary,
    fontSize: 14,
    lineHeight: 20,
  },
  source: {
    marginTop: AIDA_SPACING.sm,
    color: AIDA_COLORS.textDim,
    fontFamily: AIDA_FONTS.mono,
    fontSize: 8,
    letterSpacing: 0.8,
  },
  emptyCard: {
    padding: AIDA_SPACING.lg,
  },
  emptyTitle: {
    color: AIDA_COLORS.cyanStrong,
    fontFamily: AIDA_FONTS.display,
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 1.4,
  },
  emptyBody: {
    marginTop: AIDA_SPACING.xs,
    color: AIDA_COLORS.textMuted,
    fontSize: 13,
    lineHeight: 20,
  },
});
