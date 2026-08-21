import Ionicons from '@expo/vector-icons/Ionicons';
import { Tabs } from 'expo-router';
import { ComponentProps } from 'react';

import {
  AIDA_COLORS,
  AIDA_FONTS,
} from '@/src/theme/aida-theme';

type IconName = ComponentProps<typeof Ionicons>['name'];

const ICONS: Record<string, IconName> = {
  index: 'chatbubble-ellipses-outline',
  systems: 'pulse-outline',
  activity: 'time-outline',
  more: 'grid-outline',
};

export default function MobileLayout() {
  return (
    <Tabs
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarHideOnKeyboard: true,
        tabBarActiveTintColor: AIDA_COLORS.cyanGlow,
        tabBarInactiveTintColor: AIDA_COLORS.textDim,
        tabBarStyle: {
          height: 72,
          paddingTop: 8,
          paddingBottom: 8,
          backgroundColor: AIDA_COLORS.glassHeader,
          borderTopColor: AIDA_COLORS.border,
        },
        tabBarLabelStyle: {
          fontFamily: AIDA_FONTS.mono,
          fontSize: 9,
          fontWeight: '700',
          letterSpacing: 0.5,
        },
        tabBarIcon: ({ color, size }) => (
          <Ionicons
            name={ICONS[route.name] ?? 'ellipse-outline'}
            color={color}
            size={size}
          />
        ),
      })}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: 'AIDA',
        }}
      />
      <Tabs.Screen
        name="systems"
        options={{
          title: 'Systems',
        }}
      />
      <Tabs.Screen
        name="activity"
        options={{
          title: 'Activity',
        }}
      />
      <Tabs.Screen
        name="more"
        options={{
          title: 'Control',
        }}
      />
    </Tabs>
  );
}
