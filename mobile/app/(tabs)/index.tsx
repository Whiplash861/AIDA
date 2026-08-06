import { useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';

type Message = {
  id: string;
  sender: 'aida' | 'user';
  text: string;
};

const INITIAL_MESSAGES: Message[] = [
  {
    id: 'welcome',
    sender: 'aida',
    text: 'AIDA mobile interface online. Awaiting directive.',
  },
];

export default function HomeScreen() {
  const [message, setMessage] = useState('');
  const [messages, setMessages] = useState<Message[]>(INITIAL_MESSAGES);

  function sendMessage() {
    const cleanMessage = message.trim();

    if (!cleanMessage) {
      return;
    }

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      sender: 'user',
      text: cleanMessage,
    };

    setMessages((current) => [...current, userMessage]);
    setMessage('');

    setTimeout(() => {
      const response: Message = {
        id: `aida-${Date.now()}`,
        sender: 'aida',
        text: 'Input received. The mobile frontend is operational, but the AIDA backend has not been connected yet.',
      };

      setMessages((current) => [...current, response]);
    }, 500);
  }

  return (
    <SafeAreaView style={styles.safeArea}>
      <StatusBar style="light" />

      <KeyboardAvoidingView
        style={styles.container}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <View style={styles.header}>
          <View>
            <Text style={styles.title}>AIDA</Text>
            <Text style={styles.subtitle}>
              Analytical Intelligent Diagnostic Agent
            </Text>
          </View>

          <View style={styles.statusBadge}>
            <View style={styles.statusDot} />
            <Text style={styles.statusText}>STANDBY</Text>
          </View>
        </View>

        <View style={styles.coreSection}>
          <View style={styles.outerRing}>
            <View style={styles.middleRing}>
              <View style={styles.core}>
                <View style={styles.coreHighlight} />
              </View>
            </View>
          </View>

          <Text style={styles.coreLabel}>MOBILE INTERFACE ACTIVE</Text>
        </View>

        <ScrollView
          style={styles.messageArea}
          contentContainerStyle={styles.messageContent}
          keyboardShouldPersistTaps="handled"
        >
          {messages.map((item) => (
            <View
              key={item.id}
              style={[
                styles.messageBubble,
                item.sender === 'user'
                  ? styles.userBubble
                  : styles.aidaBubble,
              ]}
            >
              <Text style={styles.senderLabel}>
                {item.sender === 'user' ? 'YOU' : 'AIDA'}
              </Text>

              <Text style={styles.messageText}>{item.text}</Text>
            </View>
          ))}
        </ScrollView>

        <View style={styles.composer}>
          <TextInput
            value={message}
            onChangeText={setMessage}
            onSubmitEditing={sendMessage}
            placeholder="Enter directive..."
            placeholderTextColor="#6f8596"
            returnKeyType="send"
            style={styles.input}
          />

          <Pressable
            onPress={sendMessage}
            style={({ pressed }) => [
              styles.sendButton,
              pressed && styles.sendButtonPressed,
            ]}
          >
            <Text style={styles.sendButtonText}>↑</Text>
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: '#071018',
  },
  container: {
    flex: 1,
    paddingHorizontal: 18,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    paddingTop: 12,
    paddingBottom: 14,
    borderBottomWidth: 1,
    borderBottomColor: '#18313f',
  },
  title: {
    color: '#dff8ff',
    fontSize: 27,
    fontWeight: '800',
    letterSpacing: 4,
  },
  subtitle: {
    color: '#688493',
    fontSize: 9,
    marginTop: 4,
    letterSpacing: 0.8,
  },
  statusBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 7,
    marginTop: 7,
    paddingHorizontal: 10,
    paddingVertical: 7,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: '#285165',
    backgroundColor: '#0c1a23',
  },
  statusDot: {
    width: 7,
    height: 7,
    borderRadius: 7,
    backgroundColor: '#48e5ad',
  },
  statusText: {
    color: '#87eec9',
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 1.2,
  },
  coreSection: {
    alignItems: 'center',
    paddingVertical: 24,
  },
  outerRing: {
    width: 118,
    height: 118,
    borderRadius: 59,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: '#1f6985',
    backgroundColor: '#081720',
  },
  middleRing: {
    width: 88,
    height: 88,
    borderRadius: 44,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: '#42c8f5',
    backgroundColor: '#0a202c',
  },
  core: {
    width: 54,
    height: 54,
    borderRadius: 27,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#4fdcff',
    shadowColor: '#4fdcff',
    shadowOpacity: 0.8,
    shadowRadius: 18,
    shadowOffset: {
      width: 0,
      height: 0,
    },
  },
  coreHighlight: {
    width: 20,
    height: 20,
    borderRadius: 10,
    backgroundColor: '#d8f9ff',
    opacity: 0.85,
  },
  coreLabel: {
    color: '#55c9eb',
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 2,
    marginTop: 14,
  },
  messageArea: {
    flex: 1,
  },
  messageContent: {
    paddingBottom: 16,
    gap: 12,
  },
  messageBubble: {
    maxWidth: '88%',
    paddingHorizontal: 15,
    paddingVertical: 12,
    borderRadius: 15,
    borderWidth: 1,
  },
  aidaBubble: {
    alignSelf: 'flex-start',
    backgroundColor: '#0d202b',
    borderColor: '#24516a',
    borderTopLeftRadius: 4,
  },
  userBubble: {
    alignSelf: 'flex-end',
    backgroundColor: '#153846',
    borderColor: '#327892',
    borderTopRightRadius: 4,
  },
  senderLabel: {
    color: '#54cbe9',
    fontSize: 9,
    fontWeight: '800',
    letterSpacing: 1.5,
    marginBottom: 5,
  },
  messageText: {
    color: '#d8e7ed',
    fontSize: 15,
    lineHeight: 21,
  },
  composer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingVertical: 12,
    borderTopWidth: 1,
    borderTopColor: '#18313f',
  },
  input: {
    flex: 1,
    height: 48,
    paddingHorizontal: 16,
    color: '#e5f8ff',
    backgroundColor: '#0c1a23',
    borderWidth: 1,
    borderColor: '#24495b',
    borderRadius: 24,
    fontSize: 15,
  },
  sendButton: {
    width: 48,
    height: 48,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 24,
    backgroundColor: '#36bfe9',
  },
  sendButtonPressed: {
    opacity: 0.7,
    transform: [{ scale: 0.96 }],
  },
  sendButtonText: {
    color: '#041016',
    fontSize: 25,
    fontWeight: '800',
    marginBottom: 3,
  },
});