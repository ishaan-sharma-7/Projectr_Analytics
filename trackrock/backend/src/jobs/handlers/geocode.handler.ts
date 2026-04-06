import type { Job } from 'bullmq';
import pLimit from 'p-limit';
import { prisma } from '../../lib/prisma.js';
import { logger } from '../../lib/logger.js';
import { geocodeAddress, getFipsTract } from '../../pipeline/geocoder.js';

const GOOGLE_CONCURRENCY = 40;
const CENSUS_DELAY_MS = 250;

/**
 * Geocode all ungeocode properties for a given city.
 * Step 1: Google Maps (parallel, 40 concurrent)
 * Step 2: Census FIPS lookup (sequential, 4 QPS)
 */
export async function geocodeHandler(job: Job): Promise<void> {
  const city: string = job.data.city ?? 'Austin';
  logger.info(`[Geocode] Starting for city=${city}`);

  await geocodeCity(city, (pct) => {
    job.updateProgress(pct).catch(() => {});
  });
}

export async function geocodeCity(
  city: string,
  onProgress?: (pct: number) => void,
): Promise<{ geocoded: number; fipsResolved: number }> {
  // ── Step 1: Google Maps geocoding ──────────────────────────────────────────
  const ungeocode = await prisma.property.findMany({
    where: { city, lat: null },
    select: { id: true, propertyAddress: true, city: true, state: true, confidenceScore: true },
  });

  logger.info(`[Geocode] ${ungeocode.length} properties need geocoding in ${city}`);

  const limit = pLimit(GOOGLE_CONCURRENCY);
  let geocodedCount = 0;

  await Promise.all(
    ungeocode.map((prop) =>
      limit(async () => {
        const result = await geocodeAddress(prop.propertyAddress, prop.city, prop.state ?? 'TX');
        if (!result) return;

        const isApproximate = result.quality === 'APPROXIMATE' || result.quality === 'RANGE_INTERPOLATED';
        const adjustedConfidence = isApproximate
          ? prop.confidenceScore * 0.85
          : prop.confidenceScore;

        await prisma.property.update({
          where: { id: prop.id },
          data: {
            lat: result.lat,
            lng: result.lng,
            zipCode: result.zipCode ?? undefined,
            confidenceScore: adjustedConfidence,
          },
        });

        geocodedCount++;
        const pct = Math.round((geocodedCount / ungeocode.length) * 50); // first 50%
        onProgress?.(pct);
      }),
    ),
  );

  logger.info(`[Geocode] Geocoded ${geocodedCount}/${ungeocode.length} properties`);

  // ── Step 2: Census FIPS tract lookup ──────────────────────────────────────
  const needsFips = await prisma.property.findMany({
    where: { city, fipsTract: null, lat: { not: null }, lng: { not: null } },
    select: { id: true, lat: true, lng: true },
  });

  logger.info(`[Geocode] ${needsFips.length} properties need FIPS lookup`);

  let fipsCount = 0;

  for (const prop of needsFips) {
    if (!prop.lat || !prop.lng) continue;

    const fips = await getFipsTract(prop.lat, prop.lng);
    if (fips) {
      await prisma.property.update({
        where: { id: prop.id },
        data: {
          fipsTract: fips.fipsTract,
        },
      });
      fipsCount++;
    }

    const pct = 50 + Math.round((fipsCount / needsFips.length) * 50); // second 50%
    onProgress?.(pct);

    await new Promise((r) => setTimeout(r, CENSUS_DELAY_MS));
  }

  logger.info(`[Geocode] FIPS resolved for ${fipsCount}/${needsFips.length} properties`);
  onProgress?.(100);

  return { geocoded: geocodedCount, fipsResolved: fipsCount };
}
