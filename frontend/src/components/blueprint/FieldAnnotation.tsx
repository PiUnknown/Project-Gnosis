import React from 'react';

interface FieldAnnotationProps {
  type?: 'circle' | 'underline' | 'arrow-left' | 'bracket';
  label?: string;
  children: React.ReactNode;
  className?: string;
}

export const FieldAnnotation: React.FC<FieldAnnotationProps> = ({
  type = 'circle',
  label,
  children,
  className = '',
}) => {
  if (type === 'circle') {
    return (
      <span className={`relative inline-flex items-center justify-center p-0.5 ${className}`}>
        {/* Hand-drawn SVG Oval overlay */}
        <svg
          className="absolute -inset-1.5 w-[calc(100%+12px)] h-[calc(100%+10px)] pointer-events-none overflow-visible z-10"
          viewBox="0 0 100 40"
          preserveAspectRatio="none"
          fill="none"
        >
          <path
            d="M 6,20 C 6,9 25,4 52,4 C 80,4 94,10 94,20 C 94,30 75,36 48,36 C 20,36 6,31 6,20 Z"
            stroke="#E8A33D"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="opacity-95"
          />
        </svg>
        <span className="relative z-0 font-bold text-[#E8A33D]">{children}</span>
        {label && (
          <span className="absolute -top-4 -right-2 font-mono text-[8px] bg-[#0A0A0B] border border-[#E8A33D] text-[#E8A33D] px-1 py-0 uppercase tracking-wider font-semibold z-20 whitespace-nowrap shadow-none">
            {label}
          </span>
        )}
      </span>
    );
  }

  if (type === 'underline') {
    return (
      <span className={`relative inline-block ${className}`}>
        <span>{children}</span>
        {/* Hand-drawn underline */}
        <svg
          className="absolute -bottom-1 left-0 w-full h-2 pointer-events-none overflow-visible z-10"
          viewBox="0 0 100 8"
          preserveAspectRatio="none"
          fill="none"
        >
          <path
            d="M 2,4 C 30,7 65,1 98,5"
            stroke="#E8A33D"
            strokeWidth="1.8"
            strokeLinecap="round"
          />
        </svg>
        {label && (
          <span className="ml-2 font-mono text-[9px] text-[#E8A33D] uppercase tracking-wider font-medium">
            [{label}]
          </span>
        )}
      </span>
    );
  }

  if (type === 'arrow-left') {
    return (
      <span className={`inline-flex items-center gap-2 ${className}`}>
        <svg
          width="32"
          height="16"
          viewBox="0 0 32 16"
          fill="none"
          className="overflow-visible pointer-events-none shrink-0"
        >
          <path
            d="M 30,8 C 20,7 10,9 4,8"
            stroke="#E8A33D"
            strokeWidth="1.8"
            strokeLinecap="round"
          />
          <path
            d="M 9,3 L 3,8 L 9,13"
            stroke="#E8A33D"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <span>{children}</span>
        {label && (
          <span className="font-mono text-[9px] text-[#E8A33D] uppercase tracking-wider font-semibold">
            [{label}]
          </span>
        )}
      </span>
    );
  }

  return (
    <span className={`relative inline-block border-l-2 border-[#E8A33D] pl-2 ${className}`}>
      {children}
      {label && (
        <span className="block font-mono text-[9px] text-[#E8A33D] uppercase tracking-wider mt-0.5 font-medium">
          {label}
        </span>
      )}
    </span>
  );
};
