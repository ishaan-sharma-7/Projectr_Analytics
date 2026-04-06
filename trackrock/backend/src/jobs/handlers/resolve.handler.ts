import type { Job } from 'bullmq';
import { logger } from '../../lib/logger.js';

export async function resolveHandler(job: Job): Promise<void> {
  logger.info(`[Resolve] Starting for city=${job.data.city}`);
  // TODO: Phase 5 — Gemini entity resolution
  throw new Error('Resolve handler not yet implemented — coming in Phase 5');
}
