import { AEGIS_ENGINE } from '@/src/core/engines/aegis/manifest';
import {
  AegisAndroidProviderRegistry,
  AegisProviderSnapshot,
} from '@/src/core/engines/aegis/provider-registry';

export type MobileAegisState =
  | 'stopped'
  | 'observing'
  | 'investigating'
  | 'elevated'
  | 'threat_confirmed'
  | 'degraded';

export type MobileAegisSnapshot = {
  state: MobileAegisState;
  running: boolean;
  lastObservationAt: string | null;
  lastIntelligentScanAt: string | null;
  baselineAvailable: boolean;
  openCaseCount: number;
  degradedReasons: string[];
  providers: AegisProviderSnapshot[];
};

class MobileAegisRuntime {
  readonly providers = new AegisAndroidProviderRegistry(AEGIS_ENGINE.subprocesses);

  private state: MobileAegisState = 'stopped';
  private running = false;
  private lastObservationAt: string | null = null;
  private lastIntelligentScanAt: string | null = null;
  private baselineAvailable = false;
  private openCaseCount = 0;
  private degradedReasons: string[] = [];

  snapshot(): MobileAegisSnapshot {
    return {
      state: this.state,
      running: this.running,
      lastObservationAt: this.lastObservationAt,
      lastIntelligentScanAt: this.lastIntelligentScanAt,
      baselineAvailable: this.baselineAvailable,
      openCaseCount: this.openCaseCount,
      degradedReasons: [...this.degradedReasons],
      providers: this.providers.snapshot(),
    };
  }

  /**
   * Marks the Engine runtime active only after the required observation
   * provider exists. A staged manifest is not equivalent to a running Engine.
   */
  start(): void {
    if (this.running) return;
    if (!this.providers.canExecute('observer.background')) {
      this.state = 'degraded';
      this.degradedReasons = ['android_background_observer_unavailable'];
      return;
    }
    this.running = true;
    this.state = 'observing';
    this.degradedReasons = [];
  }

  stop(): void {
    this.running = false;
    this.state = 'stopped';
  }

  beginInvestigation(): void {
    this.state = 'investigating';
  }

  completeObservation(options: {
    degradedReasons?: string[];
    elevated?: boolean;
    threatConfirmed?: boolean;
  } = {}): void {
    this.lastObservationAt = new Date().toISOString();
    this.degradedReasons = [...(options.degradedReasons ?? [])];
    if (options.threatConfirmed) {
      this.state = 'threat_confirmed';
    } else if (this.degradedReasons.length > 0) {
      this.state = 'degraded';
    } else if (options.elevated) {
      this.state = 'elevated';
    } else {
      this.state = 'observing';
    }
  }

  completeIntelligentScan(options: {
    baselineAvailable?: boolean;
    openCaseCount?: number;
    degradedReasons?: string[];
    elevated?: boolean;
    threatConfirmed?: boolean;
  } = {}): void {
    this.lastIntelligentScanAt = new Date().toISOString();
    if (typeof options.baselineAvailable === 'boolean') {
      this.baselineAvailable = options.baselineAvailable;
    }
    if (typeof options.openCaseCount === 'number') {
      this.openCaseCount = Math.max(0, Math.trunc(options.openCaseCount));
    }
    this.completeObservation({
      degradedReasons: options.degradedReasons,
      elevated: options.elevated,
      threatConfirmed: options.threatConfirmed,
    });
  }
}

export const MOBILE_AEGIS = new MobileAegisRuntime();
