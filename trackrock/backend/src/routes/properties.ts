import { Router } from 'express';
import { cacheRoute } from '../middleware/cache.js';

export const propertiesRouter = Router();

// GET /api/properties?city=&year=&entity=&minConfidence=&bbox=
propertiesRouter.get('/', cacheRoute(300), async (_req, res) => {
  res.json({ status: 'stub', route: 'GET /api/properties' });
});

// GET /api/properties/heatmap?city=&year=
propertiesRouter.get('/heatmap', cacheRoute(300), async (_req, res) => {
  res.json({ status: 'stub', route: 'GET /api/properties/heatmap' });
});

// GET /api/properties/:id
propertiesRouter.get('/:id', async (_req, res) => {
  res.json({ status: 'stub', route: 'GET /api/properties/:id' });
});
