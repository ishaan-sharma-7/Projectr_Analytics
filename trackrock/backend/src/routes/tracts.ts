import { Router } from 'express';
import { cacheRoute } from '../middleware/cache.js';

export const tractsRouter = Router();

// GET /api/tracts?city=&state=
tractsRouter.get('/', cacheRoute(3600), async (_req, res) => {
  res.json({ status: 'stub', route: 'GET /api/tracts' });
});

// GET /api/tracts/compare?a=:fipsTract&b=:fipsTract
tractsRouter.get('/compare', cacheRoute(3600), async (_req, res) => {
  res.json({ status: 'stub', route: 'GET /api/tracts/compare' });
});

// GET /api/tracts/:fipsTract
tractsRouter.get('/:fipsTract', cacheRoute(3600), async (_req, res) => {
  res.json({ status: 'stub', route: 'GET /api/tracts/:fipsTract' });
});

// GET /api/tracts/:fipsTract/metrics
tractsRouter.get('/:fipsTract/metrics', cacheRoute(3600), async (_req, res) => {
  res.json({ status: 'stub', route: 'GET /api/tracts/:fipsTract/metrics' });
});

// GET /api/tracts/:fipsTract/concentration
tractsRouter.get('/:fipsTract/concentration', cacheRoute(21600), async (_req, res) => {
  res.json({ status: 'stub', route: 'GET /api/tracts/:fipsTract/concentration' });
});
