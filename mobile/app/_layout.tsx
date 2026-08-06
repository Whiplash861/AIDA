import { DarkTheme, ThemeProvider } from '@react-navigation/native';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import 'react-native-reanimated';

import { AIDA_COLORS } from '@/src/theme/aida-theme';

const AIDA_NAVIGATION_THEME = {
  ...DarkTheme,
  colors: {
    ...DarkTheme.colors,
    primary: AIDA_COLORS.cyan,
    background: AIDA_COLORS.canvas,
    card: AIDA_COLORS.glassHeader,
    text: AIDA_COLORS.textPrimary,
    border: AIDA_COLORS.border,
    notification: AIDA_COLORS.cyanGlow,
  },
};

export const unstable_settings = {
  anchor: '(tabs)',
};

export default function RootLayout() {
  return (
    <ThemeProvider value={AIDA_NAVIGATION_THEME}>
      <Stack screenOptions={{ headerShown: false }}>
        <Stack.Screen name="(tabs)" />
      </Stack>
      <StatusBar style="light" />
    </ThemeProvider>
  );
}
