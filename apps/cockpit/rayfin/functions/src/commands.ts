import { randomUUID } from 'node:crypto';
import sql from 'mssql';
import type { Offer, Rental } from '../../data/schema.js';
import { canPlay, controlLimit, deadline, key, type CommandResult, type ControlInput,
  type OrderInput, type PlayInput, type ProgressInput } from './domain.js';
import { emit, publicState, request, type Store } from './storage.js';

async function rental(store: Store, orderId: string): Promise<Rental> {
  const result = await request(store).input('order', sql.NVarChar(128), key(orderId, 'order ID'))
    .query('SELECT * FROM dbo.Rentals WITH (UPDLOCK,HOLDLOCK) WHERE order_id=@order');
  if (result.recordset.length !== 1) throw new Error('Order not found.');
  return publicState(result.recordset[0]) as unknown as Rental;
}
async function offer(store: Store, offerKey: string): Promise<Offer> {
  const result = await request(store).input('offer', sql.NVarChar(128), offerKey)
    .query('SELECT * FROM dbo.Offers WITH (UPDLOCK,HOLDLOCK) WHERE offer_key=@offer');
  if (result.recordset.length !== 1) throw new Error('Offer not found.');
  return result.recordset[0] as Offer;
}
async function rentalEvent(store: Store, orderId: string, eventType: string): Promise<string> {
  return emit(store, eventType, orderId, publicState(await rental(store, orderId) as unknown as Record<string, unknown>));
}

export async function placeOrder(store: Store, input: OrderInput): Promise<CommandResult> {
  key(input.customer_key, 'customer key'); key(input.offer_key, 'offer key');
  const selected = await offer(store, input.offer_key);
  const start = deadline(selected, store.now);
  const customer = await request(store).input('key', sql.NVarChar(128), input.customer_key)
    .query('SELECT territory FROM dbo.Customers WITH (HOLDLOCK) WHERE customer_key=@key');
  if (customer.recordset.length !== 1) throw new Error('Customer not found in CRM import.');
  if (selected.territory !== customer.recordset[0].territory) throw new Error('Offer is not available in the customer territory.');
  const content = await request(store).input('key', sql.NVarChar(128), selected.content_key)
    .query('SELECT id FROM dbo.Contents WHERE content_key=@key');
  if (!content.recordset.length) throw new Error('Offer content is not in the licensed catalog.');
  const orderId = randomUUID();
  const status = selected.transaction_type === 'EST' ? 'purchased' : 'booked';
  await request(store).input('id', sql.UniqueIdentifier, orderId).input('order', sql.NVarChar(128), orderId)
    .input('customer', sql.NVarChar(128), input.customer_key).input('offer', sql.NVarChar(128), selected.offer_key)
    .input('status', sql.NVarChar(24), status).input('amount', sql.Int, selected.price_minor)
    .input('currency', sql.NVarChar(3), selected.currency).input('now', sql.DateTime2, store.now)
    .input('deadline', sql.DateTime2, start ? new Date(start) : null)
    .query(`INSERT dbo.Rentals (id,order_id,customer_key,offer_key,status,amount_minor,currency,
      created_at,start_deadline,first_play_at,expires_at)
      VALUES (@id,@order,@customer,@offer,@status,@amount,@currency,@now,@deadline,NULL,NULL)`);
  return { entity_key: orderId, status, event_ids: [await rentalEvent(store, orderId, 'rental.created')] };
}

export async function startPlayback(store: Store, input: PlayInput): Promise<CommandResult> {
  const order = await rental(store, input.order_id);
  const selected = await offer(store, order.offer_key);
  canPlay(order, selected, store.now);
  const events: string[] = [];
  if (!order.first_play_at) {
    const expires = selected.transaction_type === 'TVOD'
      ? new Date(store.now.getTime() + selected.play_window_hours * 3_600_000) : null;
    await request(store).input('order', sql.NVarChar(128), order.order_id)
      .input('now', sql.DateTime2, store.now).input('expires', sql.DateTime2, expires)
      .input('status', sql.NVarChar(24), selected.transaction_type === 'TVOD' ? 'active' : 'purchased')
      .query('UPDATE dbo.Rentals SET first_play_at=@now,expires_at=@expires,status=@status WHERE order_id=@order');
    events.push(await rentalEvent(store, order.order_id, 'rental.updated'));
  }
  const sessionId = randomUUID();
  await request(store).input('id', sql.UniqueIdentifier, sessionId).input('session', sql.NVarChar(128), sessionId)
    .input('order', sql.NVarChar(128), order.order_id).input('content', sql.NVarChar(128), selected.content_key)
    .input('customer', sql.NVarChar(128), order.customer_key)
    .query(`INSERT dbo.Playbacks (id,session_id,order_id,content_key,customer_key,position_seconds,status)
      VALUES (@id,@session,@order,@content,@customer,0,'playing')`);
  events.push(await emit(store, 'playback.created', sessionId, {
    session_id: sessionId, order_id: order.order_id, content_key: selected.content_key,
    customer_key: order.customer_key, position_seconds: 0, status: 'playing',
  }));
  return { entity_key: sessionId, status: 'playing', event_ids: events };
}

export async function recordProgress(store: Store, input: ProgressInput): Promise<CommandResult> {
  key(input.session_id, 'session ID');
  if (!Number.isInteger(input.position_seconds) || input.position_seconds < 0)
    throw new Error('Playback position must be a nonnegative integer.');
  const result = await request(store).input('session', sql.NVarChar(128), input.session_id)
    .query('SELECT * FROM dbo.Playbacks WITH (UPDLOCK,HOLDLOCK) WHERE session_id=@session');
  if (!result.recordset.length) throw new Error('Playback session not found.');
  const session = result.recordset[0];
  const order = await rental(store, session.order_id);
  canPlay(order, await offer(store, order.offer_key), store.now);
  const content = await request(store).input('key', sql.NVarChar(128), session.content_key)
    .query('SELECT duration_seconds FROM dbo.Contents WHERE content_key=@key');
  const duration = content.recordset[0]?.duration_seconds;
  if (!Number.isInteger(duration) || input.position_seconds > duration) throw new Error('Position exceeds the film duration.');
  if (input.position_seconds < session.position_seconds) throw new Error('Progress cannot move backwards.');
  const status = input.position_seconds === duration ? 'completed' : 'playing';
  await request(store).input('session', sql.NVarChar(128), input.session_id)
    .input('position', sql.Int, input.position_seconds).input('status', sql.NVarChar(24), status)
    .query('UPDATE dbo.Playbacks SET position_seconds=@position,status=@status WHERE session_id=@session');
  const event = await emit(store, 'playback.updated', input.session_id,
    { ...publicState(session), position_seconds: input.position_seconds, status });
  return { entity_key: input.session_id, status, event_ids: [event] };
}

export async function expireRentals(store: Store): Promise<CommandResult> {
  const orders = await request(store).input('now', sql.DateTime2, store.now).query(`
    SELECT TOP (100) order_id FROM dbo.Rentals WITH (UPDLOCK,HOLDLOCK)
    WHERE status IN ('booked','active') AND
    ((first_play_at IS NULL AND start_deadline<=@now) OR (first_play_at IS NOT NULL AND expires_at<=@now))
    ORDER BY created_at,order_id`);
  let events = 0;
  for (const { order_id: orderId } of orders.recordset) {
    await request(store).input('order', sql.NVarChar(128), orderId)
      .query("UPDATE dbo.Rentals SET status='expired' WHERE order_id=@order");
    await rentalEvent(store, orderId, 'rental.expired'); events++;
    const sessions = await request(store).input('order', sql.NVarChar(128), orderId)
      .query("SELECT * FROM dbo.Playbacks WITH (UPDLOCK,HOLDLOCK) WHERE order_id=@order AND status='playing'");
    for (const session of sessions.recordset) {
      await request(store).input('session', sql.NVarChar(128), session.session_id)
        .query("UPDATE dbo.Playbacks SET status='expired' WHERE session_id=@session");
      await emit(store, 'playback.updated', session.session_id, { ...publicState(session), status: 'expired' }); events++;
    }
  }
  return { entity_key: store.runId, status: `Expired ${orders.recordset.length} rentals; ${events} events committed`, event_ids: [] };
}

export async function requestControl(store: Store, input: ControlInput): Promise<CommandResult> {
  controlLimit(input.type, input.limit);
  const pending = await request(store).input('type', sql.NVarChar(24), input.type)
    .query("SELECT id FROM dbo.ControlCommands WITH (UPDLOCK,HOLDLOCK) WHERE type=@type AND status IN ('requested','running')");
  if (pending.recordset.length) throw new Error('A command of this type is already pending. Refresh its status before retrying.');
  const id = randomUUID();
  await request(store).input('id', sql.UniqueIdentifier, id)
    .input('key', sql.NVarChar(128), input.idempotency_key).input('type', sql.NVarChar(24), input.type)
    .input('params', sql.NVarChar(2000), JSON.stringify({ limit: input.limit, run_id: store.runId }))
    .input('now', sql.DateTime2, store.now)
    .query(`INSERT dbo.ControlCommands (id,idempotency_key,type,status,parameters,requested_at,completed_at,error)
      VALUES (@id,@key,@type,'requested',@params,@now,NULL,NULL)`);
  return { entity_key: id, status: 'requested', event_ids: [] };
}
