import type { Job } from 'bullmq';
import { logger } from '../../lib/logger.js';

export async function geocodeHandler(job: Job): Promise<void> {
  logger.info(`[Geocode] Starting for city=${job.data.city}`);
  // TODO: Phase 6 — Google Maps Geocoding API + Census FIPS lookup
  throw new Error('Geocode handler not yet implemented — coming in Phase 6');
}
