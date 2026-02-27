import { Router } from 'express';
import { randomUUID } from 'crypto';
import { db, FieldValue, storage } from '../../firebase';
import { authenticateToken, AuthRequest } from '../../middleware/authMiddleware';
import { logger } from '../../utils/logger';
import { generateStyledVideoWithVeo } from '../../server/bebek/services/gemini/video';

// Video style URL config (copy from config/styleUrls.ts)
const DEFAULT_VIDEO_REFERENCE_URL =
  'https://firebasestorage.googleapis.com/v0/b/bebek-ai.firebasestorage.app/o/assets%2Fvideos%2Fucan.mp4?alt=media&token=2cfb0fc5-63aa-4a5c-9bea-51bfd78aeb28';
const VIDEO_REFERENCE_URL_BY_STYLE_ID: Record<string, string> = {
  v1: 'https://firebasestorage.googleapis.com/v0/b/bebek-ai.firebasestorage.app/o/assets%2Fvideos%2Fguzeloyun.mp4?alt=media',
  v2: 'https://firebasestorage.googleapis.com/v0/b/bebek-ai.firebasestorage.app/o/assets%2Fvideos%2Fhavada.mp4?alt=media',
  v3: 'https://firebasestorage.googleapis.com/v0/b/bebek-ai.firebasestorage.app/o/assets%2Fvideos%2Foyun.mp4?alt=media',
  v4: 'https://firebasestorage.googleapis.com/v0/b/bebek-ai.firebasestorage.app/o/assets%2Fvideos%2Fucan.mp4?alt=media&token=2cfb0fc5-63aa-4a5c-9bea-51bfd78aeb28',
};

const resolveVideoReferenceUrl = (styleId: string | null) => {
  if (!styleId) return DEFAULT_VIDEO_REFERENCE_URL;
  return VIDEO_REFERENCE_URL_BY_STYLE_ID[styleId] || DEFAULT_VIDEO_REFERENCE_URL;
};

const preview = (value: string | null | undefined, max = 220) =>
  value ? value.slice(0, max) : null;

const extFromVideoMime = (mime: string) => {
  if (mime.includes('webm')) return 'webm';
  if (mime.includes('quicktime') || mime.includes('mov')) return 'mov';
  return 'mp4';
};

const resolveStorageObjectPath = (input: string) => {
  const raw = input.trim();
  if (!raw) return null;

  if (raw.startsWith('gs://')) {
    const noPrefix = raw.slice(5);
    const slashIndex = noPrefix.indexOf('/');
    if (slashIndex < 0) return null;
    return noPrefix.slice(slashIndex + 1);
  }

  if (raw.startsWith('http://') || raw.startsWith('https://')) {
    try {
      const parsed = new URL(raw);
      const marker = '/o/';
      const idx = parsed.pathname.indexOf(marker);
      if (idx >= 0) {
        const encodedPath = parsed.pathname.slice(idx + marker.length);
        return decodeURIComponent(encodedPath);
      }
    } catch {
      return null;
    }
    return null;
  }

  return raw;
};

const downloadVideoFromSource = async (source: string) => {
  if (!source.startsWith('http://') && !source.startsWith('https://')) {
    throw new Error('Video source must be a valid URL');
  }

  const headers: Record<string, string> = {};
  let parsedUrl: URL;
  try {
    parsedUrl = new URL(source);
  } catch {
    throw new Error('Video source URL could not be parsed');
  }

  if (parsedUrl.hostname === 'generativelanguage.googleapis.com') {
    const apiKey = process.env.GEMINI_API_KEY || '';
    if (!apiKey) {
      throw new Error('GEMINI_API_KEY is required to download Gemini video files');
    }
    headers['x-goog-api-key'] = apiKey;
  }

  const response = await fetch(source, { headers });
  if (!response.ok) {
    throw new Error(`Unable to download generated video (${response.status})`);
  }

  const arrayBuffer = await response.arrayBuffer();
  const contentType = (response.headers.get('content-type') || '').toLowerCase().trim();
  const mimeType = contentType.startsWith('video/') ? contentType : 'video/mp4';
  return { buffer: Buffer.from(arrayBuffer), mimeType };
};

const getSignedOrPublicUrl = async (filePath: string) => {
  const bucket: any = storage.bucket();
  const file = bucket.file(filePath);
  try {
    const [signed] = await file.getSignedUrl({
      action: 'read',
      expires: '2099-12-31',
    });
    return signed;
  } catch {
    const bucketName = bucket.name;
    return `https://firebasestorage.googleapis.com/v0/b/${bucketName}/o/${encodeURIComponent(filePath)}?alt=media`;
  }
};

export const registerVideoRoutes = (router: Router) => {
  router.post('/video/generate', authenticateToken, async (req, res) => {
    try {
      const authReq = req as AuthRequest;
      if (!authReq.user) {
        res.status(401).json({ error: 'access_denied', message: 'Authentication required' });
        return;
      }

      const userId = authReq.user.id;
      const styleId = typeof req.body?.style_id === 'string' ? req.body.style_id : null;
      const userImageSource =
        typeof req.body?.user_image_url === 'string'
          ? req.body.user_image_url
          : (typeof req.body?.user_image_path === 'string' ? req.body.user_image_path : '');
      const requestId = typeof req.body?.request_id === 'string'
        ? req.body.request_id
        : (req.header('x-request-id') || null);
      const requestedModel = typeof req.body?.model === 'string' ? req.body.model : undefined;

      const referenceVideoUrl = resolveVideoReferenceUrl(styleId);
      const resolvedByStyleMap = Boolean(styleId && VIDEO_REFERENCE_URL_BY_STYLE_ID[styleId]);
      logger.info({
        requestId,
        step: 'video_reference_resolved',
        userId,
        styleId,
        resolvedByStyleMap,
        usedDefaultReference: !resolvedByStyleMap,
        referenceVideoUrlPreview: preview(referenceVideoUrl),
      }, 'Video reference URL resolved');
      if (!referenceVideoUrl) {
        logger.warn({
          requestId,
          step: 'video_generate_rejected_missing_reference',
          userId,
          styleId,
        }, 'Video generation rejected due to unresolved reference URL');
        res.status(400).json({
          error: 'invalid_request',
          message: 'Video URL could not be resolved',
        });
        return;
      }

      if (!userImageSource) {
        logger.warn({
          requestId,
          step: 'video_generate_rejected_missing_user_image',
          userId,
          styleId,
        }, 'Video generation rejected due to missing user image');
        res.status(400).json({ error: 'invalid_request', message: 'user_image_url is required' });
        return;
      }

      logger.info({
        requestId,
        step: 'video_generate_request_received',
        userId,
        styleId,
        model: requestedModel || process.env.FAL_VIDEO_MODEL || 'fal-ai/pixverse/swap',
        userImageUrlPreview: preview(userImageSource),
        referenceVideoUrlPreview: preview(referenceVideoUrl),
      }, 'Video generation request received');

      const providerResult = await generateStyledVideoWithVeo({
        styleId,
        userImageUrl: userImageSource,
        referenceVideoUrl,
        requestId,
        model: requestedModel,
      });

      logger.info({
        requestId,
        step: 'video_generate_provider_completed',
        styleId,
        usedFallback: providerResult.usedFallback,
        providerStatus: providerResult.providerStatus,
        outputVideoUrlPreview: preview(providerResult.outputVideoUrl),
      }, 'Video generation provider step completed');

      const generatedId = randomUUID();
      const now = Date.now();
      const inputPath = resolveStorageObjectPath(userImageSource) || `users/${userId}/uploads/video/${now}-remote.jpg`;
      const bucket: any = storage.bucket();
      let outputVideoUrl = providerResult.outputVideoUrl;
      let outputVideoPath: string | null = null;
      let outputMimeType = 'video/mp4';

      if (!providerResult.usedFallback) {
        const downloadedVideo = await downloadVideoFromSource(providerResult.outputVideoUrl);
        outputMimeType = downloadedVideo.mimeType || 'video/mp4';
        const videoExt = extFromVideoMime(outputMimeType);
        outputVideoPath = `users/${userId}/generated/video/${generatedId}.${videoExt}`;

        await bucket.file(outputVideoPath).save(downloadedVideo.buffer, {
          contentType: outputMimeType,
          resumable: false,
          metadata: {
            cacheControl: 'public,max-age=31536000',
          },
        });
        outputVideoUrl = await getSignedOrPublicUrl(outputVideoPath);
      }

      await db
        .collection('users')
        .doc(userId)
        .collection('generatedPhotos')
        .doc(generatedId)
        .set({
          id: generatedId,
          styleType: 'video',
          styleId,
          requestId,
          inputImagePath: inputPath,
          inputImageUrl: userImageSource,
          outputVideoUrl,
          outputVideoPath,
          outputImageUrl: null,
          outputMimeType,
          providerText: providerResult.providerText || null,
          providerStatus: providerResult.providerStatus || null,
          providerRaw: providerResult.providerRaw || null,
          usedFallback: providerResult.usedFallback,
          createdAt: FieldValue.serverTimestamp(),
          updatedAt: FieldValue.serverTimestamp(),
        });

      res.json({
        request_id: requestId,
        style_id: styleId,
        user_id: userId,
        input: {
          path: inputPath,
          url: userImageSource,
        },
        output: {
          id: generatedId,
          path: outputVideoPath,
          url: outputVideoUrl,
          mimeType: outputMimeType,
        },
        provider: {
          text: providerResult.providerText || null,
          status: providerResult.providerStatus || null,
          used_fallback: providerResult.usedFallback,
        },
      });
    } catch (error) {
      logger.error(
        { err: error, step: 'video_generate_failed', requestId: req.header('x-request-id') || null },
        'Video generation failed',
      );
      res.status(500).json({ error: 'internal_error', message: (error as Error)?.message || 'Video generation failed' });
    }
  });
};
