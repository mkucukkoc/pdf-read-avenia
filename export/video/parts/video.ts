import { fal } from '@fal-ai/client';
import { logger } from '../../../../utils/logger';
import {
  DEFAULT_FAL_VIDEO_MODEL,
  ensureFalConfigured,
  getFalKey,
} from './utils';

const shortPreview = (value: string | undefined | null, max = 180) => {
  if (!value) return null;
  return value.length > max ? `${value.slice(0, max)}...` : value;
};

const extractVideoUrlFromFalResponse = (payload: any): string | null => {
  if (!payload || typeof payload !== 'object') return null;

  const direct =
    payload?.video?.url
    || payload?.videoUrl
    || payload?.output?.url
    || payload?.result?.video?.url
    || payload?.response?.video?.url
    || payload?.response?.videoUrl
    || payload?.response?.output?.url
    || payload?.response?.result?.video?.url
    || payload?.data?.video?.url
    || payload?.response?.data?.video?.url
    || payload?.result?.data?.video?.url;
  if (typeof direct === 'string' && direct.trim().length > 0) {
    return direct.trim();
  }

  return null;
};

export const generateStyledVideoWithVeo = async (params: {
  styleId: string | null;
  userImageUrl: string;
  referenceVideoUrl: string;
  requestId?: string | null;
  model?: string;
}) => {
  const { styleId, userImageUrl, referenceVideoUrl, requestId } = params;
  const resolvedModel = params.model || DEFAULT_FAL_VIDEO_MODEL;
  const falKey = getFalKey();
  const videoRequestId = requestId || `video-${Date.now()}`;
  const pixverseResolution = (process.env.FAL_VIDEO_RESOLUTION || '720p') as '360p' | '540p' | '720p';
  const pixverseKeyframeId = Number(process.env.FAL_VIDEO_KEYFRAME_ID || 1);
  const enableBackgroundSwap = (process.env.FAL_VIDEO_ENABLE_BACKGROUND_SWAP || 'true') === 'true';
  const babyBackgroundImageUrl = process.env.FAL_VIDEO_BABY_BACKGROUND_IMAGE_URL || '';
  const framingPrompt =
    'Keep the baby face slightly farther from camera with medium-shot framing. Avoid extreme close-up facial framing. ' +
    'Remove any Instagram logo, watermark, username label, or platform text overlay from the final video.';

  logger.info(
    {
      videoRequestId,
      step: 'fal_video_request_prepared',
      styleId,
      model: resolvedModel,
      userImageUrlPreview: shortPreview(userImageUrl),
      referenceVideoUrlPreview: shortPreview(referenceVideoUrl),
      hasFalKey: Boolean(falKey),
    },
    'FAL video request prepared'
  );

  if (!falKey) {
    logger.warn(
      {
        videoRequestId,
        step: 'fal_video_skipped_missing_api_key',
        styleId,
      },
      'FAL key missing; using fallback video URL'
    );
    return {
      outputVideoUrl: referenceVideoUrl,
      providerText: 'Fallback video URL used because FAL_KEY is missing.',
      providerStatus: null as number | null,
      usedFallback: true,
      providerRaw: null as any,
    };
  }

  ensureFalConfigured();
  try {
    const runPixverseSwap = async (args: {
      mode: 'person' | 'object' | 'background';
      videoUrl: string;
      imageUrl: string;
      step: string;
      prompt?: string;
    }) => {
      const input: any = {
        video_url: args.videoUrl,
        image_url: args.imageUrl,
        mode: args.mode,
        keyframe_id: Number.isFinite(pixverseKeyframeId) ? pixverseKeyframeId : 1,
        resolution: pixverseResolution,
        original_sound_switch: true,
      };
      if (args.prompt) {
        input.prompt = args.prompt;
      }
      logger.info(
        {
          videoRequestId,
          step: `${args.step}_started`,
          model: resolvedModel,
          input: {
            ...input,
            video_url: shortPreview(input.video_url),
            image_url: shortPreview(input.image_url),
          },
        },
        'FAL Pixverse swap step started'
      );

      const result: any = await fal.subscribe(resolvedModel, {
        input,
        logs: true,
        onQueueUpdate: (update: any) => {
          logger.info(
            {
              videoRequestId,
              step: `${args.step}_queue_update`,
              model: resolvedModel,
              status: update?.status || null,
              queuePosition: update?.queue_position ?? null,
            },
            'FAL Pixverse queue update'
          );
        },
      });

      const outputVideoUrl = extractVideoUrlFromFalResponse(result);
      logger.info(
        {
          videoRequestId,
          step: `${args.step}_completed`,
          model: resolvedModel,
          requestId: result?.requestId || result?.request_id || null,
          outputVideoUrlPreview: shortPreview(outputVideoUrl || ''),
        },
        'FAL Pixverse swap step completed'
      );
      return { result, outputVideoUrl };
    };

    const personSwap = await runPixverseSwap({
      mode: 'person',
      videoUrl: referenceVideoUrl,
      imageUrl: userImageUrl,
      step: 'fal_pixverse_person_swap',
      prompt: framingPrompt,
    });
    if (!personSwap.outputVideoUrl) {
      logger.warn(
        { videoRequestId, step: 'fal_pixverse_person_swap_missing_output' },
        'Pixverse person swap missing output URL; using fallback'
      );
      return {
        outputVideoUrl: referenceVideoUrl,
        providerText: 'FAL fallback used (person swap response missing video URL)',
        providerStatus: 200,
        usedFallback: true,
        providerRaw: personSwap.result,
      };
    }

    let finalVideoUrl = personSwap.outputVideoUrl;
    let providerRaw: any = personSwap.result;
    let providerText: string | null = null;

    if (enableBackgroundSwap && babyBackgroundImageUrl) {
      try {
        const backgroundSwap = await runPixverseSwap({
          mode: 'background',
          videoUrl: personSwap.outputVideoUrl,
          imageUrl: babyBackgroundImageUrl,
          step: 'fal_pixverse_background_swap',
        });
        if (backgroundSwap.outputVideoUrl) {
          finalVideoUrl = backgroundSwap.outputVideoUrl;
          providerRaw = {
            personSwap: personSwap.result,
            backgroundSwap: backgroundSwap.result,
          };
        } else {
          providerText = 'Background swap skipped: response missing video URL, returning person swap output.';
          providerRaw = {
            personSwap: personSwap.result,
            backgroundSwap: backgroundSwap.result,
          };
        }
      } catch (backgroundError: any) {
        logger.warn(
          {
            videoRequestId,
            step: 'fal_pixverse_background_swap_failed',
            message: backgroundError?.message || 'unknown_error',
            providerData: backgroundError?.response?.data || backgroundError?.body || null,
          },
          'Pixverse background swap failed; returning person swap output'
        );
        providerText = 'Background swap failed; returning person swap output.';
      }
    }

    return {
      outputVideoUrl: finalVideoUrl,
      providerText,
      providerStatus: 200,
      usedFallback: false,
      providerRaw,
    };
  } catch (error: any) {
    logger.error(
      {
        err: error,
        videoRequestId,
        step: 'fal_video_request_failed',
        providerStatus: error?.response?.status || null,
        providerData: error?.response?.data || error?.body || null,
      },
      'FAL video request failed; using fallback video URL'
    );
    return {
      outputVideoUrl: referenceVideoUrl,
      providerText: `FAL request failed: ${error?.message || 'unknown error'}`,
      providerStatus: error?.response?.status || null,
      usedFallback: true,
      providerRaw: error?.response?.data || error?.body || null,
    };
  }
};
