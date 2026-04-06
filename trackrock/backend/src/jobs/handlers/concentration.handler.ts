import type { Job } from 'bullmq';
import { logger } from '../../lib/logger.js';

export async function concentrationHandler(job: Job): Promise<void> {
  logger.info(`[Concentration] Starting for city=${job.data.city}`);
  // TODO: Phase 8 — compute concentration scores from property counts
  throw new Error('Concentration handler not yet implemented — coming in Phase 8');
}
