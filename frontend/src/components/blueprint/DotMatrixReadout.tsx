import React from 'react';

interface DotMatrixReadoutProps {
  label: string;
  rows?: number;
  cols?: number;
  activeCount: number;
  totalCount?: number;
  statusText?: string;
  className?: string;
}

export const DotMatrixReadout: React.FC<DotMatrixReadoutProps> = ({
  label,
  rows = 4,
  cols = 16,
  activeCount,
  totalCount = rows * cols,
  statusText,
  className = '',
}) => {
  const totalDots = rows * cols;
  const normalizedActive = Math.round((activeCount / Math.max(1, totalCount)) * totalDots);

  return (
    <div className={`flex flex-col gap-1.5 select-none ${className}`}>
      <div className="flex justify-between items-baseline font-mono text-[10px]">
        <span className="text-[#8A8A85] tracking-[0.08em] uppercase">{label}</span>
        <span className="text-[#E8A33D] font-mono font-medium">
          {statusText || `${activeCount}/${totalCount}`}
        </span>
      </div>

      <div
        className="grid gap-[3px] p-1.5 bg-[#0A0A0B] border border-[#26262A]"
        style={{
          gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
        }}
      >
        {Array.from({ length: totalDots }).map((_, i) => {
          const isActive = i < normalizedActive;
          return (
            <div
              key={i}
              className={`w-1.5 h-1.5 transition-colors duration-100 ${
                isActive
                  ? i % 5 === 0
                    ? 'bg-[#E8A33D]'
                    : 'bg-[#E8E8E6]'
                  : 'bg-[#202024]'
              }`}
            />
          );
        })}
      </div>
    </div>
  );
};
