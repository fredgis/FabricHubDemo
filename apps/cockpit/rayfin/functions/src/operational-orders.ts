import sql from 'mssql';
import type { AppSchema, RuntimeBinding } from '../../data/schema.js';
import { withOperationalPool } from './operational-connection.js';

export type OperationalOrdersPage = {
  rentals: AppSchema['Rental'][];
  playback: AppSchema['Playback'][];
  orders: { page: number; pageSize: number; total: number };
  sessions: { page: number; pageSize: number; total: number };
};

const PAGE_SIZE = 50;
type RentalRow = Omit<AppSchema['Rental'], 'start_deadline' | 'first_play_at' | 'expires_at'> & {
  start_deadline: Date | null;
  first_play_at: Date | null;
  expires_at: Date | null;
};

export function assertOrdersPage(value: number, name: string): void {
  if (!Number.isSafeInteger(value) || value < 1)
    throw new Error(`${name} must be a positive safe integer.`);
}

function pageMetadata(requested: number, rawTotal: unknown): OperationalOrdersPage['orders'] {
  const total = typeof rawTotal === 'number' || (typeof rawTotal === 'string' && /^\d+$/.test(rawTotal))
    ? Number(rawTotal) : NaN;
  if (!Number.isSafeInteger(total) || total < 0) throw new Error('Operational row count exceeds the supported range.');
  return { page: Math.min(requested, Math.max(1, Math.ceil(total / PAGE_SIZE))), pageSize: PAGE_SIZE, total };
}

export async function readOperationalOrders(binding: RuntimeBinding, token: string,
  ordersPage: number, playbackPage: number): Promise<OperationalOrdersPage> {
  assertOrdersPage(ordersPage, 'ordersPage');
  assertOrdersPage(playbackPage, 'playbackPage');
  return withOperationalPool(binding, token, async pool => {
    const settings = await pool.request().query<{ snapshot_isolation_state: number }>(
      'SELECT snapshot_isolation_state FROM sys.databases WHERE database_id=DB_ID()');
    // RCSI alone is statement-scoped. Fall back to serializable without changing database settings.
    const isolation = settings.recordset[0]?.snapshot_isolation_state === 1
      ? sql.ISOLATION_LEVEL.SNAPSHOT : sql.ISOLATION_LEVEL.SERIALIZABLE;
    const tx = new sql.Transaction(pool);
    try {
      await tx.begin(isolation);
      const counts = await new sql.Request(tx).query<{ orders: string; sessions: string }>(`
        SELECT (SELECT COUNT_BIG(*) FROM dbo.Rentals) AS orders,
          (SELECT COUNT_BIG(*) FROM dbo.Playbacks) AS sessions`);
      const orders = pageMetadata(ordersPage, counts.recordset[0]?.orders);
      const sessions = pageMetadata(playbackPage, counts.recordset[0]?.sessions);
      const rows = await new sql.Request(tx)
        .input('ordersOffset', sql.BigInt, (orders.page - 1) * PAGE_SIZE)
        .input('playbackOffset', sql.BigInt, (sessions.page - 1) * PAGE_SIZE)
        .input('pageSize', sql.Int, PAGE_SIZE)
        .query<[RentalRow, AppSchema['Playback']]>(`
          SELECT id,order_id,customer_key,offer_key,status,amount_minor,currency,
            created_at,start_deadline,first_play_at,expires_at
          FROM dbo.Rentals ORDER BY created_at DESC,order_id DESC
          OFFSET @ordersOffset ROWS FETCH NEXT @pageSize ROWS ONLY;
          SELECT id,session_id,order_id,content_key,customer_key,position_seconds,status
          FROM dbo.Playbacks ORDER BY session_id ASC
          OFFSET @playbackOffset ROWS FETCH NEXT @pageSize ROWS ONLY;`);
      await tx.commit();
      return {
        rentals: rows.recordsets[0].map(row => ({ ...row, start_deadline: row.start_deadline ?? undefined,
          first_play_at: row.first_play_at ?? undefined, expires_at: row.expires_at ?? undefined })),
        playback: rows.recordsets[1], orders, sessions,
      };
    } catch (error) {
      try { await tx.rollback(); } catch { /* XACT_ABORT may already have rolled back. */ }
      throw error;
    }
  });
}
