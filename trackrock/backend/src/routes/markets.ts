import { Router } from 'express';
import { cacheRoute } from '../middleware/cache.js';

export const marketsRouter = Router();

// GET /api/markets
marketsRouter.get('/', cacheRoute(3600), async (_req, res) => {
  res.json({ status: 'stub', route: 'GET /api/markets' });
});

// GET /api/markets/:city/summary
marketsRouter.get('/:city/summary', cacheRoute(3600), async (_req, res) => {
  res.json({ status: 'stub', route: 'GET /api/markets/:city/summary' });
});
