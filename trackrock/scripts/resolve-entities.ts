/**
 * Run entity resolution directly (no BullMQ).
 * Resolves all OTHER/low-confidence properties using Gemini.
 *
 * Usage (from trackrock/):
 *   npx dotenv -e ../.env -- tsx scripts/resolve-entities.ts
 *
 * Options:
 *   --dry-run   Print what would be resolved without calling Gemini
 *   --limit N   Only resolve first N unique owner names
 */
import path from 'path';
import dotenv from 'dotenv';
import { PrismaClient } from '@prisma/client';

dotenv.config({ path: path.resolve(process.cwd(), '../.env') });

const args = process.argv.slice(2);
const isDryRun = args.includes('--dry-run');
const limitArg = args.find((a) => a.startsWith('--limit='));
const limit = limitArg ? parseInt(limitArg.split('=')[1]) : undefined;

const prisma = new PrismaClient();

async function main() {
  const { resolveLLC } = await import('../backend/src/gemini/llcResolver.js');

  const unresolved = await prisma.property.findMany({
    where: {
      OR: [{ parentEntity: 'OTHER' }, { confidenceScore: { lt: 0.7 } }],
    },
    select: { ownerName: true, mailingAddress: true, matchReason: true },
    distinct: ['ownerName'],
    ...(limit ? { take: limit } : {}),
  });

  console.log(`[Resolve] ${unresolved.length} unique owner names to process`);

  if (isDryRun) {
    console.log('[Resolve] Dry run — first 20 names:');
    unresolved.slice(0, 20).forEach((p) => console.log(`  ${p.ownerName}`));
    return;
  }

  let reclassified = 0;

  for (let i = 0; i < unresolved.length; i++) {
    const p = unresolved[i];
    process.stdout.write(`\r[Resolve] ${i + 1}/${unresolved.length} — ${p.ownerName.slice(0, 40).padEnd(40)}`);

    const result = await resolveLLC(p.ownerName, p.mailingAddress ?? '', p.matchReason);

    await prisma.property.updateMany({
      where: { ownerName: p.ownerName },
      data: {
        parentEntity: result.parentEntity,
        confidenceScore: result.confidence,
        confidenceReason: result.reasoning,
        subsidiaryChain: result.subsidiaryChain,
      },
    });

    if (result.parentEntity !== 'OTHER') {
      reclassified++;
      process.stdout.write(` → ${result.parentEntity} (${(result.confidence * 100).toFixed(0)}%)`);
    }

    await new Promise((r) => setTimeout(r, 1100));
  }

  console.log(`\n\n[Resolve] Done — ${reclassified} owner names reclassified`);

  // Final breakdown
  const totals = await prisma.property.groupBy({
    by: ['parentEntity'],
    _count: { id: true },
    orderBy: { _count: { id: 'desc' } },
  });

  console.log('\n[Resolve] Updated entity breakdown:');
  for (const row of totals) {
    console.log(`  ${row.parentEntity.padEnd(22)} ${row._count.id}`);
  }
}

main()
  .catch((err) => {
    console.error('\n[Resolve] Error:', err.message);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
    const { redis } = await import('../backend/src/lib/redis.js');
    await redis.quit();
  });
