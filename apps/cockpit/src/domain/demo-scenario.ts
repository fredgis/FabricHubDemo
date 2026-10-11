import type { AppFunctionsSchema } from '../../rayfin/functions/src/types';
import { safeError } from '../services/business';
import type { MSFlixClient } from '../services/rayfinClient';

export type DemoScenarioType = 'rental' | 'purchase' | 'mixed';
export type DemoCommandName = 'placeOrder' | 'startPlayback' | 'recordProgress';
type FunctionName = DemoCommandName | 'capabilities';
export type DemoFunctions = {
  [Name in FunctionName]: Pick<MSFlixClient['functions'][Name], 'invoke'>;
};
type CommandResult = AppFunctionsSchema['placeOrder']['output'];
const INVOCATION_OPTIONS = { timeoutMs: 60_000 };
const TIMEOUT_RETRY_DELAYS_MS = [2_000, 5_000];
export type DemoConfig = { scenario: DemoScenarioType; count: number; paceMs: number } & (
  | { customerMode?: 'fixed'; customerKey: string }
  | { customerMode: 'random'; customerCount: number }
);
export type DemoReferences = {
  customers: readonly { customer_key: string; territory: string }[];
  offers: readonly { offer_key: string; content_key: string; territory: string; transaction_type: string }[];
  content: readonly { content_key: string; duration_seconds: number }[];
};
export type DemoTransaction = Readonly<{
  customerKey: string; offerKey: string; contentKey: string; transactionType: 'TVOD' | 'EST'; progressSeconds: number;
}>;
export type DemoPlan = Readonly<{
  runId: string; scenario: DemoScenarioType; paceMs: number; transactions: readonly DemoTransaction[];
}>;
export type DemoReceipt = {
  transactionIndex: number; command: DemoCommandName; idempotencyKey: string; result: CommandResult;
};
export type DemoRunState = {
  runId: string; status: 'idle' | 'running' | 'completed' | 'failed' | 'cancelled';
  completedTransactions: number; receipts: DemoReceipt[]; error: string; cancelRequested: boolean;
};

function resolveDemoConfig(config: DemoConfig, references: DemoReferences) {
  if (!Number.isInteger(config.count) || config.count < 1 || config.count > 100)
    throw new Error('Journey count must be a whole number from 1 to 100.');
  if (!Number.isInteger(config.paceMs) || config.paceMs < 0 || config.paceMs > 10_000)
    throw new Error('Command pace must be between 0 and 10,000 milliseconds.');
  if (!['rental', 'purchase', 'mixed'].includes(config.scenario)) throw new Error('Choose a supported Demo scenario.');
  if (config.customerMode === 'random' && (!Number.isInteger(config.customerCount)
    || config.customerCount < 1 || config.customerCount > config.count))
    throw new Error('Random customer count must be a whole number from 1 to the journey count.');

  const content = new Map(references.content.filter(film =>
    Number.isSafeInteger(film.duration_seconds) && film.duration_seconds > 0).map(film => [film.content_key, film]));
  const offers = references.offers.filter(offer => content.has(offer.content_key))
    .sort((a, b) => a.offer_key.localeCompare(b.offer_key));
  const transactionTypes = config.scenario === 'purchase' ? ['EST']
    : config.scenario === 'mixed' && config.count > 1 ? ['TVOD', 'EST'] : ['TVOD'];
  const offerTerritories = transactionTypes.map(transactionType => ({
    transactionType,
    territories: new Set(offers.filter(offer => offer.transaction_type === transactionType).map(offer => offer.territory)),
  }));
  if (config.customerMode === 'random') {
    const customers = [...new Map(references.customers.filter(customer =>
      offerTerritories.every(({ territories }) => territories.has(customer.territory)))
      .map(customer => [customer.customer_key, customer])).values()];
    if (!customers.length) throw new Error('No existing customers have eligible offers for this scenario.');
    if (config.customerCount > customers.length)
      throw new Error(`Random customer count exceeds the eligible customer count (${customers.length}).`);
    return { customers, offers, content };
  }
  const customer = references.customers.find(row => row.customer_key === config.customerKey);
  if (!customer) throw new Error('Select an existing customer before starting a Demo.');
  for (const { transactionType, territories } of offerTerritories) {
    if (!territories.has(customer.territory))
      throw new Error(`No ${transactionType === 'TVOD' ? 'rental' : 'purchase'} offer with valid film duration exists for ${customer.territory}.`);
  }
  return { customers: [customer], offers, content };
}

export function validateDemoConfig(config: DemoConfig, references: DemoReferences): void {
  resolveDemoConfig(config, references);
}

function shuffled<T>(rows: readonly T[]): T[] {
  const result = [...rows];
  for (let index = result.length - 1; index > 0; index--) {
    const other = Math.floor(Math.random() * (index + 1));
    [result[index], result[other]] = [result[other], result[index]];
  }
  return result;
}

/** Resolve existing territorial offers only. Prices and rental rights remain server-owned. */
export function createDemoPlan(config: DemoConfig, references: DemoReferences, runId: string = crypto.randomUUID()): DemoPlan {
  const resolved = resolveDemoConfig(config, references);
  if (!/^[a-zA-Z0-9_-]{1,64}$/.test(runId)) throw new Error('Invalid Demo run ID.');
  const customers = config.customerMode === 'random'
    ? shuffled(resolved.customers).slice(0, config.customerCount) : resolved.customers;
  const assigned = Array.from({ length: config.count }, (_, index) => customers[index % customers.length]);
  const scheduled = config.customerMode === 'random' ? shuffled(assigned) : assigned;
  let previousContentKey = '';
  const transactions = scheduled.map((customer, index): DemoTransaction => {
    const transactionType = config.scenario === 'purchase' || (config.scenario === 'mixed' && index % 2 === 1) ? 'EST' : 'TVOD';
    const eligible = resolved.offers.filter(offer =>
      offer.territory === customer.territory && offer.transaction_type === transactionType);
    let offer = eligible[Math.floor(index / (config.scenario === 'mixed' ? 2 : 1)) % eligible.length];
    if (config.customerMode === 'random') {
      const alternatives = eligible.filter(row => row.content_key !== previousContentKey);
      const choices = alternatives.length ? alternatives : eligible;
      offer = choices[Math.floor(Math.random() * choices.length)];
    }
    previousContentKey = offer.content_key;
    const film = resolved.content.get(offer.content_key)!;
    return Object.freeze({
      customerKey: customer.customer_key, offerKey: offer.offer_key, contentKey: offer.content_key,
      transactionType, progressSeconds: Math.min(60, film.duration_seconds),
    });
  });
  return Object.freeze({ runId, scenario: config.scenario, paceMs: config.paceMs, transactions: Object.freeze(transactions) });
}

function pause(milliseconds: number, signal: AbortSignal): Promise<void> {
  if (!milliseconds || signal.aborted) return Promise.resolve();
  return new Promise(resolve => {
    const finish = () => { clearTimeout(timer); signal.removeEventListener('abort', finish); resolve(); };
    const timer = setTimeout(finish, milliseconds);
    signal.addEventListener('abort', finish, { once: true });
  });
}

function confirmedReceipt(result: CommandResult): CommandResult {
  if (!result || typeof result.entity_key !== 'string' || !result.entity_key
    || typeof result.status !== 'string' || !result.status
    || !Array.isArray(result.event_ids) || !result.event_ids.length
    || result.event_ids.some(id => typeof id !== 'string' || !id)
    || new Set(result.event_ids).size !== result.event_ids.length)
    throw new Error('Native function returned an invalid command receipt.');
  return { ...result, event_ids: [...result.event_ids] };
}

/** A bounded sequential journey. Only confirmed UDF outputs become displayed receipts. */
export class DemoScenario {
  private cursor = 0;
  private receipts: DemoReceipt[] = [];
  private status: DemoRunState['status'] = 'idle';
  private error = '';
  private task?: Promise<DemoRunState>;
  private cancelRequested = false;
  private onChange?: (state: DemoRunState) => void;
  private paceController = new AbortController();

  constructor(readonly plan: DemoPlan, private readonly functions: DemoFunctions) {}

  get state(): DemoRunState {
    return {
      runId: this.plan.runId, status: this.status, completedTransactions: Math.floor(this.cursor / 3),
      receipts: this.receipts.map(row => ({ ...row, result: { ...row.result, event_ids: [...row.result.event_ids] } })),
      error: this.error, cancelRequested: this.cancelRequested,
    };
  }

  /** A native invocation cannot be aborted. Its receipt is kept before the next command is stopped. */
  cancel(): void {
    if (this.status !== 'running') return;
    this.cancelRequested = true;
    this.paceController.abort();
    this.onChange?.(this.state);
  }

  execute(onChange?: (state: DemoRunState) => void): Promise<DemoRunState> {
    if (this.task) return this.task;
    if (this.status === 'completed') return Promise.resolve(this.state);
    this.status = 'running'; this.error = ''; this.cancelRequested = false; this.onChange = onChange;
    this.paceController = new AbortController();
    onChange?.(this.state);
    this.task = this.run(onChange).finally(() => { this.task = undefined; });
    return this.task;
  }

  private async invokeWithRecovery<T>(name: FunctionName, invoke: () => Promise<T>): Promise<T> {
    for (let retry = 0; ; retry++) {
      try { return await invoke(); }
      catch (error) {
        // Rayfin reports client timeouts as an un-coded SdkError, not a function failure.
        const timedOut = error instanceof Error && error.name === 'SdkError'
          && (!('code' in error) || error.code === undefined)
          && /^Request timed out after \d+ms$/.test(error.message);
        if (!timedOut || this.cancelRequested) throw error;
        if (retry === TIMEOUT_RETRY_DELAYS_MS.length)
          throw new Error(`${name} did not respond after ${retry + 1} attempts. Its result is unconfirmed.`);
        await pause(TIMEOUT_RETRY_DELAYS_MS[retry], this.paceController.signal);
        if (this.cancelRequested) throw error;
      }
    }
  }

  private async run(onChange?: (state: DemoRunState) => void): Promise<DemoRunState> {
    try {
      const capability = await this.invokeWithRecovery('capabilities', () =>
        this.functions.capabilities.invoke(undefined, INVOCATION_OPTIONS));
      if (capability.can_operate !== true) throw new Error(capability.reason || 'Operator permission required.');
      while (this.cursor < this.plan.transactions.length * 3) {
        if (this.cancelRequested) break;
        const transactionIndex = Math.floor(this.cursor / 3);
        const step = this.cursor % 3;
        const row = this.plan.transactions[transactionIndex];
        const idempotencyKey = `demo:${this.plan.runId}:${transactionIndex}:${['order', 'play', 'progress'][step]}`;
        let command: DemoCommandName;
        let result: CommandResult;
        if (step === 0) {
          command = 'placeOrder';
          result = await this.invokeWithRecovery(command, () => this.functions.placeOrder.invoke({ input: {
            customer_key: row.customerKey, offer_key: row.offerKey, idempotency_key: idempotencyKey,
          } }, INVOCATION_OPTIONS));
        } else if (step === 1) {
          command = 'startPlayback';
          result = await this.invokeWithRecovery(command, () => this.functions.startPlayback.invoke({ input: {
            order_id: this.receipts[this.cursor - 1].result.entity_key, idempotency_key: idempotencyKey,
          } }, INVOCATION_OPTIONS));
        } else {
          command = 'recordProgress';
          result = await this.invokeWithRecovery(command, () => this.functions.recordProgress.invoke({ input: {
            session_id: this.receipts[this.cursor - 1].result.entity_key, position_seconds: row.progressSeconds,
            idempotency_key: idempotencyKey,
          } }, INVOCATION_OPTIONS));
        }
        this.receipts.push({ transactionIndex, command, idempotencyKey, result: confirmedReceipt(result) });
        this.cursor++;
        onChange?.(this.state);
        if (this.cursor < this.plan.transactions.length * 3 && !this.cancelRequested)
          await pause(this.plan.paceMs, this.paceController.signal);
      }
      this.status = this.cursor === this.plan.transactions.length * 3 ? 'completed' : 'cancelled';
    } catch (error) {
      this.status = 'failed'; this.error = safeError(error);
    }
    onChange?.(this.state);
    return this.state;
  }
}
