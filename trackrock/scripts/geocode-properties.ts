/**
 * Geocode all ungeocode properties in the DB.
 * Runs inline — no BullMQ required.
 *
 * Usage (from trackrock/):
 *   npx dotenv -e ../.env -- tsx scripts/geocode-properties.ts
 *
 * Options:
 *   --city Austin    Only geocode a specific city (default: Austin)
 *   --fips-only      Skip Google Maps step, only run Census FIPS lookup
 */
import path from 'path';
import dotenv from 'dotenv';
import { PrismaClient } from '@prisma/client';

dotenv.config({ path: path.resolve(process.cwd(), '../.env') });

const args = process.argv.slice(2);
const cityArg = args.find((a) => a.startsWith('--city='))?.split('=')[1] ?? 'Austin';
const fipsOnly = args.includes('--fips-only');

const prisma = new PrismaClient();

async function main() {
  const { geocodeCity } = await import('../backend/src/jobs/handlers/geocode.handler.js');

  console.log(`[Geocode] Starting geocoding for city=${cityArg}`);
  if (fipsOnly) console.log('[Geocode] FIPS-only mode — skipping Google Maps step');

  const before = await prisma.property.count({ where: { city: cityArg, lat: null } });
  console.log(`[Geocode] ${before} properties without coordinates\n`);

  const { geocoded, fipsResolved } = await geocodeCity(cityArg, (pct) => {
    process.stdout.write(`\r[Geocode] Progress: ${pct}%  `);
  });

  process.stdout.write('\n');

  // Summary
  const total = await prisma.property.count({ where: { city: cityArg } });
  const withCoords = await prisma.property.count({ where: { city: cityArg, lat: { not: null } } });
  const withFips = await prisma.property.count({ where: { city: cityArg, fipsTract: { not: null } } });

  console.log(`\n[Geocode] Results for ${cityArg}:`);
  console.log(`  Geocoded (Google Maps): ${geocoded}`);
  console.log(`  FIPS resolved (Census): ${fipsResolved}`);
  console.log(`  Total properties:       ${total}`);
  console.log(`  With coordinates:       ${withCoords} (${((withCoords / total) * 100).toFixed(1)}%)`);
  console.log(`  With FIPS tract:        ${withFips} (${((withFips / total) * 100).toFixed(1)}%)`);
}

main()
  .catch((err) => {
    console.error('\n[Geocode] Error:', err.message);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
    const { redis } = await import('../backend/src/lib/redis.js');
    await redis.quit();
  });
