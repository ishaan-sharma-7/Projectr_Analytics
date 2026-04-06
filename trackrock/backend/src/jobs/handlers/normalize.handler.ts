import type { Job } from 'bullmq';
import { logger } from '../../lib/logger.js';

export async function normalizeHandler(job: Job): Promise<void> {
  logger.info(`[Normalize] Starting for city=${job.data.city}`);
  // TODO: Phase 7 — Census ACS, Zillow, FRED, HUD, Eviction Lab
  throw new Error('Normalize handler not yet implemented — coming in Phase 7');
}
