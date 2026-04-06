import { GoogleGenerativeAI } from '@google/generative-ai';
import { config } from '../config.js';

// Singleton — instantiated lazily so startup doesn't fail if key is missing
let _genAI: GoogleGenerativeAI | null = null;

export function getGenAI(): GoogleGenerativeAI {
  if (!_genAI) {
    if (!config.geminiKey) {
      throw new Error('GOOGLE_GEMINI_API_KEY is not set — Gemini features unavailable');
    }
    _genAI = new GoogleGenerativeAI(config.geminiKey);
  }
  return _genAI;
}

export function getGeminiModel(modelName = 'gemini-1.5-pro') {
  return getGenAI().getGenerativeModel({
    model: modelName,
    generationConfig: { temperature: 0.1 },
  });
}

/** Safely extract JSON object from a Gemini response that may include markdown fences */
export function safeParseGeminiJson<T>(text: string): T | null {
  try {
    const match = text.match(/\{[\s\S]*\}/);
    if (!match) return null;
    return JSON.parse(match[0]) as T;
  } catch {
    return null;
  }
}
