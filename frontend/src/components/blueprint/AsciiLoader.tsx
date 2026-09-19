import React, { useState, useEffect } from 'react';

interface AsciiLoaderProps {
  progress?: number; // 0 to 100
  label?: string;
  totalLength?: number;
  className?: string;
}

export const AsciiLoader: React.FC<AsciiLoaderProps> = ({
  progress,
  label = 'PROCESSING EXCAVATION',
  totalLength = 24,
  className = '',
}) => {
  const [frame, setFrame] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setFrame((f) => (f + 1) % 4);
    }, 180);
    return () => clearInterval(timer);
  }, []);

  const glyphs = ['/', '—', '\\', '|'];
  const currentGlyph = glyphs[frame];

  const calculatedProgress = progress !== undefined ? Math.min(100, Math.max(0, progress)) : null;

  const renderAsciiBar = () => {
    if (calculatedProgress !== null) {
      const filled = Math.round((calculatedProgress / 100) * totalLength);
      const empty = totalLength - filled;
      return `[${'='.repeat(Math.max(0, filled - 1))}${filled > 0 ? '>' : ''}${' '.repeat(empty)}] ${calculatedProgress}%`;
    }

    // Indeterminate ASCII sweep
    const pos = (frame * 6) % totalLength;
    const bar = Array.from({ length: totalLength }).map((_, i) =>
      Math.abs(i - pos) < 3 ? '■' : '·'
    ).join('');
    return `[${bar}]`;
  };

  return (
    <div className={`flex flex-col gap-1.5 p-3 bg-[#0D0D0E] border border-[#26262A] select-none ${className}`}>
      <div className="flex items-center justify-between font-mono text-[10px]">
        <span className="text-[#8A8A85] tracking-[0.08em] uppercase flex items-center gap-1.5">
          <span className="text-[#E8A33D] font-bold">{currentGlyph}</span>
          {label}
        </span>
        <span className="text-[#55554F] uppercase">PIPELINE_ACTIVE</span>
      </div>
      <div className="font-mono text-xs text-[#E8A33D] tracking-widest whitespace-pre bg-[#0A0A0B] p-2 border border-[#26262A]">
        {renderAsciiBar()}
      </div>
    </div>
  );
};
