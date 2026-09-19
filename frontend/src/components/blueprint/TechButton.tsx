import React from 'react';

interface TechButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'amber' | 'ghost' | 'danger';
  size?: 'sm' | 'md' | 'lg';
  active?: boolean;
  glyph?: string;
  isLoading?: boolean;
}

export const TechButton: React.FC<TechButtonProps> = ({
  children,
  variant = 'default',
  size = 'md',
  active = false,
  glyph,
  isLoading = false,
  className = '',
  disabled,
  ...props
}) => {
  const sizeClasses = {
    sm: 'px-2 py-1 text-[10px]',
    md: 'px-3.5 py-1.5 text-[11px]',
    lg: 'px-5 py-2.5 text-[12px]',
  }[size];

  const getVariantStyles = () => {
    if (disabled) {
      return 'bg-[#121214] text-[#55554F] border-[#26262A] cursor-not-allowed opacity-60';
    }
    if (active) {
      return 'bg-[#E8A33D] text-[#0A0A0B] border-[#E8A33D] font-semibold';
    }
    switch (variant) {
      case 'amber':
        return 'bg-[#E8A33D] text-[#0A0A0B] border-[#E8A33D] hover:bg-[#d6932e] font-semibold';
      case 'ghost':
        return 'bg-transparent text-[#8A8A85] border-transparent hover:border-[#26262A] hover:text-[#E8E8E6] hover:bg-[#121214]';
      case 'danger':
        return 'bg-[#121214] text-[#FF4D4D] border-[#FF4D4D]/40 hover:bg-[#FF4D4D] hover:text-[#0A0A0B]';
      case 'default':
      default:
        return 'bg-[#121214] text-[#E8E8E6] border-[#26262A] hover:bg-[#E8E8E6] hover:text-[#0A0A0B]';
    }
  };

  return (
    <button
      disabled={disabled || isLoading}
      className={`font-mono uppercase tracking-[0.08em] border transition-colors duration-75 flex items-center justify-center gap-1.5 select-none ${sizeClasses} ${getVariantStyles()} ${className}`}
      style={{ borderRadius: '0px' }}
      {...props}
    >
      {isLoading ? (
        <span className="ascii-blink">[EXEC...]</span>
      ) : (
        <>
          {glyph && <span className="text-[#55554F] group-hover:text-inherit font-bold">{glyph}</span>}
          <span>{children}</span>
        </>
      )}
    </button>
  );
};
