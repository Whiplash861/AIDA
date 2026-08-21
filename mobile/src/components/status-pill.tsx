import { StyleSheet, Text, View } from 'react-native';

import { StatusTone } from '@/src/core/runtime/aida-runtime';
import {
  AIDA_COLORS,
  AIDA_FONTS,
  AIDA_RADIUS,
} from '@/src/theme/aida-theme';

type StatusPillProps = {
  value: string;
  tone: StatusTone;
};

const TONES: Record<
  StatusTone,
  { foreground: string; background: string; border: string }
> = {
  ready: {
    foreground: AIDA_COLORS.mint,
    background: 'rgba(9, 42, 34, 0.90)',
    border: 'rgba(77, 236, 171, 0.42)',
  },
  active: {
    foreground: AIDA_COLORS.cyanGlow,
    background: 'rgba(8, 39, 59, 0.92)',
    border: 'rgba(88, 207, 255, 0.48)',
  },
  warning: {
    foreground: AIDA_COLORS.warning,
    background: 'rgba(48, 36, 12, 0.92)',
    border: 'rgba(255, 205, 91, 0.47)',
  },
  error: {
    foreground: AIDA_COLORS.error,
    background: 'rgba(49, 18, 25, 0.92)',
    border: 'rgba(255, 105, 126, 0.49)',
  },
  idle: {
    foreground: '#a9bbc8',
    background: 'rgba(25, 35, 43, 0.92)',
    border: 'rgba(136, 166, 187, 0.30)',
  },
  offline: {
    foreground: '#a9bbc8',
    background: 'rgba(25, 35, 43, 0.92)',
    border: 'rgba(136, 166, 187, 0.30)',
  },
};

export function StatusPill({ value, tone }: StatusPillProps) {
  const palette = TONES[tone];

  return (
    <View
      style={[
        styles.container,
        {
          backgroundColor: palette.background,
          borderColor: palette.border,
        },
      ]}
    >
      <Text style={[styles.text, { color: palette.foreground }]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    minHeight: 30,
    maxWidth: 150,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderRadius: AIDA_RADIUS.pill,
    paddingHorizontal: 11,
    paddingVertical: 6,
  },
  text: {
    fontFamily: AIDA_FONTS.mono,
    fontSize: 9,
    fontWeight: '700',
    letterSpacing: 0.8,
  },
});
