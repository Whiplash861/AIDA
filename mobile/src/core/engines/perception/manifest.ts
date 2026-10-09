import { MobileEngineDefinition } from '@/src/core/engines/types';

export const PERCEPTION_ENGINE: MobileEngineDefinition = {
  id: 'perception',
  name: 'Perception',
  domain: 'Camera, screenshot, image, and visual evidence intake',
  state: 'limited',
  detail:
    'Android Perception owns user-supplied visual evidence intake and analysis boundaries while preserving explicit permission and evidence provenance.',
  commandTypes: [],
  subprocesses: [
    {
      id: 'camera.capture',
      label: 'Camera Evidence Capture',
      state: 'staged',
      authority: 'observe',
      provider: 'android.camera',
      detail: 'Captures user-authorized camera evidence with explicit Android permission handling.',
    },
    {
      id: 'image.import',
      label: 'Image Evidence Import',
      state: 'limited',
      authority: 'observe',
      provider: 'android.media-picker',
      detail: 'Reviews system-picker image metadata locally. No raw media is retained or uploaded; native OCR remains unavailable.',
    },
    {
      id: 'screenshot.import',
      label: 'Screenshot Evidence Intake',
      state: 'limited',
      authority: 'observe',
      provider: 'android.media-picker',
      detail: 'Accepts user-selected screenshots as evidence while preserving source metadata where available.',
    },
    {
      id: 'evidence.analysis',
      label: 'Visual Evidence Analysis',
      state: 'staged',
      authority: 'analyze',
      provider: 'perception.analysis',
      detail: 'Analyzes visual evidence and returns findings without claiming unsupported device operations.',
    },
    {
      id: 'evidence.provenance',
      label: 'Evidence Provenance',
      state: 'limited',
      authority: 'observe',
      provider: 'local.storage',
      detail: 'Tracks the source and handling state of visual evidence used by AIDA and other Engines.',
    },
    {
      id: 'text.import', label: 'Pasted Evidence Review', state: 'limited', authority: 'observe',
      provider: 'system.clipboard', detail: 'Reads text only after PASTE, identifies literal diagnostic markers, and never routes pasted text as commands.',
    },
  ],
};
