import { useEffect, useRef } from 'react';
import { Animated, StyleSheet, Text, View } from 'react-native';

import {
  AIDA_COLORS,
  AIDA_FONTS,
  AIDA_STATUS_TONES,
  AidaRuntimeStatus,
} from '@/src/theme/aida-theme';

type StatusCoreProps = {
  status: AidaRuntimeStatus;
};

export function StatusCore({ status }: StatusCoreProps) {
  const pulse = useRef(new Animated.Value(0)).current;
  const tone = AIDA_STATUS_TONES[status];

  useEffect(() => {
    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, {
          toValue: 1,
          duration: status === 'ANALYZING' ? 650 : 1_250,
          useNativeDriver: true,
        }),
        Animated.timing(pulse, {
          toValue: 0,
          duration: status === 'ANALYZING' ? 650 : 1_250,
          useNativeDriver: true,
        }),
      ]),
    );

    animation.start();
    return () => animation.stop();
  }, [pulse, status]);

  const scale = pulse.interpolate({
    inputRange: [0, 1],
    outputRange: [0.94, 1.06],
  });
  const opacity = pulse.interpolate({
    inputRange: [0, 1],
    outputRange: [0.45, 0.9],
  });

  return (
    <View style={styles.wrapper}>
      <Animated.View
        style={[
          styles.ambient,
          {
            backgroundColor: tone.foreground,
            opacity,
            transform: [{ scale }],
          },
        ]}
      />
      <View style={[styles.outerRing, { borderColor: tone.border }]}>
        <View style={[styles.middleRing, { borderColor: tone.foreground }]}>
          <Animated.View
            style={[
              styles.core,
              {
                backgroundColor: tone.foreground,
                shadowColor: tone.foreground,
                transform: [{ scale }],
              },
            ]}
          >
            <View style={styles.coreHighlight} />
          </Animated.View>
        </View>
      </View>
      <Text style={[styles.label, { color: tone.foreground }]}>
        MOBILE INTERFACE ACTIVE
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 18,
  },
  ambient: {
    position: 'absolute',
    top: 28,
    width: 118,
    height: 118,
    borderRadius: 59,
  },
  outerRing: {
    width: 124,
    height: 124,
    borderRadius: 62,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    backgroundColor: 'rgba(4, 15, 23, 0.88)',
  },
  middleRing: {
    width: 92,
    height: 92,
    borderRadius: 46,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    backgroundColor: 'rgba(7, 26, 38, 0.94)',
  },
  core: {
    width: 56,
    height: 56,
    borderRadius: 28,
    alignItems: 'center',
    justifyContent: 'center',
    shadowOpacity: 0.85,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 0 },
    elevation: 10,
  },
  coreHighlight: {
    width: 20,
    height: 20,
    borderRadius: 10,
    backgroundColor: AIDA_COLORS.textBright,
    opacity: 0.78,
  },
  label: {
    marginTop: 14,
    fontFamily: AIDA_FONTS.mono,
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 2,
  },
});
