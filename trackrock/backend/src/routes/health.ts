import { Router } from 'express';
import { prisma } from '../lib/prisma.js';
import { redis } from '../lib/redis.js';

export const healthRouter = Router();

healthRouter.get('/', async (_req, res) => {
  const checks = { postgres: false, redis: false };

  try {
    await prisma.$queryRaw`SELECT 1`;
    checks.postgres = true;
  } catch { /* unhealthy */ }

  try {
    await redis.ping();
    checks.redis = true;
  } catch { /* unhealthy */ }

  const healthy = checks.postgres && checks.redis;
  res.status(healthy ? 200 : 503).json({
    status: healthy ? 'ok' : 'degraded',
    timestamp: new Date().toISOString(),
    checks,
  });
});
