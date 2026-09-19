import React from 'react';

interface RegistrationMarkProps {
  type?: 'crosshair' | 'corner' | 'tick' | 'coord';
  label?: string;
  className?: string;
}

export const RegistrationMark: React.FC<RegistrationMarkProps> = ({
  type = 'crosshair',
  label,
  className = '',
}) => {
  if (type === 'crosshair') {
    return (
      <span className={`font-mono text-[10px] text-[#55554F] select-none ${className}`}>
        +
      </span>
    );
  }

  if (type === 'coord') {
    return (
      <div className={`font-mono text-[9px] tracking-widest text-[#55554F] uppercase select-none ${className}`}>
        {label || 'SEC 01 // LAT 45.22'}
      </div>
    );
  }

  if (type === 'corner') {
    return (
      <div className={`relative w-2 h-2 pointer-events-none select-none ${className}`}>
        <div className="absolute top-0 left-0 w-2 h-[1px] bg-[#55554F]" />
        <div className="absolute top-0 left-0 w-[1px] h-2 bg-[#55554F]" />
      </div>
    );
  }

  return (
    <div className={`w-[1px] h-2 bg-[#3F3F46] select-none ${className}`} />
  );
};
