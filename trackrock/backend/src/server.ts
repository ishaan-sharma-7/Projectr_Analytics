import express from 'express';
import cors from 'cors';
import { healthRouter } from './routes/health.js';
import { propertiesRouter } from './routes/properties.js';
import { tractsRouter } from './routes/tracts.js';
import { metricsRouter } from './routes/metrics.js';
import { marketsRouter } from './routes/markets.js';
import { reportRouter } from './routes/report.js';
import { queryRouter } from './routes/query.js';
import { pipelineRouter } from './routes/pipeline.js';
import { uploadRouter } from './routes/upload.js';
import { errorHandler } from './middleware/errorHandler.js';
import { requestLogger } from './middleware/requestLogger.js';

export function createServer() {
  const app = express();

  app.use(cors({ origin: ['http://localhost:5173', 'http://localhost:3001'] }));
  app.use(express.json({ limit: '10mb' }));
  app.use(express.urlencoded({ extended: true }));
  app.use(requestLogger);

  // Routes
  app.use('/api/health', healthRouter);
  app.use('/api/properties', propertiesRouter);
  app.use('/api/tracts', tractsRouter);
  app.use('/api/metrics', metricsRouter);
  app.use('/api/markets', marketsRouter);
  app.use('/api/report', reportRouter);
  app.use('/api/query', queryRouter);
  app.use('/api/pipeline', pipelineRouter);
  app.use('/api/upload', uploadRouter);

  // 404
  app.use((_req, res) => res.status(404).json({ error: 'Not found' }));

  // Error handler (must be last)
  app.use(errorHandler);

  return app;
}
