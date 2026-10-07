export function assertVolumeApproval(approval, plan, now = new Date()) {
  if (approval?.approved !== true || approval.limits_confirmed !== true || approval.catalog_confirmed !== true)
    throw new Error('Explicit parent approval of source/storage limits and expanded catalog is required.');
  for (const field of ['source_manifest_hash','policy_hash','fingerprint','workspace_id','capacity_id'])
    if (approval[field] !== plan[field]) throw new Error(`Approval ${field} does not match the frozen plan.`);
  if (approval.run_key !== plan.profile.run_key) throw new Error('Approval run_key does not match.');
  if (!Number.isInteger(approval.max_orders) || !Number.isInteger(approval.max_events) ||
    plan.expected.orders > approval.max_orders || plan.expected.events > approval.max_events)
    throw new Error('Execution exceeds approved order/event bounds.');
  const expires = Date.parse(approval.expires_at);
  if (!Number.isFinite(expires) || expires <= now.getTime()) throw new Error('Volume approval has expired.');
}
