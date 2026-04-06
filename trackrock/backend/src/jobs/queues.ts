import { Queue } from 'bullmq';
import { redis } from '../lib/redis.js';
import type { PipelineStage } from '@trackrock/shared';

export const pipelineQueue = new Queue('pipeline', {
  connection: redis,
  defaultJobOptions: {
    attempts: 3,
    backoff: { type: 'exponential', delay: 5000 },
    removeOnComplete: 100,
    removeOnFail: 50,
  },
});

export async function enqueuePipelineStage(
  stage: PipelineStage,
  city: string,
  payload?: Record<string, unknown>,
) {
  const jobId = `${stage}:${city}:${Date.now()}`;
  return pipelineQueue.add(
    `${stage}:${city}`,
    { stage, city, ...payload },
    { jobId },
  );
}
