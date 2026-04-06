/**
 * Seed Austin demo data directly from processed_owners/ CSVs.
 * Bypasses BullMQ — runs inline for fast hackathon bootstrapping.
 *
 * Usage (from trackrock/):
 *   npx dotenv -e ../.env -- tsx scripts/seed-austin.ts
 */
import path from 'path';
import dotenv from 'dotenv';
import { PrismaClient } from '@prisma/client';

// Load .env from Projectr_Analytics root
dotenv.config({ path: path.resolve(process.cwd(), '../.env') });

const prisma = new PrismaClient();

async function main() {
  // Dynamic import after dotenv so DATABASE_URL is already set
  const { ingestFromCsv } = await import('../backend/src/jobs/handlers/ingest.handler.js');

  // processed_owners/ always lives next to trackrock/ inside Projectr_Analytics/
  const csvDir = path.resolve(process.cwd(), '..', 'processed_owners');
  const csvPath = path.join(csvDir, 'institutional_owners_2025_deep_clean.csv');

  console.log(`[Seed] Reading from: ${csvPath}`);
  console.log('[Seed] Seeding Austin properties...\n');

  const count = await ingestFromCsv(csvPath, 'Austin', (pct) => {
    process.stdout.write(`\r[Seed] Progress: ${pct}%  `);
  });

  process.stdout.write('\n');
  console.log(`[Seed] Upserted ${count} properties`);

  // Summary by entity
  const totals = await prisma.property.groupBy({
    by: ['parentEntity'],
    _count: { id: true },
    orderBy: { _count: { id: 'desc' } },
  });

  console.log('\n[Seed] Breakdown by parent entity:');
  for (const row of totals) {
    console.log(`  ${row.parentEntity.padEnd(22)} ${row._count.id}`);
  }

  const total = await prisma.property.count();
  console.log(`\n[Seed] Total properties in DB: ${total}`);
}

main()
  .catch((err) => {
    console.error('[Seed] Error:', err.message);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
