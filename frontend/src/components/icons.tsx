// Minimal inline SVG icon set (24px grid, stroke-based) — replaces emoji so
// rendering is consistent across Android/iOS Telegram webviews.

interface IconProps {
  size?: number;
  filled?: boolean;
  className?: string;
}

const base = (size: number) => ({
  width: size, height: size, viewBox: "0 0 24 24",
  fill: "none", stroke: "currentColor",
  strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const,
});

export const HeartIcon = ({ size = 26, filled, className }: IconProps) => (
  <svg {...base(size)} className={className} fill={filled ? "currentColor" : "none"}>
    <path d="M12 20.5s-7.5-4.7-9.5-9.2C1.1 8 3 4.5 6.6 4.5c2.2 0 3.9 1.3 4.7 2.7.1.2.5.2.6 0 .8-1.4 2.5-2.7 4.7-2.7 3.6 0 5.5 3.5 4.1 6.8-2 4.5-9.5 9.2-9.5 9.2z" />
  </svg>
);

export const LearnIcon = ({ size = 26, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="M2.5 9.5 12 4.5l9.5 5-9.5 5-9.5-5z" />
    <path d="M6.5 11.7v4.3c0 1.2 2.5 2.5 5.5 2.5s5.5-1.3 5.5-2.5v-4.3" />
    <path d="M21.5 9.5v5" />
  </svg>
);

export const ShareIcon = ({ size = 26, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <circle cx="6" cy="12" r="2.6" />
    <circle cx="17.5" cy="5.5" r="2.6" />
    <circle cx="17.5" cy="18.5" r="2.6" />
    <path d="M8.4 10.8 15.1 6.9M8.4 13.2l6.7 3.9" />
  </svg>
);

export const WalletIcon = ({ size = 22, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <rect x="2.5" y="6" width="19" height="13" rx="2.5" />
    <path d="M2.5 9.5h19" />
    <circle cx="17" cy="14.5" r="1.2" fill="currentColor" stroke="none" />
  </svg>
);

export const SettingsIcon = ({ size = 22, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 12a7.4 7.4 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7.5 7.5 0 0 0-2-1.2L14.5 3h-5l-.4 2.6a7.5 7.5 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7.5 7.5 0 0 0 2 1.2l.4 2.6h5l.4-2.6a7.5 7.5 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.06-.4.1-.8.1-1.2z" />
  </svg>
);

export const CameraIcon = ({ size = 24, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <rect x="2.5" y="6.5" width="14" height="11" rx="2.5" />
    <path d="M16.5 10.5 21.5 8v8l-5-2.5" />
  </svg>
);

export const PlayIcon = ({ size = 24, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <circle cx="12" cy="12" r="9.5" />
    <path d="M10 8.5 16 12l-6 3.5v-7z" fill="currentColor" stroke="none" />
  </svg>
);

export const UsersIcon = ({ size = 18, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <circle cx="9" cy="8.5" r="3.2" />
    <path d="M3 19.5c0-3 2.7-5 6-5s6 2 6 5" />
    <path d="M16 5.8a3.2 3.2 0 0 1 0 5.4M18.5 14.7c1.7.8 2.7 2.2 2.7 4" />
  </svg>
);

export const EyeIcon = ({ size = 15, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="M2 12s3.5-6.5 10-6.5S22 12 22 12s-3.5 6.5-10 6.5S2 12 2 12z" />
    <circle cx="12" cy="12" r="2.8" />
  </svg>
);

export const TargetIcon = ({ size = 15, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <circle cx="12" cy="12" r="9" />
    <circle cx="12" cy="12" r="5" />
    <circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none" />
  </svg>
);

export const UnlockIcon = ({ size = 15, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <rect x="4.5" y="10.5" width="15" height="10" rx="2" />
    <path d="M8 10.5V7a4 4 0 0 1 7.8-1.3" />
  </svg>
);

export const BackIcon = ({ size = 24, className }: IconProps) => (
  <svg {...base(size)} className={className}>
    <path d="M15 5l-7 7 7 7" />
  </svg>
);
