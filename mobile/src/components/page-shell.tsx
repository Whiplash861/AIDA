import { PropsWithChildren } from 'react';
import {
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import {
  AIDA_COLORS,
  AIDA_FONTS,
  AIDA_SPACING,
} from '@/src/theme/aida-theme';

type PageShellProps = PropsWithChildren<{
  title: string;
  subtitle: string;
  refreshing?: boolean;
  onRefresh?: () => void;
}>;

export function PageShell({
  title,
  subtitle,
  refreshing = false,
  onRefresh,
  children,
}: PageShellProps) {
  return (
    <SafeAreaView style={styles.safeArea}>
      <View pointerEvents="none" style={styles.backgroundGlowPrimary} />
      <View pointerEvents="none" style={styles.backgroundGlowSecondary} />

      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          onRefresh ? (
            <RefreshControl
              refreshing={refreshing}
              onRefresh={onRefresh}
              tintColor={AIDA_COLORS.cyanGlow}
            />
          ) : undefined
        }
      >
        <View style={styles.header}>
          <Text style={styles.eyebrow}>AIDA MOBILE</Text>
          <Text style={styles.title}>{title}</Text>
          <Text style={styles.subtitle}>{subtitle}</Text>
        </View>

        {children}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: AIDA_COLORS.canvas,
  },
  content: {
    flexGrow: 1,
    gap: AIDA_SPACING.sm,
    paddingHorizontal: AIDA_SPACING.sm,
    paddingTop: AIDA_SPACING.sm,
    paddingBottom: AIDA_SPACING.xl,
  },
  header: {
    paddingHorizontal: AIDA_SPACING.xs,
    paddingVertical: AIDA_SPACING.sm,
  },
  eyebrow: {
    color: AIDA_COLORS.cyan,
    fontFamily: AIDA_FONTS.mono,
    fontSize: 9,
    fontWeight: '700',
    letterSpacing: 2,
  },
  title: {
    marginTop: 4,
    color: AIDA_COLORS.textBright,
    fontFamily: AIDA_FONTS.display,
    fontSize: 28,
    fontWeight: '700',
    letterSpacing: 2,
  },
  subtitle: {
    marginTop: 4,
    color: AIDA_COLORS.textMuted,
    fontSize: 13,
    lineHeight: 19,
  },
  backgroundGlowPrimary: {
    position: 'absolute',
    top: -120,
    left: -140,
    width: 340,
    height: 340,
    borderRadius: 170,
    backgroundColor: 'rgba(27, 89, 119, 0.28)',
  },
  backgroundGlowSecondary: {
    position: 'absolute',
    right: -180,
    bottom: 30,
    width: 360,
    height: 360,
    borderRadius: 180,
    backgroundColor: 'rgba(32, 43, 100, 0.14)',
  },
});
