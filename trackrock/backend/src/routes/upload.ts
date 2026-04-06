import { Router } from 'express';
import multer from 'multer';
import path from 'path';
import fs from 'fs';
import { enqueuePipelineStage } from '../jobs/queues.js';
import { prisma } from '../lib/prisma.js';
import { AppError } from '../middleware/errorHandler.js';

export const uploadRouter = Router();

// Store uploads in a temp directory
const uploadDir = path.join(process.cwd(), 'uploads');
if (!fs.existsSync(uploadDir)) fs.mkdirSync(uploadDir, { recursive: true });

const storage = multer.diskStorage({
  destination: (_req, _file, cb) => cb(null, uploadDir),
  filename: (_req, file, cb) => {
    const unique = `${Date.now()}-${Math.round(Math.random() * 1e9)}`;
    cb(null, `${unique}-${file.originalname}`);
  },
});

const upload = multer({
  storage,
  limits: { fileSize: 500 * 1024 * 1024 }, // 500MB
  fileFilter: (_req, file, cb) => {
    if (!file.originalname.endsWith('.csv')) {
      return cb(new Error('Only CSV files are accepted'));
    }
    cb(null, true);
  },
});

// POST /api/upload/csv
uploadRouter.post('/csv', upload.single('file'), async (req, res, next) => {
  try {
    if (!req.file) throw new AppError(400, 'No file uploaded');

    const city = (req.body.city as string) ?? 'Austin';

    // Create pipeline job record
    const job = await prisma.pipelineJob.create({
      data: { stage: 'ingest', city, status: 'pending' },
    });

    // Enqueue ingest with file path
    const bullJob = await enqueuePipelineStage('ingest', city, {
      filePath: req.file.path,
      originalName: req.file.originalname,
    });

    res.json({
      jobId: job.id,
      bullJobId: bullJob.id,
      status: 'queued',
      file: req.file.originalname,
      city,
    });
  } catch (err) {
    next(err);
  }
});
