/**
 * Applies PostGIS geometry column and trigger after Prisma migrations.
 * Run via: npm run migrate (automatically called after prisma migrate deploy)
 * Safe to run multiple times — all statements are idempotent.
 */
import { PrismaClient } from '@prisma/client';
import dotenv from 'dotenv';
import path from 'path';

// Load .env from monorepo root (trackrock/.env), not backend/
dotenv.config({ path: path.resolve(process.cwd(), '../.env') });

const prisma = new PrismaClient();

async function main() {
  console.log('[PostGIS] Applying geometry column and trigger...');

  // Enable extension
  await prisma.$executeRawUnsafe(`CREATE EXTENSION IF NOT EXISTS postgis`);

  // Add geometry column (idempotent check)
  await prisma.$executeRawUnsafe(`
    DO $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'Property' AND column_name = 'geom'
      ) THEN
        PERFORM AddGeometryColumn('public', 'Property', 'geom', 4326, 'POINT', 2);
      END IF;
    END
    $$
  `);

  // Spatial index (idempotent)
  await prisma.$executeRawUnsafe(`
    CREATE INDEX IF NOT EXISTS "Property_geom_idx" ON "Property" USING GIST(geom)
  `);

  // Sync function
  await prisma.$executeRawUnsafe(`
    CREATE OR REPLACE FUNCTION sync_property_geom()
    RETURNS TRIGGER AS $$
    BEGIN
      IF NEW.lat IS NOT NULL AND NEW.lng IS NOT NULL THEN
        NEW.geom = ST_SetSRID(ST_MakePoint(NEW.lng, NEW.lat), 4326);
      ELSE
        NEW.geom = NULL;
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
  `);

  // Trigger (drop + recreate for idempotency)
  await prisma.$executeRawUnsafe(`
    DROP TRIGGER IF EXISTS property_geom_trigger ON "Property"
  `);
  await prisma.$executeRawUnsafe(`
    CREATE TRIGGER property_geom_trigger
      BEFORE INSERT OR UPDATE ON "Property"
      FOR EACH ROW EXECUTE FUNCTION sync_property_geom()
  `);

  // Backfill any existing rows that have lat/lng but no geom
  const backfilled = await prisma.$executeRawUnsafe(`
    UPDATE "Property"
    SET geom = ST_SetSRID(ST_MakePoint(lng, lat), 4326)
    WHERE lat IS NOT NULL AND lng IS NOT NULL AND geom IS NULL
  `);

  console.log(`[PostGIS] Done. Backfilled ${backfilled} existing rows.`);
}

main()
  .catch((e) => {
    console.error('[PostGIS] Error:', e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
