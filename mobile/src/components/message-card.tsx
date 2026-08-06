import { StyleSheet, Text, View } from 'react-native';

import {
  AIDA_COLORS,
  AIDA_FONTS,
  AIDA_RADIUS,
} from '@/src/theme/aida-theme';

export type MobileMessage = {
  id: string;
  sender: 'aida' | 'user' | 'system';
  text: string;
};

type MessageCardProps = {
  message: MobileMessage;
};

export function MessageCard({ message }: MessageCardProps) {
  const isUser = message.sender === 'user';

  return (
    <View
      style={[
        styles.card,
        styles[message.sender],
        isUser ? styles.alignRight : styles.alignLeft,
      ]}
    >
      <Text style={[styles.sender, senderStyles[message.sender]]}>
        {message.sender === 'user' ? 'YOU' : message.sender.toUpperCase()}
      </Text>
      <Text style={styles.body}>{message.text}</Text>
    </View>
  );
}

const senderStyles = {
  aida: { color: '#65e6ef' },
  user: { color: AIDA_COLORS.purple },
  system: { color: '#62cfff' },
} as const;

const styles = StyleSheet.create({
  card: {
    maxWidth: '90%',
    borderWidth: 1,
    borderRadius: AIDA_RADIUS.card,
    paddingHorizontal: 15,
    paddingVertical: 12,
  },
  alignLeft: {
    alignSelf: 'flex-start',
    borderTopLeftRadius: 4,
  },
  alignRight: {
    alignSelf: 'flex-end',
    borderTopRightRadius: 4,
  },
  aida: {
    backgroundColor: AIDA_COLORS.glassAida,
    borderColor: 'rgba(92, 218, 232, 0.36)',
  },
  user: {
    backgroundColor: AIDA_COLORS.glassUser,
    borderColor: AIDA_COLORS.borderPurple,
  },
  system: {
    backgroundColor: AIDA_COLORS.glassSystem,
    borderColor: 'rgba(85, 176, 224, 0.32)',
  },
  sender: {
    marginBottom: 5,
    fontFamily: AIDA_FONTS.display,
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 1.4,
  },
  body: {
    color: AIDA_COLORS.textPrimary,
    fontSize: 15,
    lineHeight: 21,
  },
});
