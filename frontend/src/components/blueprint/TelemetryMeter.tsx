import React from 'react';

interface TelemetryMeterProps {
  label: string;
  value: number; // 0 to 100 or actual count
  max?: number;
  totalSegments?: number;
  unit?: string;
  amberThreshold?: number; // percentage above which it turns amber
  criticalThreshold?: number; // percentage above which it turns critical red
  className?: string;
}

export const TelemetryMeter: React.FC<TelemetryMeterProps> = ({
  label,
  value,
  max = 100,
  totalSegments = 16,
  unit = '%',
  amberThreshold = 60,
  criticalThreshold = 85,
  className = '',
}) => {
  const percentage = Math.min(100, Math.max(0, (value / max) * 100));
  const activeSegments = Math.round((percentage / 100) * totalSegments);

  const getSegmentColor = (index: number) => {
    const segPercentage = (index / totalSegments) * 100;
    if (segPercentage >= criticalThreshold) return 'bg-[#FF4D4D]';
    if (segPercentage >= amberThreshold) return 'bg-[#E8A33D]';
    return 'bg-[#E8E8E6]';
  };

  return (
    <div className={`flex flex-col gap-1 select-none ${className}`}>
      <div className="flex justify-between items-baseline font-mono text-[10px]">
        <span className="text-[#8A8A85] tracking-[0.08em] uppercase">{label}</span>
        <span className="text-[#E8E8E6] font-semibold">
          {value.toLocaleString()} {unit}
        </span>
      </div>

      {/* Discrete Segmented Bar */}
      <div className="flex gap-[2px] items-center h-2 bg-[#0A0A0B] p-[1px] border border-[#26262A]">
        {Array.from({ length: totalSegments }).map((_, i) => {
          const isActive = i < activeSegments;
          return (
            <div
              key={i}
              className={`flex-1 h-full transition-colors duration-150 ${
                isActive ? getSegmentColor(i) : 'bg-[#18181B]'
              }`}
            />
          );
        })}
      </div>
    </div>
  );
};
