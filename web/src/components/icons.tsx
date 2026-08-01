import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function Base({ children, ...props }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      {...props}
    >
      {children}
    </svg>
  );
}

export const IconGauge = (p: IconProps) => (
  <Base {...p}>
    <path d="M12 20a8 8 0 1 0-8-8" />
    <path d="M4 12h2" />
    <path d="M12 20h8" />
    <path d="m12 12 4.5-3.5" />
    <circle cx="12" cy="12" r="1.4" />
  </Base>
);

export const IconData = (p: IconProps) => (
  <Base {...p}>
    <ellipse cx="12" cy="6" rx="7" ry="3" />
    <path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6" />
    <path d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" />
  </Base>
);

export const IconBox = (p: IconProps) => (
  <Base {...p}>
    <path d="M12 3 4 7v10l8 4 8-4V7z" />
    <path d="m4 7 8 4 8-4" />
    <path d="M12 21V11" />
  </Base>
);

export const IconFlow = (p: IconProps) => (
  <Base {...p}>
    <circle cx="6" cy="6" r="2.2" />
    <circle cx="18" cy="6" r="2.2" />
    <circle cx="12" cy="18" r="2.2" />
    <path d="M8.2 6h7.6" />
    <path d="M6 8.2V12a2 2 0 0 0 2 2h2" />
    <path d="M18 8.2V12a2 2 0 0 1-2 2h-2" />
  </Base>
);

export const IconPulse = (p: IconProps) => (
  <Base {...p}>
    <path d="M3 12h3.5l2-5 3 10 2.5-6 2 3H21" />
  </Base>
);

export const IconTerminal = (p: IconProps) => (
  <Base {...p}>
    <rect x="3" y="4" width="18" height="16" rx="2.4" />
    <path d="m7 10 2.5 2L7 14" />
    <path d="M12.5 14H17" />
  </Base>
);

export const IconSliders = (p: IconProps) => (
  <Base {...p}>
    <path d="M5 5v6M5 15v4M12 5v3M12 12v7M19 5v9M19 18v1" />
    <circle cx="5" cy="13" r="1.8" />
    <circle cx="12" cy="10" r="1.8" />
    <circle cx="19" cy="16" r="1.8" />
  </Base>
);

export const IconArrow = (p: IconProps) => (
  <Base {...p}>
    <path d="M5 12h13" />
    <path d="m13 6 6 6-6 6" />
  </Base>
);

export const IconCheck = (p: IconProps) => (
  <Base {...p}>
    <path d="m5 13 4 4 10-10" />
  </Base>
);

export const IconX = (p: IconProps) => (
  <Base {...p}>
    <path d="M6 6l12 12M18 6 6 18" />
  </Base>
);

export const IconPlay = (p: IconProps) => (
  <Base {...p}>
    <path d="M7 5l12 7-12 7z" />
  </Base>
);

export const IconRotate = (p: IconProps) => (
  <Base {...p}>
    <path d="M4 12a8 8 0 1 1 3 6.2" />
    <path d="M4 19v-5h5" />
  </Base>
);

export const IconBolt = (p: IconProps) => (
  <Base {...p}>
    <path d="M13 3 5 14h5l-1 7 8-11h-5z" />
  </Base>
);

export const IconShield = (p: IconProps) => (
  <Base {...p}>
    <path d="M12 3l7 3v6c0 4.2-2.9 7.6-7 9-4.1-1.4-7-4.8-7-9V6z" />
    <path d="m9 12 2 2 4-4" />
  </Base>
);

export const IconGithub = (p: IconProps) => (
  <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden {...p}>
    <path d="M12 2a10 10 0 0 0-3.16 19.49c.5.09.68-.22.68-.48v-1.7c-2.78.6-3.37-1.34-3.37-1.34-.45-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.89 1.53 2.34 1.09 2.91.83.09-.65.35-1.09.63-1.34-2.22-.25-4.56-1.11-4.56-4.95 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02a9.6 9.6 0 0 1 5 0c1.91-1.29 2.75-1.02 2.75-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.59 1.03 2.68 0 3.85-2.34 4.7-4.57 4.95.36.31.68.92.68 1.85v2.74c0 .27.18.58.69.48A10 10 0 0 0 12 2Z" />
  </svg>
);

export const IconExternal = (p: IconProps) => (
  <Base {...p}>
    <path d="M14 5h5v5" />
    <path d="M19 5l-8 8" />
    <path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4" />
  </Base>
);

export const IconLayers = (p: IconProps) => (
  <Base {...p}>
    <path d="m12 3 8 4-8 4-8-4z" />
    <path d="m4 12 8 4 8-4" />
    <path d="m4 17 8 4 8-4" />
  </Base>
);

export const IconAlert = (p: IconProps) => (
  <Base {...p}>
    <path d="M12 4l9 16H3z" />
    <path d="M12 10v4" />
    <path d="M12 17.5h.01" />
  </Base>
);
