import type { Job } from 'bullmq';
import { logger } from '../../lib/logger.js';

export async function ingestHandler(job: Job): Promise<void> {
  logger.info(`[Ingest] Starting for city=${job.data.city}`);
  // TODO: Phase 4 — parse CSVs and upsert Property records
  throw new Error('Ingest handler not yet implemented — coming in Phase 4');
}
