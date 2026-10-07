import { describe, expect, it } from 'vitest';
import { assertVolumeApproval } from '../../apps/cockpit/tools/lib/volume-approval.mjs';
const plan = { profile: { run_key: 'approved-run', total_orders: 50000 },
  expected: { orders: 50000, events: 500000 },
  source_manifest_hash: 'a'.repeat(64), policy_hash: 'b'.repeat(64), fingerprint: 'c'.repeat(64),
  workspace_id: 'workspace', capacity_id: 'capacity' };
const approval = { approved: true, limits_confirmed: true, catalog_confirmed: true,
  run_key: 'approved-run', max_orders: 50000, max_events: 500000,
  source_manifest_hash: 'a'.repeat(64), policy_hash: 'b'.repeat(64), fingerprint: 'c'.repeat(64),
  workspace_id: 'workspace', capacity_id: 'capacity', expires_at: '2026-10-08T00:00:00Z' };
describe('parent volume approval gate', () => {
  it('refuses mass execution until limits and the exact expanded-source plan are explicitly approved', () => {
    const now = new Date('2026-10-07T12:00:00Z');
    expect(() => assertVolumeApproval({ ...approval, approved: false }, plan, now)).toThrow('approval');
    expect(() => assertVolumeApproval({ ...approval, catalog_confirmed: false }, plan, now)).toThrow('approval');
    expect(() => assertVolumeApproval({ ...approval, source_manifest_hash: 'changed' }, plan, now)).toThrow('match');
    expect(() => assertVolumeApproval({ ...approval, max_events: 499999 }, plan, now)).toThrow('bounds');
    expect(() => assertVolumeApproval(approval, plan, now)).not.toThrow();
  });
});
