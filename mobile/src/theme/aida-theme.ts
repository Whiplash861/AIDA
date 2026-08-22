import { Platform } from 'react-native';

export type AidaRuntimeStatus =
  | 'CONNECTING'
  | 'STANDBY'
  | 'LISTENING'
  | 'ANALYZING'
  | 'SPEAKING'
  | 'WARNING'
  | 'OFFLINE'
  | 'ERROR'
  | 'SHUTDOWN';

export const AIDA_COLORS = {
  canvas: '#05090f',
  canvasDeep: '#04090f',
  canvasMid: '#06101a',
  textPrimary: '#eaf6ff',
  textBright: '#f5fbff',
  textMuted: '#8da3b3',
  textDim: '#768c9c',
  cyan: '#64d8ff',
  cyanStrong: '#66d9ff',
  cyanGlow: '#68d8ff',
  mint: '#59f0b3',
  warning: '#ffd875',
  error: '#ff7d8d',
  purple: '#c58aff',
  glassHeader: 'rgba(14, 31, 45, 0.92)',
  glassPanel: 'rgba(12, 27, 40, 0.91)',
  glassPanelDeep: 'rgba(7, 18, 28, 0.95)',
  glassInput: 'rgba(5, 17, 27, 0.91)',
  glassAida: 'rgba(8, 30, 39, 0.94)',
  glassUser: 'rgba(38, 27, 62, 0.94)',
  glassSystem: 'rgba(10, 28, 43, 0.94)',
  border: 'rgba(112, 210, 255, 0.32)',
  borderSoft: 'rgba(105, 196, 239, 0.27)',
  borderStrong: 'rgba(102, 217, 255, 0.80)',
  borderPurple: 'rgba(177, 118, 244, 0.42)',
  shadow: '#36c8ff',
} as const;

export const AIDA_RADIUS = {
  small: 12,
  card: 14,
  panel: 18,
  pill: 999,
} as const;

export const AIDA_SPACING = {
  xxs: 4,
  xs: 8,
  sm: 12,
  md: 16,
  lg: 20,
  xl: 28,
} as const;

export const AIDA_FONTS = {
  display: Platform.select({
    ios: 'Avenir Next Condensed',
    android: 'sans-serif-condensed',
    default: undefined,
  }),
  mono: Platform.select({
    ios: 'Menlo',
    android: 'monospace',
    default: undefined,
  }),
} as const;

export const AIDA_STATUS_TONES: Record<
  AidaRuntimeStatus,
  { foreground: string; background: string; border: string }
> = {
  CONNECTING: {
    foreground: AIDA_COLORS.cyanGlow,
    background: 'rgba(8, 39, 59, 0.90)',
    border: 'rgba(88, 207, 255, 0.47)',
  },
  STANDBY: {
    foreground: AIDA_COLORS.mint,
    background: 'rgba(9, 42, 34, 0.90)',
    border: 'rgba(77, 236, 171, 0.42)',
  },
  LISTENING: {
    foreground: AIDA_COLORS.purple,
    background: 'rgba(42, 24, 62, 0.92)',
    border: 'rgba(197, 138, 255, 0.50)',
  },
  ANALYZING: {
    foreground: AIDA_COLORS.cyanGlow,
    background: 'rgba(8, 39, 59, 0.92)',
    border: 'rgba(88, 207, 255, 0.55)',
  },
  SPEAKING: {
    foreground: AIDA_COLORS.cyanStrong,
    background: 'rgba(9, 44, 60, 0.92)',
    border: 'rgba(102, 217, 255, 0.62)',
  },
  WARNING: {
    foreground: AIDA_COLORS.warning,
    background: 'rgba(48, 36, 12, 0.92)',
    border: 'rgba(255, 205, 91, 0.47)',
  },
  OFFLINE: {
    foreground: '#a9bbc8',
    background: 'rgba(25, 35, 43, 0.92)',
    border: 'rgba(136, 166, 187, 0.30)',
  },
  ERROR: {
    foreground: AIDA_COLORS.error,
    background: 'rgba(49, 18, 25, 0.92)',
    border: 'rgba(255, 105, 126, 0.49)',
  },
  SHUTDOWN: {
    foreground: AIDA_COLORS.textDim,
    background: 'rgba(20, 25, 31, 0.94)',
    border: 'rgba(118, 140, 156, 0.30)',
  },
};
