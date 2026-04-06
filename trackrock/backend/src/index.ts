import { config } from './config.js';
import { createServer } from './server.js';
import { startWorkers } from './jobs/workers.js';
import { prisma } from './lib/prisma.js';
import { redis } from './lib/redis.js';
import { logger } from './lib/logger.js';

async function main() {
  // Verify DB connection
  await prisma.$connect();
  logger.info('[DB] Connected to PostgreSQL');

  // Start BullMQ workers
  const worker = startWorkers();

  // Start HTTP server
  const app = createServer();
  const server = app.listen(config.port, () => {
    logger.info(`[Server] Listening on http://localhost:${config.port}`);
    logger.info(`[Server] Environment: ${config.nodeEnv}`);
  });

  // Graceful shutdown
  const shutdown = async (signal: string) => {
    logger.info(`[Server] ${signal} received — shutting down`);
    server.close(async () => {
      await worker.close();
      await prisma.$disconnect();
      await redis.quit();
      logger.info('[Server] Shutdown complete');
      process.exit(0);
    });
  };

  process.on('SIGTERM', () => shutdown('SIGTERM'));
  process.on('SIGINT', () => shutdown('SIGINT'));
}

main().catch((err) => {
  logger.error('[Server] Fatal startup error:', err);
  process.exit(1);
});
