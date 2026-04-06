import { Router } from 'express';

export const queryRouter = Router();

// POST /api/query { question: string, city?: string }
queryRouter.post('/', async (_req, res) => {
  res.json({ status: 'stub', route: 'POST /api/query' });
});
