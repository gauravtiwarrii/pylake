import { useId } from "react";

type PyLakeIconProps = {
  size?: number;
  className?: string;
  label?: string;
};

type PyLakeWordmarkProps = {
  theme?: "dark" | "light";
  className?: string;
};

type PyLakeLogoProps = {
  theme?: "dark" | "light";
  size?: number;
  className?: string;
};

export function PyLakeIcon({ size = 32, className, label }: PyLakeIconProps) {
  const gradientId = `pylake-mark-${useId()}`;

  return (
    <svg
      aria-hidden={label ? undefined : true}
      aria-label={label}
      className={className}
      fill="none"
      height={size}
      role={label ? "img" : undefined}
      viewBox="0 0 64 64"
      width={size}
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id={gradientId} x1="7" x2="56" y1="8" y2="56" gradientUnits="userSpaceOnUse">
          <stop stopColor="#12C8ED" />
          <stop offset=".48" stopColor="#168BFF" />
          <stop offset="1" stopColor="#773BFF" />
        </linearGradient>
      </defs>
      <path
        d="M12 52V11h22a15 15 0 1 1 0 30H18"
        stroke={`url(#${gradientId})`}
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="8"
      />
      <path
        d="M9 46c7-8 14-9 22-5s15 3 24-4M9 55c7-7 14-8 22-4s15 2 24-4"
        stroke={`url(#${gradientId})`}
        strokeLinecap="round"
        strokeWidth="4"
      />
    </svg>
  );
}

export function PyLakeWordmark({ theme = "dark", className }: PyLakeWordmarkProps) {
  return (
    <span
      aria-hidden="true"
      className={`inline-flex items-baseline font-semibold tracking-[-0.06em] ${
        theme === "dark" ? "text-white" : "text-[#0B0B12]"
      } ${className ?? ""}`}
    >
      <span>Py</span>
      <span className="bg-gradient-to-r from-[#12C8ED] via-[#168BFF] to-[#773BFF] bg-clip-text text-transparent">
        Lake
      </span>
    </span>
  );
}

export function PyLakeLogo({ theme = "dark", size = 32, className }: PyLakeLogoProps) {
  return (
    <span
      aria-label="PyLake"
      className={`inline-flex items-center gap-2.5 ${className ?? ""}`}
      role="img"
    >
      <PyLakeIcon size={size} />
      <PyLakeWordmark theme={theme} className="text-[1.05rem]" />
    </span>
  );
}
