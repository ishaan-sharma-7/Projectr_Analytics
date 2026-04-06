import { Router } from 'express';
import { enqueuePipelineStage, pipelineQueue } from '../jobs/queues.js';
import { prisma } from '../lib/prisma.js';
import { AppError } from '../middleware/errorHandler.js';
import type { PipelineStage } from '@trackrock/shared';

export const pipelineRouter = Router();

const VALID_STAGES: PipelineStage[] = ['ingest', 'resolve', 'geocode', 'normalize', 'concentration'];

// POST /api/pipeline/trigger { stage, city }
pipelineRouter.post('/trigger', async (req, res, next) => {
  try {
    const { stage, city } = req.body as { stage: PipelineStage; city: string };

    if (!stage || !VALID_STAGES.includes(stage)) {
      throw new AppError(400, `Invalid stage. Must be one of: ${VALID_STAGES.join(', ')}`);
    }

    // Create a PipelineJob record
    const job = await prisma.pipelineJob.create({
      data: { stage, city: city ?? null, status: 'pending' },
    });

    // Enqueue the BullMQ job
    const bullJob = await enqueuePipelineStage(stage, city ?? 'all');

    res.json({ jobId: job.id, bullJobId: bullJob.id, status: 'queued', stage, city });
  } catch (err) {
    next(err);
  }
});

// GET /api/pipeline/status
pipelineRouter.get('/status', async (_req, res, next) => {
  try {
    const [waiting, active, completed, failed] = await Promise.all([
      pipelineQueue.getWaitingCount(),
      pipelineQueue.getActiveCount(),
      pipelineQueue.getCompletedCount(),
      pipelineQueue.getFailedCount(),
    ]);

    const recentJobs = await prisma.pipelineJob.findMany({
      orderBy: { createdAt: 'desc' },
      take: 20,
    });

    res.json({ queue: { waiting, active, completed, failed }, recentJobs });
  } catch (err) {
    next(err);
  }
});
