import { Stack } from 'expo-router';

export default function MobileLayout() {
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        animation: 'fade',
        contentStyle: { backgroundColor: '#05090f' },
      }}
    />
  );
}
