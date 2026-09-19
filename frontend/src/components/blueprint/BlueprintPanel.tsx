import React from 'react';
import { RegistrationMark } from './RegistrationMark';

interface BlueprintPanelProps {
  title?: string;
  glyph?: string;
  coord?: string;
  badge?: string;
  children: React.ReactNode;
  className?: string;
  headerRight?: React.ReactNode;
  showCorners?: boolean;
}

export const BlueprintPanel: React.FC<BlueprintPanelProps> = ({
  title,
  glyph = '[●]',
  coord,
  badge,
  children,
  className = '',
  headerRight,
  showCorners = true,
}) => {
  return (
    <div
      className={`relative bg-[#121214] border border-[#26262A] flex flex-col ${className}`}
      style={{ borderRadius: '0px' }}
    >
      {/* Corner crosshairs */}
      {showCorners && (
        <>
          <div className="absolute -top-[5px] -left-[5px] z-10 pointer-events-none">
            <RegistrationMark type="crosshair" />
          </div>
          <div className="absolute -top-[5px] -right-[5px] z-10 pointer-events-none">
            <RegistrationMark type="crosshair" />
          </div>
          <div className="absolute -bottom-[5px] -left-[5px] z-10 pointer-events-none">
            <RegistrationMark type="crosshair" />
          </div>
          <div className="absolute -bottom-[5px] -right-[5px] z-10 pointer-events-none">
            <RegistrationMark type="crosshair" />
          </div>
        </>
      )}

      {/* Header */}
      {(title || coord || headerRight) && (
        <div className="flex items-center justify-between px-3 py-2 border-b border-[#26262A] bg-[#101012] select-none">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] text-[#E8A33D] font-semibold">{glyph}</span>
            {title && (
              <span className="font-mono text-[10px] tracking-[0.08em] uppercase text-[#E8E8E6] font-medium">
                {title}
              </span>
            )}
            {badge && (
              <span className="font-mono text-[9px] px-1.5 py-0.5 border border-[#26262A] text-[#8A8A85] bg-[#0A0A0B]">
                {badge}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {coord && (
              <span className="font-mono text-[9px] tracking-wider text-[#55554F]">
                {coord}
              </span>
            )}
            {headerRight}
          </div>
        </div>
      )}

      {/* Panel Content */}
      <div className="flex-1 p-3">
        {children}
      </div>
    </div>
  );
};
