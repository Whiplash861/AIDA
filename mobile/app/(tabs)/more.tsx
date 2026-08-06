import { StyleSheet, Text, View } from 'react-native';

import { GlassPanel } from '@/src/components/glass-panel';
import { PageShell } from '@/src/components/page-shell';
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
  tone: 'next' | 'protected';
};

const GROUPS: { title: string; items: OperationRow[] }[] = [
  {
    title: 'OVERSIGHT',
    items: [
      {
        title: 'Tasks',
        detail: 'Durable background assistance and progress.',
        badge: 'NEXT',
        tone: 'next',
      },
      {
        title: 'Threats',
        detail: 'Findings, evidence, and response plans.',
        badge: 'NEXT',
        tone: 'next',
      },
      {
        title: 'Artificer',
        detail: 'Reviews, proposals, risk, and audit history.',
        badge: 'NEXT',
        tone: 'next',
      },
    ],
  },
  {
    title: 'KNOWLEDGE & SUPPORT',
    items: [
      {
        title: 'Memory',
        detail: 'Saved findings, preferences, and procedures.',
        badge: 'NEXT',
        tone: 'next',
      },
      {
        title: 'Report Bug',
        detail: 'Submit notes and screenshots to the developer.',
        badge: 'NEXT',
        tone: 'next',
      },
    ],
  },
  {
    title: 'AUTHORITY',
    items: [
      {
        title: 'Autonomy',
        detail: 'Remote authority changes require reauthentication.',
        badge: 'PROTECTED',
        tone: 'protected',
      },
    ],
  },
];

export default function MoreScreen() {
  return (
    <PageShell
      title="More"
      subtitle="Operational tools, grouped without crowding the primary AIDA interface."
    >
      <GlassPanel variant="header" style={styles.noticeCard}>
        <Text style={styles.noticeTitle}>EARLY ALPHA CONTROL BOUNDARY</Text>
        <Text style={styles.noticeBody}>
          Status and activity are live and read-only. Consequential controls
          remain unavailable until mobile reauthentication and confirmation are
          implemented.
        </Text>
      </GlassPanel>

      {GROUPS.map((group) => (
        <GlassPanel key={group.title} variant="deep" style={styles.groupCard}>
          <Text style={styles.groupTitle}>{group.title}</Text>
          <View style={styles.rows}>
            {group.items.map((item, index) => (
              <View
                key={item.title}
                style={[
                  styles.row,
                  index < group.items.length - 1 && styles.rowBorder,
                ]}
              >
                <View style={styles.rowText}>
                  <Text style={styles.rowTitle}>{item.title}</Text>
                  <Text style={styles.rowDetail}>{item.detail}</Text>
                </View>

                <View
                  style={[
                    styles.badge,
                    item.tone === 'protected'
                      ? styles.protectedBadge
                      : styles.nextBadge,
                  ]}
                >
                  <Text
                    style={[
                      styles.badgeText,
                      item.tone === 'protected'
                        ? styles.protectedText
                        : styles.nextText,
                    ]}
                  >
                    {item.badge}
                  </Text>
                </View>
              </View>
            ))}
          </View>
        </GlassPanel>
      ))}
    </PageShell>
  );
}

const styles = StyleSheet.create({
  noticeCard: {
    padding: AIDA_SPACING.md,
  },
  noticeTitle: {
    color: AIDA_COLORS.cyanStrong,
    fontFamily: AIDA_FONTS.display,
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 1.5,
  },
  noticeBody: {
    marginTop: AIDA_SPACING.xs,
    color: AIDA_COLORS.textPrimary,
    fontSize: 13,
    lineHeight: 20,
  },
  groupCard: {
    padding: AIDA_SPACING.md,
  },
  groupTitle: {
    color: AIDA_COLORS.cyanStrong,
    fontFamily: AIDA_FONTS.display,
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 1.6,
  },
  rows: {
    marginTop: AIDA_SPACING.sm,
  },
  row: {
    minHeight: 68,
    flexDirection: 'row',
    alignItems: 'center',
    gap: AIDA_SPACING.sm,
  },
  rowBorder: {
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: AIDA_COLORS.borderSoft,
  },
  rowText: {
    flex: 1,
    minWidth: 0,
  },
  rowTitle: {
    color: AIDA_COLORS.textBright,
    fontFamily: AIDA_FONTS.display,
    fontSize: 14,
    fontWeight: '700',
    letterSpacing: 0.7,
  },
  rowDetail: {
    marginTop: 4,
    color: AIDA_COLORS.textMuted,
    fontSize: 12,
    lineHeight: 18,
  },
  badge: {
    minHeight: 28,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderRadius: AIDA_RADIUS.pill,
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  nextBadge: {
    backgroundColor: 'rgba(8, 39, 59, 0.88)',
    borderColor: 'rgba(88, 207, 255, 0.42)',
  },
  protectedBadge: {
    backgroundColor: 'rgba(48, 36, 12, 0.88)',
    borderColor: 'rgba(255, 205, 91, 0.42)',
  },
  badgeText: {
    fontFamily: AIDA_FONTS.mono,
    fontSize: 8,
    fontWeight: '700',
    letterSpacing: 0.8,
  },
  nextText: {
    color: AIDA_COLORS.cyanGlow,
  },
  protectedText: {
    color: AIDA_COLORS.warning,
  },
});
