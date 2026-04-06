import { Worker, type Job } from 'bullmq';
import { redis } from '../lib/redis.js';
import { logger } from '../lib/logger.js';
import { prisma } from '../lib/prisma.js';
import type { PipelineStage } from '@trackrock/shared';

// Handlers are imported lazily to avoid circular deps at startup
async function dispatch(job: Job) {
  const stage = job.data.stage as PipelineStage;

  // Update PipelineJob record to 'running'
  await prisma.pipelineJob.updateMany({
    where: { stage, status: 'pending', city: job.data.city ?? null },
    data: { status: 'running', startedAt: new Date() },
  });

  try {
    switch (stage) {
      case 'ingest': {
        const { ingestHandler } = await import('./handlers/ingest.handler.js');
        await ingestHandler(job);
        break;
      }
      case 'resolve': {
        const { resolveHandler } = await import('./handlers/resolve.handler.js');
        await resolveHandler(job);
        break;
      }
      case 'geocode': {
        const { geocodeHandler } = await import('./handlers/geocode.handler.js');
        await geocodeHandler(job);
        break;
      }
      case 'normalize': {
        const { normalizeHandler } = await import('./handlers/normalize.handler.js');
        await normalizeHandler(job);
        break;
      }
      case 'concentration': {
        const { concentrationHandler } = await import('./handlers/concentration.handler.js');
        await concentrationHandler(job);
        break;
      }
      default:
        throw new Error(`Unknown pipeline stage: ${stage}`);
    }

    await prisma.pipelineJob.updateMany({
      where: { stage, status: 'running', city: job.data.city ?? null },
      data: { status: 'complete', completedAt: new Date() },
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    await prisma.pipelineJob.updateMany({
      where: { stage, status: 'running', city: job.data.city ?? null },
      data: { status: 'failed', completedAt: new Date(), errorMsg: msg },
    });
    throw err;
  }
}

export function startWorkers() {
  const worker = new Worker('pipeline', dispatch, {
    connection: redis,
    concurrency: 2,
  });

  worker.on('completed', (job) => {
    logger.info(`[Worker] ${job.name} completed`);
  });

  worker.on('failed', (job, err) => {
    logger.error(`[Worker] ${job?.name} failed: ${err.message}`);
  });

  worker.on('error', (err) => {
    logger.error(`[Worker] Error: ${err.message}`);
  });

  return worker;
}
