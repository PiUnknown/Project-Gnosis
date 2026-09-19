import React from 'react';
import { DoodleSlot } from './DoodleSlot';

interface EmptySchematicProps {
  caption?: string;
  coord?: string;
  doodleId?: string; // "compass" | "map" | "folder"
  doodleSize?: number; // 96-180px
  className?: string;
}

export const EmptySchematic: React.FC<EmptySchematicProps> = ({
  caption = 'NO ARTIFACT LOADED // SPECIFY REPOSITORY OR INITIALIZE EXCAVATION',
  coord = 'GRID [00, 00]',
  doodleId,
  doodleSize = 120,
  className = '',
}) => {
  return (
    <div
      className={`border border-dashed border-[#26262A] bg-[#0C0C0E] p-8 flex flex-col items-center justify-center text-center select-none ${className}`}
    >
      {doodleId ? (
        <div className="mb-4 flex flex-col items-center justify-center">
          <DoodleSlot
            doodleId={doodleId}
            size={doodleSize}
            label={coord}
            opacity={0.85}
          />
        </div>
      ) : (
        /* Blueprint wireframe box fallback */
        <div className="relative w-40 h-24 border border-[#26262A] flex items-center justify-center mb-4">
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <svg className="w-full h-full stroke-[#26262A]" strokeWidth="0.75">
              <line x1="0" y1="0" x2="100%" y2="100%" strokeDasharray="3 3" />
              <line x1="100%" y1="0" x2="0" y2="100%" strokeDasharray="3 3" />
              <rect x="25%" y="25%" width="50%" height="50%" fill="none" stroke="#333338" />
            </svg>
          </div>
          <span className="font-mono text-[9px] text-[#55554F] bg-[#0C0C0E] px-1 z-10">
            {coord}
          </span>
        </div>
      )}

      <div className="font-mono text-[10px] uppercase tracking-[0.08em] text-[#8A8A85] max-w-sm mt-1">
        {caption}
      </div>
    </div>
  );
};
