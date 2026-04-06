import type { Request, Response, NextFunction } from 'express';
import { redis } from '../lib/redis.js';

export function cacheRoute(ttlSeconds: number) {
  return async (req: Request, res: Response, next: NextFunction) => {
    const key = `cache:${req.originalUrl}`;

    try {
      const cached = await redis.get(key);
      if (cached) {
        res.setHeader('X-Cache', 'HIT');
        return res.json(JSON.parse(cached));
      }
    } catch {
      // Cache miss or Redis down — proceed without cache
    }

    // Intercept res.json to store the response
    const originalJson = res.json.bind(res);
    res.json = (data: unknown) => {
      try {
        redis.setex(key, ttlSeconds, JSON.stringify(data));
      } catch {
        // Non-fatal
      }
      res.setHeader('X-Cache', 'MISS');
      return originalJson(data);
    };

    next();
  };
}

export async function invalidateCache(pattern: string) {
  const keys = await redis.keys(`cache:${pattern}`);
  if (keys.length > 0) await redis.del(...keys);
}
