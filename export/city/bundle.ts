import { Router } from 'express';
import { randomUUID } from 'crypto';
import { db, FieldValue, storage } from '../../firebase';
import { authenticateToken, AuthRequest } from '../../middleware/authMiddleware';
import { logger } from '../../utils/logger';
import { generateCityTeleportedPhoto } from '../../server/bebek/services/gemini/city';

const preview = (value: string | null | undefined, max = 220) =>
  value ? value.slice(0, max) : null;

const extFromMime = (mime: string) => {
  if (mime.includes('png')) return 'png';
  if (mime.includes('webp')) return 'webp';
  if (mime.includes('heic')) return 'heic';
  return 'jpg';
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

const downloadImageFromSource = async (bucket: any, source: string) => {
  const parsed = resolveStorageObjectPath(source);
  if (parsed) {
    const file = bucket.file(parsed);
    const [exists] = await file.exists();
    if (exists) {
      const [buffer] = await file.download();
      const mimeType = file.name.toLowerCase().endsWith('.png') ? 'image/png' : 'image/jpeg';
      return { buffer, mimeType, objectPath: parsed };
    }
  }

  if (source.startsWith('http://') || source.startsWith('https://')) {
    const response = await fetch(source);
    if (!response.ok) {
      throw new Error(`Unable to download source image from URL (${response.status})`);
    }
    const arrayBuffer = await response.arrayBuffer();
    const responseMime = (response.headers.get('content-type') || '').toLowerCase().trim();
    const sourceLower = source.toLowerCase();
    const inferredMime =
      sourceLower.includes('.png') ? 'image/png'
        : sourceLower.includes('.webp') ? 'image/webp'
          : sourceLower.includes('.heic') ? 'image/heic'
            : sourceLower.includes('.jpg') || sourceLower.includes('.jpeg') ? 'image/jpeg'
              : 'image/jpeg';
    const mimeType = responseMime.startsWith('image/') ? responseMime : inferredMime;
    return { buffer: Buffer.from(arrayBuffer), mimeType, objectPath: null };
  }

  throw new Error('Source image could not be resolved from storage/url');
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

export const registerCityRoutes = (router: Router) => {
  router.post('/city/generate-photo', authenticateToken, async (req, res) => {
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
      const cityNameFromBody =
        typeof req.body?.city_name === 'string'
          ? req.body.city_name.trim()
          : '';
      const requestId = typeof req.body?.request_id === 'string'
        ? req.body.request_id
        : (req.header('x-request-id') || null);
      const requestedModel = typeof req.body?.model === 'string' ? req.body.model : undefined;

      if (!userImageSource || !cityNameFromBody) {
        res.status(400).json({
          error: 'invalid_request',
          message: 'user_image_url and city_name are required',
        });
        return;
      }
      const cityName = cityNameFromBody;

      const bucket: any = storage.bucket();
      const resolvedUserImage = await downloadImageFromSource(bucket, userImageSource);
      const now = Date.now();
      const inputExt = extFromMime(resolvedUserImage.mimeType || 'image/jpeg');
      const inputPath = `users/${userId}/uploads/city/${now}-input.${inputExt}`;
      await bucket.file(inputPath).save(resolvedUserImage.buffer, {
        contentType: resolvedUserImage.mimeType || 'image/jpeg',
        resumable: false,
        metadata: { cacheControl: 'public,max-age=31536000' },
      });
      const inputUrl = await getSignedOrPublicUrl(inputPath);

      logger.info(
        {
          userId,
          requestId,
          styleId,
          cityName,
          step: 'city_generate_request_prepared',
          inputUrlPreview: preview(inputUrl),
        },
        'City teleport generation request prepared',
      );

      const generated = await generateCityTeleportedPhoto({
        personImageUrl: inputUrl,
        cityName,
        model: requestedModel,
      });

      const generatedExt = extFromMime(generated.mimeType || 'image/png');
      const generatedId = randomUUID();
      const generatedPath = `users/${userId}/generated/city/${generatedId}.${generatedExt}`;
      const generatedBuffer = Buffer.from(generated.data, 'base64');
      await bucket.file(generatedPath).save(generatedBuffer, {
        contentType: generated.mimeType || 'image/png',
        resumable: false,
        metadata: { cacheControl: 'public,max-age=31536000' },
      });
      const outputUrl = await getSignedOrPublicUrl(generatedPath);

      await db
        .collection('users')
        .doc(userId)
        .collection('generatedPhotos')
        .doc(generatedId)
        .set({
          id: generatedId,
          styleType: 'city',
          styleId: styleId || null,
          requestId,
          cityName,
          inputImagePath: inputPath,
          inputImageUrl: inputUrl,
          outputImagePath: generatedPath,
          outputImageUrl: outputUrl,
          outputMimeType: generated.mimeType || 'image/png',
          createdAt: FieldValue.serverTimestamp(),
          updatedAt: FieldValue.serverTimestamp(),
        });

      logger.info(
        { userId, requestId, styleId, cityName, generatedId, step: 'city_generate_success' },
        'City teleport generation completed',
      );

      res.json({
        request_id: requestId,
        style_id: styleId || null,
        user_id: userId,
        input: {
          path: inputPath,
          url: inputUrl,
          city_name: cityName,
          photo_shot: 'medium_shot',
          camera_angle: 'eye_level',
        },
        output: {
          id: generatedId,
          path: generatedPath,
          url: outputUrl,
          mimeType: generated.mimeType || 'image/png',
        },
      });
    } catch (error) {
      logger.error(
        { err: error, step: 'city_generate_failed', requestId: req.header('x-request-id') || null },
        'City teleport generation failed',
      );
      res.status(500).json({ error: 'internal_error', message: (error as Error)?.message || 'City generation failed' });
    }
  });
};
