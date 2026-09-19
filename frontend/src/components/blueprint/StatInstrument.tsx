import React from 'react';

interface StatInstrumentProps {
  label: string;
  value: string | number;
  subValue?: string;
  glyph?: string;
  status?: 'nominal' | 'warning' | 'critical';
  className?: string;
}

export const StatInstrument: React.FC<StatInstrumentProps> = ({
  label,
  value,
  subValue,
  glyph,
  status = 'nominal',
  className = '',
}) => {
  const getStatusColor = () => {
    switch (status) {
      case 'critical':
        return 'text-[#FF4D4D] border-l-[#FF4D4D]';
      case 'warning':
        return 'text-[#E8A33D] border-l-[#E8A33D]';
      case 'nominal':
      default:
        return 'text-[#E8E8E6] border-l-[#26262A]';
    }
  };

  return (
    <div
      className={`bg-[#121214] border border-[#26262A] border-l-2 p-2.5 flex flex-col justify-between select-none ${getStatusColor()} ${className}`}
    >
      <div className="flex items-center justify-between font-mono text-[9px] text-[#55554F] tracking-[0.08em] uppercase">
        <span>{label}</span>
        {glyph && <span className="text-[#E8A33D]">{glyph}</span>}
      </div>

      <div className="mt-1 flex items-baseline gap-1.5">
        <span className="font-mono text-lg font-bold text-[#E8E8E6] tracking-tight">
          {value}
        </span>
        {subValue && (
          <span className="font-mono text-[9px] text-[#8A8A85]">
            {subValue}
          </span>
        )}
      </div>
    </div>
  );
};
