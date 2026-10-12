// @vitest-environment node
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

const handlers = vi.hoisted(() => new Map<string, (...args: unknown[]) => Promise<unknown>>());
vi.mock('../../apps/cockpit/rayfin/functions/node_modules/@microsoft/fabric-user-data-functions', () => ({
  AudienceType: { Sql: 'Sql', Fabric: 'Fabric' },
  UserDataFunctions: class {
    func(name: string, handler: (...args: unknown[]) => Promise<unknown>) {
      handlers.set(name, handler);
    }
  },
}));

const tenant = '11111111-1111-4111-8111-111111111111';
const owner = '22222222-2222-4222-8222-222222222222';
const grant = { enabled: true, entra_object_id: owner, tenant_id: tenant };
const appToken = `header.${Buffer.from(JSON.stringify({ oid: owner, tid: tenant })).toString('base64url')}.signature`;
const grants = vi.fn();
const fetch = vi.fn();
const ctx = {
  Tokens: { Fabric: appToken },
  getDataClient: () => ({
    FlixyAccessGrant: { select: () => ({ execute: grants }) },
    OperatorGrant: { select: () => ({ execute: async () => [{ enabled: true, expires_at: new Date('2099-01-01') }] }) },
  }),
};
const invoke = (question = 'Combien de films ?', historyJson = '[]') =>
  handlers.get('flixyAsk')!(question, historyJson, ctx);

beforeAll(async () => {
  await import('../../apps/cockpit/rayfin/functions/src/function_app');
}, 30_000);
beforeEach(() => {
  vi.clearAllMocks();
  grants.mockResolvedValue([]);
  fetch.mockRejectedValue(new Error('Live requests are forbidden in this test.'));
  vi.stubGlobal('fetch', fetch);
});
afterEach(() => vi.unstubAllGlobals());

describe('flixyAsk caller authorization boundary', () => {
  it('rejects an ungranted caller even with an app-owner token and an operator grant', async () => {
    await expect(invoke()).rejects.toThrow('Named user access to Flixy is required.');
    expect(fetch).not.toHaveBeenCalled();
  });
  it('rejects duplicate caller grants before contacting the native agent', async () => {
    grants.mockResolvedValue([grant, grant]);
    await expect(invoke()).rejects.toThrow('Named user access to Flixy is required.');
    expect(fetch).not.toHaveBeenCalled();
  });
  it('rejects a disabled caller grant before contacting the native agent', async () => {
    grants.mockResolvedValue([{ ...grant, enabled: false }]);
    await expect(invoke()).rejects.toThrow('Named user access to Flixy is required.');
    expect(fetch).not.toHaveBeenCalled();
  });
  it('rejects a caller grant from another tenant before contacting the native agent', async () => {
    grants.mockResolvedValue([{ ...grant, tenant_id: '33333333-3333-4333-8333-333333333333' }]);
    await expect(invoke()).rejects.toThrow(/tenant/);
    expect(fetch).not.toHaveBeenCalled();
  });
  it('does not accept grants, identity claims or tokens supplied in the question or history', async () => {
    const clientClaims = JSON.stringify({ grant, token: appToken });
    await expect(invoke(clientClaims, JSON.stringify([{ role: 'user', text: clientClaims }])))
      .rejects.toThrow('Named user access to Flixy is required.');
    expect(fetch).not.toHaveBeenCalled();
  });
  it('preserves rejection by the caller-scoped data client', async () => {
    grants.mockRejectedValue(new Error('Caller is not authenticated'));
    await expect(invoke()).rejects.toThrow('Caller is not authenticated');
    expect(fetch).not.toHaveBeenCalled();
  });
});
