import { Router } from 'express';

export const reportRouter = Router();

// POST /api/report/generate { fipsTract }
reportRouter.post('/generate', async (_req, res) => {
  res.json({ status: 'stub', route: 'POST /api/report/generate' });
});

// GET /api/report/:fipsTract/pdf
reportRouter.get('/:fipsTract/pdf', async (_req, res) => {
  res.json({ status: 'stub', route: 'GET /api/report/:fipsTract/pdf' });
});
