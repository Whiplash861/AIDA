import { useFocusEffect } from '@react-navigation/native';
import { useCallback, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { GlassPanel } from '@/src/components/glass-panel';
import { PageShell } from '@/src/components/page-shell';
import {
  ActivityItem,
  getActivity,
} from '@/src/services/aida-api';
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
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (manual = false) => {
    if (manual) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }

    try {
      const response = await getActivity(30);
      setItems(response.items);
      setError('');
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : 'Unable to load AIDA activity.',
      );
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  return (
    <PageShell
      title="Activity"
      subtitle="Recent operational events from AIDA's desktop runtime."
      refreshing={refreshing}
      onRefresh={() => void load(true)}
    >
      {loading && items.length === 0 ? (
        <GlassPanel variant="deep" style={styles.loadingCard}>
          <ActivityIndicator color={AIDA_COLORS.cyanGlow} />
          <Text style={styles.loadingText}>READING ACTIVITY STREAM</Text>
        </GlassPanel>
      ) : null}

      {error ? (
        <GlassPanel variant="panel" style={styles.errorCard}>
          <Text style={styles.errorTitle}>ACTIVITY UNAVAILABLE</Text>
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

      {!loading && !error && items.length === 0 ? (
        <GlassPanel variant="deep" style={styles.emptyCard}>
          <Text style={styles.emptyTitle}>NO RECENT ACTIVITY</Text>
          <Text style={styles.emptyBody}>
            New scans, Artificer reviews, task events, and warnings will appear
            here.
          </Text>
        </GlassPanel>
      ) : null}

      {items.map((item) => (
        <ActivityCard key={item.id} item={item} />
      ))}
    </PageShell>
  );
}

function ActivityCard({ item }: { item: ActivityItem }) {
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
  loadingCard: {
    minHeight: 110,
    alignItems: 'center',
    justifyContent: 'center',
    gap: AIDA_SPACING.sm,
  },
  loadingText: {
    color: AIDA_COLORS.textMuted,
    fontFamily: AIDA_FONTS.mono,
    fontSize: 9,
    fontWeight: '700',
    letterSpacing: 1.3,
  },
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
