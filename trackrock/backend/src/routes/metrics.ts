import { Router } from 'express';
import { cacheRoute } from '../middleware/cache.js';

export const metricsRouter = Router();

// GET /api/metrics/rent?city=&zip=
metricsRouter.get('/rent', cacheRoute(3600), async (_req, res) => {
  res.json({ status: 'stub', route: 'GET /api/metrics/rent' });
});

// GET /api/metrics/prices?city=&zip=
metricsRouter.get('/prices', cacheRoute(3600), async (_req, res) => {
  res.json({ status: 'stub', route: 'GET /api/metrics/prices' });
});

// GET /api/metrics/evictions?fipsTract=
metricsRouter.get('/evictions', cacheRoute(3600), async (_req, res) => {
  res.json({ status: 'stub', route: 'GET /api/metrics/evictions' });
});

// GET /api/metrics/demographics?fipsTract=
metricsRouter.get('/demographics', cacheRoute(3600), async (_req, res) => {
  res.json({ status: 'stub', route: 'GET /api/metrics/demographics' });
});
