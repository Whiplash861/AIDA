import {
  type MutableRefObject,
  useEffect,
  useRef,
  useState,
} from 'react';
import { StyleSheet, Text, View } from 'react-native';
import Svg, {
  Circle,
  ClipPath,
  Defs,
  G,
  Line,
  Path,
  RadialGradient,
  Rect,
  Stop,
} from 'react-native-svg';

import { AIDA_FONTS, AidaRuntimeStatus } from '@/src/theme/aida-theme';

export type AidaOrbVisualState = 'BLUE' | 'GREEN' | 'VIOLET' | 'RED';

type Palette = {
  base: string;
  bright: string;
  hot: string;
  deep: string;
  edge: string;
};

type LayerName = 'core' | 'ambient' | 'data' | 'ring';
type RingStyle = 'SPIKE' | 'WAVE' | 'SPUTTER';
type CoreStageName =
  | 'split'
  | 'fracture'
  | 'collapse'
  | 'phase_jump'
  | 'radial_tear'
  | 'recover'
  | 'interference';

type RingProfile = {
  style: RingStyle;
  seed: number;
  centerAngle: number;
  startedAt: number;
  durationMs: number;
};

type CoreStage = {
  name: CoreStageName;
  durationMs: number;
};

type CoreProfile = {
  id: 1 | 2 | 3;
  stages: CoreStage[];
  stageIndex: number;
  stageStartedAt: number;
  seed: number;
  interferenceCenter: number;
};

type CoreLayer = {
  id: string;
  x: number;
  y: number;
  opacity: number;
  scaleY?: number;
  clip?: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
};

type CoverBand = {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  opacity: number;
};

type SputterLine = {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  opacity: number;
};

type CorePlan = {
  layers: CoreLayer[];
  covers: CoverBand[];
  sputters: SputterLine[];
};

type AidaOrbProps = {
  state: AidaOrbVisualState;
  label: string;
  runtimeStatus: AidaRuntimeStatus;
  size?: number;
};

const PALETTES: Record<AidaOrbVisualState, Palette> = {
  BLUE: {
    base: '#278DFF',
    bright: '#6EDBFF',
    hot: '#F2FDFF',
    deep: '#071A31',
    edge: '#020711',
  },
  GREEN: {
    base: '#20C879',
    bright: '#68F0B2',
    hot: '#F1FFF8',
    deep: '#06291B',
    edge: '#020B07',
  },
  VIOLET: {
    base: '#B13CFF',
    bright: '#D985FF',
    hot: '#FFF3FF',
    deep: '#2A073D',
    edge: '#0D0215',
  },
  RED: {
    base: '#FF3A50',
    bright: '#FF7A89',
    hot: '#FFF3F5',
    deep: '#35070E',
    edge: '#100204',
  },
};

// Same coordinate system as the current desktop header orb: 96x96 safety
// canvas around an 80px source field. Scaling the SVG changes presentation
// size without changing the desktop geometry or effect proportions.
const VIEW_SIZE = 96;
const ORB_DIAMETER = 80;
const INTERNAL_SCALE = 76 / 120;
const FULL_SIZE = ORB_DIAMETER - 4;
const CENTER = VIEW_SIZE / 2;
const RING_RADIUS = FULL_SIZE * 0.465;
const DATA_RADIUS = FULL_SIZE * 0.302;
const CORE_RADIUS = FULL_SIZE * 0.205;
const STATE_TRANSITION_MS = 720;
const CORE_PROFILE_MIN_MS = 3_000;
const CORE_PROFILE_MAX_MS = 5_000;
const RING_STEP_DEGREES = 2;
const RING_SEGMENT_SPAN = 2.1;

const RING_BLOOM_WIDTH = 14.5 * INTERNAL_SCALE;
const RING_WIDTH = 7.4 * INTERNAL_SCALE;
const RING_EDGE_WIDTH = 2.0 * INTERNAL_SCALE;
const RING_HOT_WIDTH = 3.4 * INTERNAL_SCALE;
const RING_COOL_WIDTH = 2.6 * INTERNAL_SCALE;

const CORE_BOX = {
  x: CENTER - CORE_RADIUS * 1.8,
  y: CENTER - CORE_RADIUS * 1.65,
  width: CORE_RADIUS * 3.6,
  height: CORE_RADIUS * 3.3,
};

export function AidaOrb({
  state,
  label,
  runtimeStatus,
  size = 164,
}: AidaOrbProps) {
  const [, renderFrame] = useState(0);

  const targetStateRef = useRef<AidaOrbVisualState>(state);
  const transitionRef = useRef<{
    from: AidaOrbVisualState;
    startedAt: number;
  } | null>(null);
  const runtimeStatusRef = useRef(runtimeStatus);
  const frameNowRef = useRef(clockNow());

  const breathPhaseRef = useRef(0);
  const ringHotRotationRef = useRef(38);
  const ringCoolRotationRef = useRef(218);
  const dataRotationsRef = useRef([146, 238, 30, 292]);
  const dataTickRotationRef = useRef(0);

  const ringProfileRef = useRef<RingProfile | null>(null);
  const coreProfileRef = useRef<CoreProfile | null>(null);
  const nextCoreProfileDueRef = useRef(Number.POSITIVE_INFINITY);
  const redTargetActiveRef = useRef(false);

  useEffect(() => {
    runtimeStatusRef.current = runtimeStatus;
  }, [runtimeStatus]);

  useEffect(() => {
    if (targetStateRef.current === state) {
      return;
    }

    transitionRef.current = {
      from: targetStateRef.current,
      startedAt: clockNow(),
    };
    targetStateRef.current = state;
  }, [state]);

  useEffect(() => {
    let animationFrame = 0;
    let lastTick = clockNow();

    const tick = (now: number) => {
      const dt = Math.min(0.05, Math.max(0.001, (now - lastTick) / 1000));
      lastTick = now;
      frameNowRef.current = now;

      const motionScale = motionScaleFor(runtimeStatusRef.current);
      breathPhaseRef.current = wrapped(
        breathPhaseRef.current + 25 * motionScale * dt,
      );
      ringHotRotationRef.current = wrapped(
        ringHotRotationRef.current + 22 * motionScale * dt,
      );
      ringCoolRotationRef.current = wrapped(
        ringCoolRotationRef.current - 15.5 * motionScale * dt,
      );
      const velocities = [-26, 19, -14, 11.5];
      dataRotationsRef.current = dataRotationsRef.current.map((angle, index) =>
        wrapped(angle + velocities[index] * motionScale * dt),
      );
      dataTickRotationRef.current = wrapped(
        dataTickRotationRef.current - 10.5 * motionScale * dt,
      );

      const transition = transitionRef.current;
      if (
        transition &&
        now - transition.startedAt >= STATE_TRANSITION_MS
      ) {
        transitionRef.current = null;
      }

      advanceRedSchedulers({
        now,
        targetState: targetStateRef.current,
        transition: transitionRef.current,
        redTargetActiveRef,
        ringProfileRef,
        coreProfileRef,
        nextCoreProfileDueRef,
      });

      renderFrame((value) => (value + 1) % 1_000_000);
      animationFrame = requestAnimationFrame(tick);
    };

    animationFrame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(animationFrame);
  }, []);

  const now = frameNowRef.current;
  const targetState = targetStateRef.current;
  const transition = transitionRef.current;
  const transitionAmount = transitionProgress(transition, now);

  const corePalette = paletteForLayer(
    'core',
    targetState,
    transition,
    transitionAmount,
  );
  const ambientPalette = paletteForLayer(
    'ambient',
    targetState,
    transition,
    transitionAmount,
  );
  const dataPalette = paletteForLayer(
    'data',
    targetState,
    transition,
    transitionAmount,
  );
  const ringPalette = paletteForLayer(
    'ring',
    targetState,
    transition,
    transitionAmount,
  );

  const redRingFraction = redLayerFraction(
    'ring',
    targetState,
    transition,
    transitionAmount,
  );

  const coreProfile = coreProfileRef.current;
  const fullInterference = coreProfile?.id === 3;
  const ringProfile = fullInterference
    ? interferenceRingProfile(coreProfile)
    : ringProfileRef.current;

  const ringSegments = buildRingSegments({
    profile: ringProfile,
    fullInterference,
    now,
    redFraction: redRingFraction,
    palette: ringPalette,
    hotRotation: ringHotRotationRef.current,
    coolRotation: ringCoolRotationRef.current,
  });

  const corePlan = buildCorePlan(coreProfile, now);
  const stableRing = !ringProfile || redRingFraction <= 0.001;
  const [baseCoreLayer, ...glitchCoreLayers] = corePlan.layers;

  const idle =
    0.5 +
    0.5 * Math.sin(degreesToRadians(breathPhaseRef.current * 1.55));
  const glow = 0.3 + idle * 0.14;
  const ambientAlpha0 = clamp01((42 + glow * 145) / 255);
  const ambientAlpha1 = clamp01((18 + glow * 78) / 255);
  const coreHaloAlpha0 = clamp01((82 + glow * 88) / 255);
  const coreHaloAlpha1 = clamp01((38 + glow * 48) / 255);

  const pulse = buildTransitionPulse(
    targetState,
    transition,
    transitionAmount,
  );

  const profile3Offset = (layer: number) =>
    fullInterference && coreProfile
      ? fullOffset(coreProfile, layer, now)
      : { x: 0, y: 0 };

  const gradientPrefix = 'aida-mobile-orb';

  return (
    <View style={styles.wrapper}>
      <View
        accessibilityLabel={`AIDA current status ${label}`}
        accessibilityRole="image"
        style={{ width: size, height: size }}
      >
        <Svg
          height={size}
          viewBox={`0 0 ${VIEW_SIZE} ${VIEW_SIZE}`}
          width={size}
        >
          <Defs>
            <RadialGradient
              cx="50%"
              cy="50%"
              id={`${gradientPrefix}-ambient`}
              r="50%"
            >
              <Stop
                offset="0%"
                stopColor={ambientPalette.base}
                stopOpacity={ambientAlpha0}
              />
              <Stop
                offset="58%"
                stopColor={ambientPalette.base}
                stopOpacity={ambientAlpha1}
              />
              <Stop
                offset="100%"
                stopColor={ambientPalette.base}
                stopOpacity={0}
              />
            </RadialGradient>

            <RadialGradient
              cx="50%"
              cy="50%"
              id={`${gradientPrefix}-core-halo`}
              r="50%"
            >
              <Stop
                offset="0%"
                stopColor={corePalette.bright}
                stopOpacity={coreHaloAlpha0}
              />
              <Stop
                offset="48%"
                stopColor={corePalette.base}
                stopOpacity={coreHaloAlpha1}
              />
              <Stop
                offset="100%"
                stopColor={corePalette.base}
                stopOpacity={0}
              />
            </RadialGradient>

            <RadialGradient
              cx="50%"
              cy="50%"
              id={`${gradientPrefix}-core-body`}
              r="50%"
            >
              <Stop offset="0%" stopColor={corePalette.hot} stopOpacity={1} />
              <Stop
                offset="12%"
                stopColor={corePalette.bright}
                stopOpacity={248 / 255}
              />
              <Stop
                offset="30%"
                stopColor={corePalette.base}
                stopOpacity={215 / 255}
              />
              <Stop
                offset="68%"
                stopColor={corePalette.deep}
                stopOpacity={248 / 255}
              />
              <Stop
                offset="100%"
                stopColor={corePalette.edge}
                stopOpacity={252 / 255}
              />
            </RadialGradient>

            <RadialGradient
              cx="50%"
              cy="50%"
              id={`${gradientPrefix}-core-flare`}
              r="50%"
            >
              <Stop offset="0%" stopColor="#FFFFFF" stopOpacity={1} />
              <Stop
                offset="52%"
                stopColor="#BDF1FF"
                stopOpacity={178 / 255}
              />
              <Stop offset="100%" stopColor="#6EDBFF" stopOpacity={0} />
            </RadialGradient>

            {corePlan.layers
              .filter((layer) => layer.clip)
              .map((layer) => (
                <ClipPath
                  id={`${gradientPrefix}-clip-${layer.id}`}
                  key={`clip-${layer.id}`}
                >
                  <Rect
                    height={layer.clip!.height}
                    width={layer.clip!.width}
                    x={layer.clip!.x}
                    y={layer.clip!.y}
                  />
                </ClipPath>
              ))}
          </Defs>

          {pulse ? (
            <G>
              <Circle
                cx={CENTER}
                cy={CENTER}
                fill="none"
                r={pulse.radius}
                stroke={pulse.color}
                strokeOpacity={pulse.opacity}
                strokeWidth={2.4 * INTERNAL_SCALE}
              />
              <Circle
                cx={CENTER}
                cy={CENTER}
                fill="none"
                r={pulse.radius + 3.5 * INTERNAL_SCALE}
                stroke={pulse.color}
                strokeOpacity={pulse.opacity / 3}
                strokeWidth={1.2 * INTERNAL_SCALE}
              />
            </G>
          ) : null}

          <Circle
            cx={CENTER}
            cy={CENTER}
            fill={`url(#${gradientPrefix}-ambient)`}
            r={46}
          />

          <Circle
            cx={CENTER}
            cy={CENTER}
            fill="none"
            r={RING_RADIUS}
            stroke={ringPalette.base}
            strokeOpacity={92 / 255}
            strokeWidth={RING_BLOOM_WIDTH}
          />

          {stableRing ? (
            <G>
              <Circle
                cx={CENTER}
                cy={CENTER}
                fill="none"
                r={RING_RADIUS}
                stroke={ringPalette.bright}
                strokeOpacity={248 / 255}
                strokeWidth={RING_WIDTH}
              />
              <Circle
                cx={CENTER}
                cy={CENTER}
                fill="none"
                r={RING_RADIUS - 3}
                stroke="#1D86DC"
                strokeOpacity={215 / 255}
                strokeWidth={RING_EDGE_WIDTH}
              />
              <Path
                d={arcPath(
                  CENTER,
                  CENTER,
                  RING_RADIUS,
                  ringHotRotationRef.current,
                  68,
                )}
                fill="none"
                stroke={ringPalette.hot}
                strokeLinecap="round"
                strokeOpacity={250 / 255}
                strokeWidth={RING_HOT_WIDTH}
              />
              <Path
                d={arcPath(
                  CENTER,
                  CENTER,
                  RING_RADIUS - 1.8,
                  ringCoolRotationRef.current,
                  50,
                )}
                fill="none"
                stroke={ringPalette.base}
                strokeLinecap="round"
                strokeOpacity={225 / 255}
                strokeWidth={RING_COOL_WIDTH}
              />
            </G>
          ) : (
            <G>
              <Circle
                cx={CENTER}
                cy={CENTER}
                fill="none"
                r={RING_RADIUS - 3}
                stroke="#1D86DC"
                strokeOpacity={120 / 255}
                strokeWidth={RING_EDGE_WIDTH}
              />
              {ringSegments.map((segment) => (
                <Path
                  d={segment.path}
                  fill="none"
                  key={segment.id}
                  stroke={segment.color}
                  strokeLinecap="butt"
                  strokeOpacity={segment.opacity}
                  strokeWidth={RING_WIDTH}
                />
              ))}
            </G>
          )}

          <DataRings
            dataPalette={dataPalette}
            dataRotations={dataRotationsRef.current}
            dataTickRotation={dataTickRotationRef.current}
            fullOffset={profile3Offset}
          />

          {baseCoreLayer ? (
            <CoreArtwork
              clipId={
                baseCoreLayer.clip
                  ? `${gradientPrefix}-clip-${baseCoreLayer.id}`
                  : undefined
              }
              gradientPrefix={gradientPrefix}
              layer={baseCoreLayer}
              palette={corePalette}
            />
          ) : null}

          {corePlan.covers.map((cover) => (
            <Rect
              fill={corePalette.edge}
              height={cover.height}
              key={`cover-${cover.id}`}
              opacity={cover.opacity}
              width={cover.width}
              x={cover.x}
              y={cover.y}
            />
          ))}

          {glitchCoreLayers.map((layer) => (
            <CoreArtwork
              clipId={
                layer.clip
                  ? `${gradientPrefix}-clip-${layer.id}`
                  : undefined
              }
              gradientPrefix={gradientPrefix}
              key={layer.id}
              layer={layer}
              palette={corePalette}
            />
          ))}

          {corePlan.sputters.map((line) => (
            <Rect
              fill={corePalette.hot}
              height={line.height}
              key={`sputter-${line.id}`}
              opacity={line.opacity}
              width={line.width}
              x={line.x}
              y={line.y}
            />
          ))}
        </Svg>
      </View>

      <Text style={[styles.statusLabel, { color: PALETTES[state].bright }]}>
        CURRENT STATUS • {label.toUpperCase()}
      </Text>
    </View>
  );
}

function DataRings({
  dataPalette,
  dataRotations,
  dataTickRotation,
  fullOffset,
}: {
  dataPalette: Palette;
  dataRotations: number[];
  dataTickRotation: number;
  fullOffset: (layer: number) => { x: number; y: number };
}) {
  const circleSpecs = [
    { scale: 1, alpha: 58 },
    { scale: 0.76, alpha: 46 },
    { scale: 0.52, alpha: 34 },
  ];

  const arcSpecs = [
    {
      scale: 0.98,
      span: 54,
      color: dataPalette.bright,
      alpha: 178,
      width: 1.35,
    },
    {
      scale: 0.82,
      span: 38,
      color: dataPalette.base,
      alpha: 154,
      width: 1.12,
    },
    {
      scale: 0.67,
      span: 28,
      color: dataPalette.hot,
      alpha: 145,
      width: 1,
    },
    {
      scale: 0.57,
      span: 24,
      color: dataPalette.bright,
      alpha: 120,
      width: 0.9,
    },
  ];

  return (
    <G>
      {circleSpecs.map((spec, index) => {
        const offset = fullOffset(index);
        return (
          <Circle
            cx={CENTER + offset.x}
            cy={CENTER + offset.y}
            fill="none"
            key={`data-circle-${index}`}
            r={DATA_RADIUS * spec.scale}
            stroke={dataPalette.base}
            strokeOpacity={spec.alpha / 255}
            strokeWidth={0.95 * INTERNAL_SCALE}
          />
        );
      })}

      {arcSpecs.map((spec, index) => {
        const offset = fullOffset(10 + index);
        return (
          <Path
            d={arcPath(
              CENTER + offset.x,
              CENTER + offset.y,
              DATA_RADIUS * spec.scale,
              dataRotations[index],
              spec.span,
            )}
            fill="none"
            key={`data-arc-${index}`}
            stroke={spec.color}
            strokeLinecap="round"
            strokeOpacity={spec.alpha / 255}
            strokeWidth={spec.width * INTERNAL_SCALE}
          />
        );
      })}

      {Array.from({ length: 28 }, (_, index) => {
        const offset = fullOffset(20);
        const angle = index * (360 / 28) + dataTickRotation;
        const radial = radialVector(angle);
        const tangent = tangentVector(angle);
        const radius = DATA_RADIUS * 0.87;
        const anchorX = CENTER + offset.x + radial.x * radius;
        const anchorY = CENTER + offset.y + radial.y * radius;
        const length = index % 4 === 0 ? 3 : 1.8;

        return (
          <Line
            key={`data-tick-${index}`}
            stroke={dataPalette.bright}
            strokeOpacity={(index % 4 === 0 ? 132 : 64) / 255}
            strokeWidth={0.8 * INTERNAL_SCALE}
            x1={anchorX - tangent.x * (length / 2)}
            x2={anchorX + tangent.x * (length / 2)}
            y1={anchorY - tangent.y * (length / 2)}
            y2={anchorY + tangent.y * (length / 2)}
          />
        );
      })}
    </G>
  );
}

function CoreArtwork({
  clipId,
  gradientPrefix,
  layer,
  palette,
}: {
  clipId?: string;
  gradientPrefix: string;
  layer: CoreLayer;
  palette: Palette;
}) {
  const scaleY = layer.scaleY ?? 1;
  const transform =
    scaleY === 1
      ? `translate(${layer.x} ${layer.y})`
      : `matrix(1 0 0 ${scaleY} ${layer.x} ${CENTER * (1 - scaleY) + layer.y})`;
  const haloRadius = CORE_RADIUS * 1.72;
  const glassRadius = CORE_RADIUS * 0.92;
  const flareRadius = CORE_RADIUS * 0.44;

  return (
    <G
      clipPath={clipId ? `url(#${clipId})` : undefined}
      opacity={layer.opacity}
      transform={transform}
    >
      <Circle
        cx={CENTER}
        cy={CENTER}
        fill={`url(#${gradientPrefix}-core-halo)`}
        r={haloRadius}
      />
      <Circle
        cx={CENTER}
        cy={CENTER}
        fill={`url(#${gradientPrefix}-core-body)`}
        r={CORE_RADIUS}
      />
      <Circle
        cx={CENTER}
        cy={CENTER}
        fill="none"
        r={glassRadius}
        stroke={palette.bright}
        strokeOpacity={188 / 255}
        strokeWidth={1.25 * INTERNAL_SCALE}
      />
      <Line
        stroke={palette.hot}
        strokeOpacity={220 / 255}
        strokeWidth={1.25 * INTERNAL_SCALE}
        x1={CENTER - CORE_RADIUS * 1.36}
        x2={CENTER + CORE_RADIUS * 1.36}
        y1={CENTER}
        y2={CENTER}
      />
      <Line
        stroke={palette.hot}
        strokeOpacity={120 / 255}
        strokeWidth={0.8 * INTERNAL_SCALE}
        x1={CENTER}
        x2={CENTER}
        y1={CENTER - CORE_RADIUS * 0.38}
        y2={CENTER + CORE_RADIUS * 0.38}
      />
      <Circle
        cx={CENTER}
        cy={CENTER}
        fill={`url(#${gradientPrefix}-core-flare)`}
        r={flareRadius}
      />
    </G>
  );
}

function advanceRedSchedulers({
  now,
  targetState,
  transition,
  redTargetActiveRef,
  ringProfileRef,
  coreProfileRef,
  nextCoreProfileDueRef,
}: {
  now: number;
  targetState: AidaOrbVisualState;
  transition: { from: AidaOrbVisualState; startedAt: number } | null;
  redTargetActiveRef: MutableRefObject<boolean>;
  ringProfileRef: MutableRefObject<RingProfile | null>;
  coreProfileRef: MutableRefObject<CoreProfile | null>;
  nextCoreProfileDueRef: MutableRefObject<number>;
}) {
  const targetRed = targetState === 'RED';

  if (targetRed && !redTargetActiveRef.current) {
    redTargetActiveRef.current = true;
    coreProfileRef.current = null;
    nextCoreProfileDueRef.current = now + randomBetween(
      CORE_PROFILE_MIN_MS,
      CORE_PROFILE_MAX_MS,
    );
  } else if (!targetRed && redTargetActiveRef.current) {
    redTargetActiveRef.current = false;
    coreProfileRef.current = null;
    nextCoreProfileDueRef.current = Number.POSITIVE_INFINITY;
  }

  if (targetRed) {
    const coreProfile = coreProfileRef.current;
    if (!coreProfile && now >= nextCoreProfileDueRef.current) {
      const next = beginCoreProfile(now);
      coreProfileRef.current = next;
      if (next.id === 3) {
        ringProfileRef.current = null;
      }
    } else if (coreProfile) {
      const currentStage = coreProfile.stages[coreProfile.stageIndex];
      if (now - coreProfile.stageStartedAt >= currentStage.durationMs) {
        const nextIndex = coreProfile.stageIndex + 1;
        if (nextIndex >= coreProfile.stages.length) {
          const wasInterference = coreProfile.id === 3;
          coreProfileRef.current = null;
          nextCoreProfileDueRef.current = now + randomBetween(
            CORE_PROFILE_MIN_MS,
            CORE_PROFILE_MAX_MS,
          );
          if (wasInterference) {
            ringProfileRef.current = startRingProfile(now);
          }
        } else {
          coreProfileRef.current = {
            ...coreProfile,
            stageIndex: nextIndex,
            stageStartedAt: now,
            seed: randomSeed(),
          };
        }
      }
    }
  }

  const transitionStillRed = Boolean(
    transition &&
      transition.from === 'RED' &&
      now - transition.startedAt < STATE_TRANSITION_MS,
  );
  const redVisualActive = targetRed || transitionStillRed;
  const profile3Active = coreProfileRef.current?.id === 3;

  if (profile3Active) {
    ringProfileRef.current = null;
    return;
  }

  if (!redVisualActive) {
    ringProfileRef.current = null;
    return;
  }

  const ringProfile = ringProfileRef.current;
  if (!ringProfile || now - ringProfile.startedAt >= ringProfile.durationMs) {
    ringProfileRef.current = startRingProfile(now);
  }
}

function beginCoreProfile(now: number): CoreProfile {
  const roll = Math.random();
  const id: 1 | 2 | 3 = roll < 0.4 ? 1 : roll < 0.8 ? 2 : 3;

  if (id === 1) {
    return {
      id,
      stages: [
        { name: 'split', durationMs: randomBetween(300, 420) },
        { name: 'fracture', durationMs: randomBetween(320, 460) },
        { name: 'collapse', durationMs: randomBetween(280, 400) },
        { name: 'recover', durationMs: randomBetween(320, 500) },
      ],
      stageIndex: 0,
      stageStartedAt: now,
      seed: randomSeed(),
      interferenceCenter: 0,
    };
  }

  if (id === 2) {
    return {
      id,
      stages: [
        { name: 'phase_jump', durationMs: randomBetween(450, 650) },
        { name: 'radial_tear', durationMs: randomBetween(550, 800) },
        { name: 'recover', durationMs: randomBetween(350, 550) },
      ],
      stageIndex: 0,
      stageStartedAt: now,
      seed: randomSeed(),
      interferenceCenter: 0,
    };
  }

  return {
    id,
    stages: [{ name: 'interference', durationMs: 3_000 }],
    stageIndex: 0,
    stageStartedAt: now,
    seed: randomSeed(),
    interferenceCenter: Math.random() * 360,
  };
}

function startRingProfile(now: number): RingProfile {
  const styles: RingStyle[] = ['SPIKE', 'WAVE', 'SPUTTER'];
  return {
    style: styles[Math.floor(Math.random() * styles.length)],
    seed: randomSeed(),
    centerAngle: Math.random() * 360,
    startedAt: now,
    durationMs: randomBetween(900, 2_200),
  };
}

function interferenceRingProfile(profile: CoreProfile | null): RingProfile | null {
  if (!profile || profile.id !== 3) {
    return null;
  }
  return {
    style: 'WAVE',
    seed: profile.seed,
    centerAngle: profile.interferenceCenter,
    startedAt: profile.stageStartedAt,
    durationMs: 3_000,
  };
}

function buildRingSegments({
  profile,
  fullInterference,
  now,
  redFraction,
  palette,
  hotRotation,
  coolRotation,
}: {
  profile: RingProfile | null;
  fullInterference: boolean;
  now: number;
  redFraction: number;
  palette: Palette;
  hotRotation: number;
  coolRotation: number;
}) {
  if (!profile || redFraction <= 0.001) {
    return [];
  }

  const segments: {
    id: string;
    path: string;
    color: string;
    opacity: number;
  }[] = [];

  for (let index = 0; index < 360 / RING_STEP_DEGREES; index += 1) {
    const angle = index * RING_STEP_DEGREES;
    const displacement = ringDisplacement({
      angle,
      index,
      profile,
      fullInterference,
      now,
      redFraction,
    });
    const start = angle - RING_SEGMENT_SPAN / 2;
    const color = ringColor(angle, palette, hotRotation, coolRotation);

    segments.push({
      id: `ring-segment-${index}`,
      path: arcPath(
        CENTER + displacement.x,
        CENTER + displacement.y,
        RING_RADIUS,
        start,
        RING_SEGMENT_SPAN,
      ),
      color:
        displacement.energy > 0.8 && index % 7 === 0 ? palette.hot : color,
      opacity: displacement.energy > 0.8 && index % 7 === 0 ? 250 / 255 : 248 / 255,
    });
  }

  return segments;
}

function ringDisplacement({
  angle,
  index,
  profile,
  fullInterference,
  now,
  redFraction,
}: {
  angle: number;
  index: number;
  profile: RingProfile;
  fullInterference: boolean;
  now: number;
  redFraction: number;
}) {
  const elapsed = Math.max(0, now - profile.startedAt);
  const progress = clamp01(elapsed / profile.durationMs);
  const baseLife = Math.sin(progress * Math.PI);
  const life = 0.34 + baseLife * 0.66;

  const baseProfiles: Record<RingStyle, [number, number, number]> = {
    SPIKE: [30, 7.4, 1.5],
    WAVE: [58, 5.2, 5],
    SPUTTER: [72, 5, 4.5],
  };

  const base = fullInterference
    ? ([34, 4.3, 3.8] as [number, number, number])
    : baseProfiles[profile.style];

  // AIDAInternalOrb multiplies span by 1.12, displacement by
  // internal_scale*1.24, then AIDAStatusOrb raises RED severity again.
  const span = base[0] * 1.12 * 1.25;
  const radialAmplitude =
    base[1] * INTERNAL_SCALE * 1.24 * 1.75;
  const tangentAmplitude =
    base[2] * INTERNAL_SCALE * 1.24 * 1.85;

  const centers = fullInterference
    ? [0, 86, 176, 268].map((offset) => wrapped(profile.centerAngle + offset))
    : [profile.centerAngle];

  let delta: number | null = null;
  let best = Number.POSITIVE_INFINITY;
  for (const center of centers) {
    const candidate = angularDelta(angle, center);
    if (Math.abs(candidate) <= span / 2 && Math.abs(candidate) < best) {
      delta = candidate;
      best = Math.abs(candidate);
    }
  }

  if (delta === null) {
    return { x: 0, y: 0, energy: 0 };
  }

  const local = delta / (span / 2);
  const window = Math.max(0, 1 - Math.abs(local)) ** 2;
  const strength = life * redFraction;
  const bucket = Math.floor((elapsed / 1000) * 120);
  const rng = seededRandom(profile.seed + index * 97 + bucket * 271);

  let radial = 0;
  let tangent = 0;

  if (!fullInterference && profile.style === 'SPIKE') {
    radial = radialAmplitude * window ** 2.65 * strength;
    tangent = randomSigned(rng, 0.42) * tangentAmplitude * strength;
  } else if (!fullInterference && profile.style === 'WAVE') {
    radial =
      radialAmplitude *
      Math.sin(local * Math.PI * 3) *
      window *
      strength;
    tangent =
      tangentAmplitude *
      Math.cos(local * Math.PI * 2.25) *
      window *
      strength;
  } else if (!fullInterference && profile.style === 'SPUTTER') {
    if (rng() < 0.28) {
      return { x: 0, y: 0, energy: 0 };
    }
    radial =
      randomBetweenWith(rng, -radialAmplitude * 0.3, radialAmplitude) *
      window *
      strength;
    tangent =
      randomBetweenWith(rng, -tangentAmplitude, tangentAmplitude) *
      window *
      strength;
  } else {
    radial =
      randomBetweenWith(rng, -radialAmplitude * 0.4, radialAmplitude) *
      window *
      strength;
    tangent =
      randomBetweenWith(rng, -tangentAmplitude, tangentAmplitude) *
      window *
      strength;
  }

  const radialVectorValue = radialVector(angle);
  const tangentVectorValue = tangentVector(angle);
  return {
    x:
      radialVectorValue.x * radial +
      tangentVectorValue.x * tangent,
    y:
      radialVectorValue.y * radial +
      tangentVectorValue.y * tangent,
    energy: Math.min(1, window * life * redFraction),
  };
}

function buildCorePlan(profile: CoreProfile | null, now: number): CorePlan {
  if (!profile) {
    return {
      layers: [{ id: 'stable', x: 0, y: 0, opacity: 1 }],
      covers: [],
      sputters: [],
    };
  }

  const stage = profile.stages[profile.stageIndex];
  const progress = clamp01(
    (now - profile.stageStartedAt) / stage.durationMs,
  );

  if (profile.id === 3) {
    return buildInterferenceCorePlan(profile, now);
  }

  if (stage.name === 'split') {
    const rng = coreBucketRng(profile, now, 20, 1);
    const offset = pick(rng, [3, 4, 5, 6]);
    const yJitter = pick(rng, [-1, 0, 0, 1]);
    const flicker = pick(rng, [0.62, 0.74, 0.86, 1]);
    const halfWidth = CORE_BOX.width / 2;
    const bandY = CENTER + randomBetweenWith(
      rng,
      -CORE_RADIUS * 0.55,
      CORE_RADIUS * 0.55,
    );

    return {
      layers: [
        {
          id: 'split-ghost',
          x: 0,
          y: 0,
          opacity: 0.16,
          clip: CORE_BOX,
        },
        {
          id: 'split-left',
          x: -offset,
          y: yJitter,
          opacity: flicker,
          clip: {
            x: CORE_BOX.x,
            y: CORE_BOX.y,
            width: halfWidth,
            height: CORE_BOX.height,
          },
        },
        {
          id: 'split-right',
          x: offset,
          y: -yJitter,
          opacity: flicker,
          clip: {
            x: CENTER,
            y: CORE_BOX.y,
            width: halfWidth,
            height: CORE_BOX.height,
          },
        },
        {
          id: 'split-band',
          x: pick(rng, [-7, -5, 5, 7]),
          y: 0,
          opacity: pick(rng, [0.48, 0.72, 0.92]),
          clip: {
            x: CORE_BOX.x,
            y: bandY,
            width: CORE_BOX.width,
            height: pick(rng, [1.8, 2.2, 2.8]),
          },
        },
      ],
      covers: [],
      sputters: [],
    };
  }

  if (stage.name === 'fracture') {
    const rng = coreBucketRng(profile, now, 22, 2);
    const yOffsets = [-7, -3, 0.5, 4, 7];
    const layers: CoreLayer[] = [
      {
        id: 'fracture-base',
        x: pick(rng, [-2, -1, 0, 0, 1, 2]),
        y: pick(rng, [-1, 0, 0, 1]),
        opacity: pick(rng, [0.34, 0.52, 0.7, 0.86, 1, 1]),
      },
    ];
    const covers: CoverBand[] = [];
    const sputters: SputterLine[] = [];

    yOffsets.forEach((offset, index) => {
      const height = pick(rng, [1.8, 2.2, 2.8, 3.2]);
      const clip = {
        x: CENTER - CORE_RADIUS * 1.75,
        y: CENTER + offset,
        width: CORE_RADIUS * 3.5,
        height,
      };
      covers.push({
        id: `fracture-cover-${index}`,
        ...clip,
        opacity: pick(rng, [0.72, 0.86, 0.96]),
      });
      if (rng() >= 0.22 || index % 2 === 0) {
        layers.push({
          id: `fracture-band-${index}`,
          x: pick(rng, [-6, -4, -3, 3, 4, 6]),
          y: pick(rng, [-1, 0, 0, 1]),
          opacity: pick(rng, [0.48, 0.66, 0.84, 1]),
          clip,
        });
      }
      if (rng() < 0.55) {
        sputters.push({
          id: `fracture-sputter-${index}`,
          x: clip.x + randomBetweenWith(rng, 0, clip.width * 0.6),
          y: clip.y + randomBetweenWith(rng, -1, 1),
          width: randomBetweenWith(rng, 3, 10),
          height: randomBetweenWith(rng, 0.5, 1.15),
          opacity: randomBetweenWith(rng, 0.35, 0.9),
        });
      }
    });

    return { layers, covers, sputters };
  }

  if (stage.name === 'collapse') {
    const levels = [1, 0.78, 0.56, 0.34, 0.18, 0.1];
    const index = Math.min(
      levels.length - 1,
      Math.floor(progress * levels.length),
    );
    const rng = coreBucketRng(profile, now, 24, 3);
    return {
      layers: [
        {
          id: 'collapse',
          x: pick(rng, [-1, 0, 0, 1]),
          y: 0,
          opacity: pick(rng, [0.42, 0.6, 0.78, 1, 1]),
          scaleY: levels[index],
        },
      ],
      covers: [],
      sputters: [],
    };
  }

  if (stage.name === 'phase_jump') {
    const rng = coreBucketRng(profile, now, 18, 4);
    const dx = pick(rng, [-4, -3, -2, 0, 0, 2, 3, 4]);
    const dy = pick(rng, [-2, -1, 0, 0, 1, 2]);
    const layers: CoreLayer[] = [
      {
        id: 'phase-ghost',
        x: 0,
        y: 0,
        opacity: 0.1,
        clip: CORE_BOX,
      },
      {
        id: 'phase-main',
        x: dx,
        y: dy,
        opacity: pick(rng, [0.42, 0.58, 0.74, 0.9, 1, 1]),
        clip: CORE_BOX,
      },
    ];

    for (let index = 0; index < 2; index += 1) {
      layers.push({
        id: `phase-band-${index}`,
        x: dx + pick(rng, [-4, -2, 2, 4]),
        y: dy,
        opacity: pick(rng, [0.38, 0.62, 0.88]),
        clip: {
          x: CORE_BOX.x,
          y:
            CENTER +
            randomBetweenWith(
              rng,
              -CORE_RADIUS * 0.7,
              CORE_RADIUS * 0.7,
            ),
          width: CORE_BOX.width,
          height: pick(rng, [1.5, 2, 2.6]),
        },
      });
    }

    return { layers, covers: [], sputters: [] };
  }

  if (stage.name === 'radial_tear') {
    const rng = coreBucketRng(profile, now, 22, 5);
    const layers: CoreLayer[] = [
      {
        id: 'tear-base',
        x: pick(rng, [-2, -1, 0, 0, 1, 2]),
        y: pick(rng, [-1, 0, 0, 1]),
        opacity: pick(rng, [0.28, 0.42, 0.58, 0.76, 0.92, 1, 1]),
      },
    ];
    const covers: CoverBand[] = [];
    const sputters: SputterLine[] = [];

    for (let index = 0; index < 6; index += 1) {
      const y =
        CENTER - CORE_RADIUS * 0.82 +
        index * ((CORE_RADIUS * 1.64) / 5) +
        randomBetweenWith(rng, -1.2, 1.2);
      const height = randomBetweenWith(rng, 1.2, 2.7);
      const clip = {
        x: CENTER - CORE_RADIUS * 1.72,
        y,
        width: CORE_RADIUS * 3.44,
        height,
      };
      covers.push({
        id: `tear-cover-${index}`,
        ...clip,
        opacity: randomBetweenWith(rng, 0.5, 0.94),
      });

      if (rng() > 0.24) {
        layers.push({
          id: `tear-band-${index}`,
          x: pick(rng, [-4, -3, -2, 2, 3, 4]),
          y: pick(rng, [-1, 0, 0, 1]),
          opacity: randomBetweenWith(rng, 0.45, 1),
          clip,
        });
      }

      if (rng() < 0.7) {
        sputters.push({
          id: `tear-sputter-${index}`,
          x: clip.x + randomBetweenWith(rng, -2, clip.width * 0.75),
          y: y + randomBetweenWith(rng, -1.5, 1.5),
          width: randomBetweenWith(rng, 2.5, 9),
          height: randomBetweenWith(rng, 0.45, 1.1),
          opacity: randomBetweenWith(rng, 0.4, 0.95),
        });
      }
    }

    return { layers, covers, sputters };
  }

  if (stage.name === 'recover') {
    const eased = 1 - (1 - progress) ** 2;
    if (profile.id === 1) {
      const levels = [0.12, 0.28, 0.48, 0.7, 0.86, 1];
      const index = Math.min(
        levels.length - 1,
        Math.floor(eased * levels.length),
      );
      return {
        layers: [
          {
            id: 'recover-collapse',
            x: 0,
            y: 0,
            opacity: 1,
            scaleY: levels[index],
          },
        ],
        covers: [],
        sputters: [],
      };
    }

    const rng = coreBucketRng(profile, now, 18, 6);
    const amplitude = (1 - eased) * 4;
    const dx = pick(rng, [-1, 0, 0, 1]) * amplitude;
    const dy = pick(rng, [-1, 0, 0, 1]) * Math.min(1.5, amplitude);
    return {
      layers: [
        {
          id: 'recover-ghost',
          x: -dx,
          y: -dy,
          opacity: 0.22 * (1 - eased),
        },
        {
          id: 'recover-main',
          x: dx,
          y: dy,
          opacity: 1,
        },
      ],
      covers: [],
      sputters: [],
    };
  }

  return {
    layers: [{ id: 'fallback', x: 0, y: 0, opacity: 1 }],
    covers: [],
    sputters: [],
  };
}

function buildInterferenceCorePlan(
  profile: CoreProfile,
  now: number,
): CorePlan {
  const rng = coreBucketRng(profile, now, 24, 7);
  const layers: CoreLayer[] = [
    {
      id: 'interference-ghost',
      x: 0,
      y: 0,
      opacity: 0.12,
      clip: CORE_BOX,
    },
  ];
  const covers: CoverBand[] = [];
  const sputters: SputterLine[] = [];

  for (let index = 0; index < 7; index += 1) {
    const y =
      CORE_BOX.y +
      index * (CORE_BOX.height / 7) +
      randomBetweenWith(rng, -1.3, 1.3);
    const height = randomBetweenWith(rng, 2.1, 4.1);
    const clip = {
      x: CORE_BOX.x - 2,
      y,
      width: CORE_BOX.width + 4,
      height,
    };
    covers.push({
      id: `interference-cover-${index}`,
      ...clip,
      opacity: randomBetweenWith(rng, 0.62, 0.98),
    });
    layers.push({
      id: `interference-band-${index}`,
      x: pick(rng, [-8, -6, -4, 4, 6, 8]),
      y: pick(rng, [-2, -1, 0, 1, 2]),
      opacity: randomBetweenWith(rng, 0.48, 1),
      clip,
    });
    if (rng() < 0.82) {
      sputters.push({
        id: `interference-sputter-${index}`,
        x: CORE_BOX.x + randomBetweenWith(rng, -5, CORE_BOX.width * 0.8),
        y: y + randomBetweenWith(rng, -2, 2),
        width: randomBetweenWith(rng, 3, 14),
        height: randomBetweenWith(rng, 0.5, 1.35),
        opacity: randomBetweenWith(rng, 0.5, 1),
      });
    }
  }

  return { layers, covers, sputters };
}

function fullOffset(profile: CoreProfile, layer: number, now: number) {
  const elapsed = Math.max(0, now - profile.stageStartedAt);
  const progress = clamp01(elapsed / 3_000);
  const baseLife = Math.sin(progress * Math.PI);
  const life = 0.34 + baseLife * 0.66;
  const bucket = Math.floor((elapsed / 1000) * 120);
  const rng = seededRandom(profile.seed + layer * 811 + bucket * 313);
  const amplitude = 1.8 * INTERNAL_SCALE * 1.18 * 2.4 * life;
  return {
    x: randomBetweenWith(rng, -amplitude, amplitude),
    y: randomBetweenWith(rng, -amplitude, amplitude),
  };
}

function buildTransitionPulse(
  state: AidaOrbVisualState,
  transition: { from: AidaOrbVisualState; startedAt: number } | null,
  progress: number,
) {
  if (!transition || progress >= 1) {
    return null;
  }
  const eased = 1 - (1 - progress) ** 2;
  const radius = 3 + eased * (ORB_DIAMETER * 0.53);
  return {
    radius,
    color: PALETTES[state].bright,
    opacity: clamp01((210 * Math.sin(progress * Math.PI)) / 255),
  };
}

function paletteForLayer(
  layer: LayerName,
  target: AidaOrbVisualState,
  transition: { from: AidaOrbVisualState; startedAt: number } | null,
  transitionAmount: number,
): Palette {
  if (!transition) {
    return PALETTES[target];
  }
  const progress = layerProgress(layer, transitionAmount);
  const source = PALETTES[transition.from];
  const destination = PALETTES[target];
  return {
    base: mixHex(source.base, destination.base, progress),
    bright: mixHex(source.bright, destination.bright, progress),
    hot: mixHex(source.hot, destination.hot, progress),
    deep: mixHex(source.deep, destination.deep, progress),
    edge: mixHex(source.edge, destination.edge, progress),
  };
}

function redLayerFraction(
  layer: LayerName,
  target: AidaOrbVisualState,
  transition: { from: AidaOrbVisualState; startedAt: number } | null,
  transitionAmount: number,
) {
  if (!transition) {
    return target === 'RED' ? 1 : 0;
  }
  const progress = layerProgress(layer, transitionAmount);
  const sourceRed = transition.from === 'RED';
  const targetRed = target === 'RED';
  if (sourceRed && targetRed) {
    return 1;
  }
  if (sourceRed) {
    return 1 - progress;
  }
  if (targetRed) {
    return progress;
  }
  return 0;
}

function transitionProgress(
  transition: { from: AidaOrbVisualState; startedAt: number } | null,
  now: number,
) {
  if (!transition) {
    return 1;
  }
  return clamp01((now - transition.startedAt) / STATE_TRANSITION_MS);
}

function layerProgress(layer: LayerName, progress: number) {
  if (layer === 'core') {
    return clamp01(progress / 0.48);
  }
  if (layer === 'ambient') {
    return clamp01(progress / 0.62);
  }
  if (layer === 'data') {
    return clamp01((progress - 0.16) / 0.56);
  }
  return clamp01((progress - 0.36) / 0.64);
}

function ringColor(
  angle: number,
  palette: Palette,
  hotRotation: number,
  coolRotation: number,
) {
  if (angleInArc(angle, hotRotation, 68)) {
    return palette.hot;
  }
  if (angleInArc(angle, coolRotation, 50)) {
    return palette.base;
  }
  return palette.bright;
}

function arcPath(
  cx: number,
  cy: number,
  radius: number,
  start: number,
  span: number,
) {
  const first = polarPoint(cx, cy, radius, start);
  const last = polarPoint(cx, cy, radius, start + span);
  const largeArc = Math.abs(span) > 180 ? 1 : 0;
  const sweep = span >= 0 ? 0 : 1;
  return `M ${first.x} ${first.y} A ${radius} ${radius} 0 ${largeArc} ${sweep} ${last.x} ${last.y}`;
}

function polarPoint(
  cx: number,
  cy: number,
  radius: number,
  angle: number,
) {
  const radians = degreesToRadians(angle);
  return {
    x: cx + Math.cos(radians) * radius,
    y: cy - Math.sin(radians) * radius,
  };
}

function radialVector(angle: number) {
  const radians = degreesToRadians(angle);
  return { x: Math.cos(radians), y: -Math.sin(radians) };
}

function tangentVector(angle: number) {
  const radians = degreesToRadians(angle);
  return { x: -Math.sin(radians), y: -Math.cos(radians) };
}

function motionScaleFor(status: AidaRuntimeStatus) {
  switch (status) {
    case 'CONNECTING':
      return 1.25;
    case 'STANDBY':
      return 0.72;
    case 'ANALYZING':
      return 2.15;
    case 'WARNING':
      return 1.3;
    case 'ERROR':
      return 1.2;
    case 'OFFLINE':
      return 0.3;
    default:
      return 1;
  }
}

function coreBucketRng(
  profile: CoreProfile,
  now: number,
  rate: number,
  salt: number,
) {
  const elapsed = Math.max(0, now - profile.stageStartedAt) / 1000;
  const bucket = Math.floor(elapsed * rate);
  return seededRandom(profile.seed + bucket * 137 + salt * 10_007);
}

function seededRandom(seed: number) {
  let value = seed >>> 0;
  return () => {
    value += 0x6d2b79f5;
    let result = value;
    result = Math.imul(result ^ (result >>> 15), result | 1);
    result ^= result + Math.imul(result ^ (result >>> 7), result | 61);
    return ((result ^ (result >>> 14)) >>> 0) / 4_294_967_296;
  };
}

function pick<T>(rng: () => number, values: T[]) {
  return values[Math.floor(rng() * values.length)];
}

function randomBetween(minimum: number, maximum: number) {
  return minimum + Math.random() * (maximum - minimum);
}

function randomBetweenWith(
  rng: () => number,
  minimum: number,
  maximum: number,
) {
  return minimum + rng() * (maximum - minimum);
}

function randomSigned(rng: () => number, magnitude: number) {
  return randomBetweenWith(rng, -magnitude, magnitude);
}

function randomSeed() {
  return Math.floor(Math.random() * 1_000_001);
}

function angleInArc(angle: number, start: number, span: number) {
  return wrapped(angle - start) <= span;
}

function angularDelta(angle: number, center: number) {
  return ((angle - center + 540) % 360) - 180;
}

function wrapped(angle: number) {
  return ((angle % 360) + 360) % 360;
}

function degreesToRadians(angle: number) {
  return (angle * Math.PI) / 180;
}

function clamp01(value: number) {
  return Math.min(1, Math.max(0, value));
}

function mixHex(first: string, second: string, progress: number) {
  const a = hexToRgb(first);
  const b = hexToRgb(second);
  const p = clamp01(progress);
  return rgbToHex(
    Math.round(a.r + (b.r - a.r) * p),
    Math.round(a.g + (b.g - a.g) * p),
    Math.round(a.b + (b.b - a.b) * p),
  );
}

function hexToRgb(value: string) {
  const clean = value.replace('#', '');
  return {
    r: Number.parseInt(clean.slice(0, 2), 16),
    g: Number.parseInt(clean.slice(2, 4), 16),
    b: Number.parseInt(clean.slice(4, 6), 16),
  };
}

function rgbToHex(red: number, green: number, blue: number) {
  return `#${[red, green, blue]
    .map((component) => component.toString(16).padStart(2, '0'))
    .join('')}`;
}

function clockNow() {
  return typeof performance !== 'undefined' && performance.now
    ? performance.now()
    : Date.now();
}

const styles = StyleSheet.create({
  wrapper: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 8,
  },
  statusLabel: {
    marginTop: 3,
    fontFamily: AIDA_FONTS.mono,
    fontSize: 9,
    fontWeight: '700',
    letterSpacing: 1.55,
  },
});
