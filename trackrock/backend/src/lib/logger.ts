import winston from 'winston';
import { config } from '../config.js';

export const logger = winston.createLogger({
  level: config.isDev ? 'debug' : 'info',
  format: config.isDev
    ? winston.format.combine(
        winston.format.colorize(),
        winston.format.simple(),
      )
    : winston.format.combine(
        winston.format.timestamp(),
        winston.format.json(),
      ),
  transports: [new winston.transports.Console()],
});
