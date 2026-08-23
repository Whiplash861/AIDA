import { EngineSubprocessDefinition, EngineSubprocessState } from '@/src/core/engines/types';

export type AegisProviderExecutor = (
  input?: unknown,
) => Promise<unknown> | unknown;

export type AegisProviderSlot = {
  subprocess: EngineSubprocessDefinition;
  state: EngineSubprocessState;
  executor: AegisProviderExecutor | null;
};

export type AegisProviderSnapshot = {
  id: string;
  label: string;
  state: EngineSubprocessState;
  provider: string;
  executable: boolean;
  detail: string;
};

export class AegisAndroidProviderRegistry {
  private readonly slots = new Map<string, AegisProviderSlot>();

  constructor(subprocesses: readonly EngineSubprocessDefinition[]) {
    for (const subprocess of subprocesses) {
      this.slots.set(subprocess.id, {
        subprocess,
        state: subprocess.state,
        executor: null,
      });
    }
  }

  register(
    subprocessId: string,
    executor: AegisProviderExecutor,
    state: EngineSubprocessState = 'supported',
  ): void {
    const slot = this.requireSlot(subprocessId);
    this.slots.set(subprocessId, {
      ...slot,
      state,
      executor,
    });
  }

  unregister(subprocessId: string, state: EngineSubprocessState = 'staged'): void {
    const slot = this.requireSlot(subprocessId);
    this.slots.set(subprocessId, {
      ...slot,
      state,
      executor: null,
    });
  }

  setState(subprocessId: string, state: EngineSubprocessState): void {
    const slot = this.requireSlot(subprocessId);
    this.slots.set(subprocessId, {
      ...slot,
      state,
    });
  }

  get(subprocessId: string): AegisProviderSlot | null {
    return this.slots.get(subprocessId) ?? null;
  }

  canExecute(subprocessId: string): boolean {
    const slot = this.slots.get(subprocessId);
    return Boolean(slot?.executor && slot.state !== 'staged');
  }

  async execute(subprocessId: string, input?: unknown): Promise<unknown> {
    const slot = this.requireSlot(subprocessId);
    if (!slot.executor || slot.state === 'staged') {
      throw new Error(
        `Aegis subprocess ${subprocessId} is ${slot.state} on the Android provider.`,
      );
    }
    return slot.executor(input);
  }

  snapshot(): AegisProviderSnapshot[] {
    return [...this.slots.values()].map((slot) => ({
      id: slot.subprocess.id,
      label: slot.subprocess.label,
      state: slot.state,
      provider: slot.subprocess.provider ?? 'unassigned',
      executable: Boolean(slot.executor),
      detail: slot.subprocess.detail,
    }));
  }

  private requireSlot(subprocessId: string): AegisProviderSlot {
    const slot = this.slots.get(subprocessId);
    if (!slot) {
      throw new Error(`Unknown Aegis subprocess: ${subprocessId}`);
    }
    return slot;
  }
}
