import React, { useState } from 'react';

export type DoodlePrimitive = 'circle' | 'arrow' | 'underline' | 'crosshair' | 'box';

interface DoodleSlotProps {
  doodleId?: string; // e.g. "compass", "map", "folder" -> /assets/doodles/{doodleId}.png
  size?: number; // 96-180px standard
  width?: number | string;
  height?: number | string;
  primitiveFallback?: DoodlePrimitive;
  label?: string;
  opacity?: number;
  className?: string;
}

export const DoodleSlot: React.FC<DoodleSlotProps> = ({
  doodleId,
  size = 120,
  width,
  height,
  primitiveFallback = 'circle',
  label,
  opacity = 0.9,
  className = '',
}) => {
  const [imgError, setImgError] = useState(false);

  // Compute resolved dimensions (constrained between 96px and 180px when size is used)
  const resolvedWidth = width ?? size;
  const resolvedHeight = height ?? size;

  // Resolve path: if doodleId already has extension use it, else default to .png
  const imageSrc = doodleId
    ? doodleId.includes('.')
      ? `/assets/doodles/${doodleId}`
      : `/assets/doodles/${doodleId}.png`
    : null;

  // Render Image if doodleId exists and has not failed
  if (imageSrc && !imgError) {
    return (
      <div
        className={`relative inline-flex flex-col items-center justify-center select-none pointer-events-none ${className}`}
        style={{ opacity }}
      >
        <img
          src={imageSrc}
          alt={label || doodleId || 'field annotation'}
          width={resolvedWidth}
          height={resolvedHeight}
          onError={() => setImgError(true)}
          className="object-contain max-w-full max-h-full"
          style={{ width: resolvedWidth, height: resolvedHeight }}
        />
        {label && (
          <span className="font-mono text-[9px] text-[#E8A33D] uppercase tracking-wider mt-1 font-medium">
            [{label}]
          </span>
        )}
      </div>
    );
  }

  // Graceful Monospace Text & Inline SVG Primitive Fallback
  const renderPrimitiveSvg = () => {
    switch (primitiveFallback) {
      case 'arrow':
        return (
          <svg
            width={resolvedWidth}
            height={typeof resolvedHeight === 'number' ? Math.min(36, resolvedHeight) : 36}
            viewBox="0 0 60 24"
            fill="none"
            className="overflow-visible"
          >
            <path
              d="M2 18 C 18 16, 36 8, 54 6"
              stroke="#E8A33D"
              strokeWidth="1.5"
              strokeLinecap="round"
              fill="none"
            />
            <path
              d="M48 2 L 56 6 L 49 11"
              stroke="#E8A33D"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              fill="none"
            />
          </svg>
        );

      case 'underline':
        return (
          <svg
            width={resolvedWidth}
            height={typeof resolvedHeight === 'number' ? Math.min(16, resolvedHeight) : 16}
            viewBox="0 0 80 12"
            fill="none"
            className="overflow-visible"
          >
            <path
              d="M2 6 C 24 9, 52 4, 78 7"
              stroke="#E8A33D"
              strokeWidth="1.5"
              strokeLinecap="round"
              fill="none"
            />
          </svg>
        );

      case 'crosshair':
        return (
          <svg
            width={resolvedWidth}
            height={resolvedHeight}
            viewBox="0 0 40 40"
            fill="none"
            className="overflow-visible"
          >
            <circle cx="20" cy="20" r="14" stroke="#E8A33D" strokeWidth="1.2" strokeDasharray="3 2" />
            <line x1="20" y1="2" x2="20" y2="38" stroke="#E8A33D" strokeWidth="1.2" />
            <line x1="2" y1="20" x2="38" y2="20" stroke="#E8A33D" strokeWidth="1.2" />
          </svg>
        );

      case 'box':
      case 'circle':
      default:
        return (
          <svg
            width={resolvedWidth}
            height={typeof resolvedHeight === 'number' ? Math.min(48, resolvedHeight) : 48}
            viewBox="0 0 70 32"
            fill="none"
            className="overflow-visible"
          >
            <path
              d="M6 16 C 6 8, 22 4, 42 4 C 60 4, 66 12, 64 20 C 62 26, 42 29, 20 28 C 8 27, 4 22, 5 15"
              stroke="#E8A33D"
              strokeWidth="1.5"
              strokeLinecap="round"
              fill="none"
            />
          </svg>
        );
    }
  };

  return (
    <div className={`relative inline-flex flex-col items-center justify-center gap-1 select-none pointer-events-none ${className}`}>
      {renderPrimitiveSvg()}
      <span className="font-mono text-[9px] text-[#55554F] uppercase tracking-wider">
        [FIELD_ANNOTATION: {label || (doodleId ? doodleId.toUpperCase() : 'SCHEMATIC_MARK')}]
      </span>
    </div>
  );
};
