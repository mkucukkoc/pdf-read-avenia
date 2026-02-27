import { fal } from '@fal-ai/client';

export const GEMINI_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta';
export const DEFAULT_GEMINI_CHAT_MODEL = process.env.GEMINI_CHAT_MODEL
  || process.env.GEMINI_MODEL
  || 'gemini-2.5-pro';
export const DEFAULT_GEMINI_SUMMARY_MODEL = process.env.GEMINI_SUMMARY_MODEL
  || process.env.GEMINI_MODEL
  || 'gemini-2.5-flash';
export const DEFAULT_GEMINI_IMAGE_MODEL = process.env.GEMINI_IMAGE_MODEL || 'gemini-2.5-flash-image';
export const DEFAULT_GEMINI_COUPLE_IMAGE_MODEL = process.env.GEMINI_COUPLE_IMAGE_MODEL || 'gemini-3-pro-image-preview';
export const DEFAULT_FAL_IMAGE_MODEL = process.env.FAL_IMAGE_MODEL || 'fal-ai/bytedance/seedream/v4/edit';
export const ENFORCED_HALF_MOON_FACE_SWAP_MODEL = 'half-moon-ai/ai-face-swap/faceswapimage';
export const ENFORCED_GEMINI_EDIT_MODEL = DEFAULT_GEMINI_IMAGE_MODEL;
export const DEFAULT_GEMINI_WEDDING_IMAGE_MODEL =
  process.env.GEMINI_WEDDING_IMAGE_MODEL || DEFAULT_GEMINI_IMAGE_MODEL;
export const DEFAULT_FAL_WEDDING_IMAGE_MODEL = DEFAULT_FAL_IMAGE_MODEL;
export const DEFAULT_FAL_COUPLE_IMAGE_MODEL = DEFAULT_FAL_IMAGE_MODEL;
export const DEFAULT_FAL_NEWBORN_IMAGE_MODEL = DEFAULT_FAL_IMAGE_MODEL;
export const DEFAULT_FAL_CITY_MODEL = process.env.FAL_CITY_MODEL || 'fal-ai/image-apps-v2/city-teleport';
export const DEFAULT_FAL_VIDEO_MODEL = process.env.FAL_VIDEO_MODEL || 'fal-ai/pixverse/swap';

export const getApiKey = () => process.env.GEMINI_API_KEY || '';
export const getFalKey = () => process.env.FAL_KEY || process.env.FAL_API_KEY || '';

let falConfigured = false;
export const ensureFalConfigured = () => {
  if (falConfigured) return;
  const key = getFalKey();
  if (!key) return;
  fal.config({ credentials: key });
  falConfigured = true;
};
export const isFalConfigured = () => falConfigured;

export const createFalDebugId = () => `fal-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

export const summarizeImageUrl = (url: string) => {
  if (typeof url !== 'string') return { kind: 'unknown' };
  if (url.startsWith('data:')) {
    const commaIndex = url.indexOf(',');
    const header = commaIndex > 0 ? url.slice(0, commaIndex) : url.slice(0, 80);
    const payloadLength = commaIndex > 0 ? url.length - commaIndex - 1 : 0;
    return {
      kind: 'data_uri',
      header,
      payloadLength,
      totalLength: url.length,
    };
  }
  return {
    kind: 'url',
    preview: url.slice(0, 180),
    totalLength: url.length,
  };
};

export const extractImageUrlFromFalResponse = (payload: any): string | undefined => {
  const url =
    payload?.data?.image?.url
    || payload?.image?.url
    || payload?.data?.images?.[0]?.url
    || payload?.images?.[0]?.url;
  if (typeof url === 'string' && url.trim().length > 0) {
    return url.trim();
  }
  return undefined;
};

export const buildGeminiImageRequest = (parts: Array<{ text?: string; inlineData?: { mimeType: string; data: string } }>) => ({
  contents: [
    {
      role: 'user',
      parts,
    },
  ],
  generationConfig: {
    responseModalities: ['IMAGE'],
  },
});

export const extractInlineImageFromGeminiResponse = (payload: any) =>
  payload?.candidates?.[0]?.content?.parts?.find((part: any) => part?.inlineData?.data)?.inlineData;

export type GeminiResponse = {
  candidates?: Array<{
    content?: {
      parts?: Array<{
        text?: string;
        inlineData?: {
          data?: string;
          mimeType?: string;
        };
        fileData?: {
          fileUri?: string;
          mimeType?: string;
        };
      }>;
    };
  }>;
};

export type InlineImagePayload = {
  data: string;
  mimeType: string;
};
