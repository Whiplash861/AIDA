import { PropsWithChildren } from 'react';
import { StyleProp, StyleSheet, View, ViewStyle } from 'react-native';

import { AIDA_COLORS, AIDA_RADIUS } from '@/src/theme/aida-theme';

type GlassVariant = 'header' | 'panel' | 'deep' | 'input';

type GlassPanelProps = PropsWithChildren<{
  variant?: GlassVariant;
  style?: StyleProp<ViewStyle>;
}>;

export function GlassPanel({
  children,
  variant = 'panel',
  style,
}: GlassPanelProps) {
  return (
    <View style={[styles.base, styles[variant], style]}>
      <View pointerEvents="none" style={styles.highlight} />
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  base: {
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: AIDA_COLORS.border,
    borderRadius: AIDA_RADIUS.panel,
    shadowColor: AIDA_COLORS.shadow,
    shadowOpacity: 0.12,
    shadowRadius: 20,
    shadowOffset: { width: 0, height: 10 },
    elevation: 4,
  },
  header: {
    backgroundColor: AIDA_COLORS.glassHeader,
  },
  panel: {
    backgroundColor: AIDA_COLORS.glassPanel,
  },
  deep: {
    backgroundColor: AIDA_COLORS.glassPanelDeep,
  },
  input: {
    backgroundColor: AIDA_COLORS.glassInput,
  },
  highlight: {
    position: 'absolute',
    top: 0,
    left: 18,
    right: 18,
    height: 1,
    backgroundColor: 'rgba(215, 247, 255, 0.22)',
  },
});
