export type OperationLease = { id: number; kind: 'directive' | 'voice'; signal: AbortSignal };
export class OperationCoordinator {
  private sequence = 0;
  private active: { lease: OperationLease; controller: AbortController } | null = null;
  acquire(kind: OperationLease['kind']): OperationLease {
    if (this.active) throw new Error('AIDA is already processing an operation.');
    const controller = new AbortController();
    const lease = { id: ++this.sequence, kind, signal: controller.signal };
    this.active = { lease, controller };
    return lease;
  }
  release(lease: OperationLease): void {
    if (this.active?.lease.id === lease.id) this.active = null;
  }
  cancel(): void { this.active?.controller.abort(); this.active = null; }
  get current(): OperationLease | null { return this.active?.lease ?? null; }
}
