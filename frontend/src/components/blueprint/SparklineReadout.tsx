import React from 'react';

interface SparklineReadoutProps {
  data: number[];
  label: string;
  metric: string;
  height?: number;
  className?: string;
}

export const SparklineReadout: React.FC<SparklineReadoutProps> = ({
  data,
  label,
  metric,
  height = 24,
  className = '',
}) => {
  const points = data.length > 0 ? data : [10, 15, 12, 20, 25, 18, 30, 28, 35, 42];
  const max = Math.max(...points, 1);
  const min = Math.min(...points, 0);
  const range = max - min || 1;

  const width = 120;
  const svgPoints = points
    .map((val, idx) => {
      const x = (idx / (points.length - 1)) * width;
      const y = height - ((val - min) / range) * (height - 4) - 2;
      return `${x},${y}`;
    })
    .join(' ');

  return (
    <div className={`flex flex-col gap-1 select-none ${className}`}>
      <div className="flex justify-between items-baseline font-mono text-[10px]">
        <span className="text-[#8A8A85] tracking-[0.08em] uppercase">{label}</span>
        <span className="text-[#E8E8E6] font-semibold">{metric}</span>
      </div>
      <div className="relative bg-[#0A0A0B] border border-[#26262A] p-1 h-[32px] flex items-center">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="w-full h-full overflow-visible"
          preserveAspectRatio="none"
        >
          <polyline
            fill="none"
            stroke="#55554F"
            strokeWidth="1"
            strokeDasharray="2 2"
            points={`0,${height / 2} ${width},${height / 2}`}
          />
          <polyline
            fill="none"
            stroke="#E8A33D"
            strokeWidth="1.5"
            strokeLinecap="square"
            strokeLinejoin="miter"
            points={svgPoints}
          />
        </svg>
      </div>
    </div>
  );
};
