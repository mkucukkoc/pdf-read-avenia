import { fal } from '@fal-ai/client';
import axios from 'axios';
import {
  DEFAULT_FAL_CITY_MODEL,
  createFalDebugId,
  ensureFalConfigured,
  getFalKey,
  summarizeImageUrl,
} from './utils';
import { logger } from '../../../../utils/logger';

export const generateCityTeleportedPhoto = async (params: {
  personImageUrl: string;
  cityName: string;
  model?: string;
}) => {
  const resolvedModel = params.model || DEFAULT_FAL_CITY_MODEL;
  const falKey = getFalKey();
  if (!falKey) throw new Error('FAL_KEY is not configured');
  ensureFalConfigured();

  const falDebugId = createFalDebugId();
  const input = {
    person_image_url: params.personImageUrl,
    city_name: params.cityName,
    photo_shot: 'medium_shot' as const,
    camera_angle: 'eye_level' as const,
  };

  logger.info(
    {
      falDebugId,
      model: resolvedModel,
      input: {
        ...input,
        person_image_url: summarizeImageUrl(input.person_image_url),
      },
    },
    'FAL city teleport request prepared',
  );

  const result: any = await fal.subscribe(resolvedModel, {
    input,
    logs: true,
  });

  logger.info(
    {
      falDebugId,
      model: resolvedModel,
      requestId: result?.requestId || result?.request_id || null,
      rawResult: result,
    },
    'FAL city teleport response received',
  );

  const outputUrl = result?.data?.images?.[0]?.url as string | undefined;
  if (!outputUrl) {
    throw new Error('FAL city teleport returned no output URL');
  }

  const outputResponse = await axios.get<ArrayBuffer>(outputUrl, { responseType: 'arraybuffer' });
  const outputMimeType = (outputResponse.headers['content-type'] as string) || 'image/png';
  const outputBase64 = Buffer.from(outputResponse.data as any).toString('base64');

  return {
    data: outputBase64,
    mimeType: outputMimeType,
    text: undefined,
  };
};
