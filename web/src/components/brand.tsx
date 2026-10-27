import Link from "next/link";

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link className="brand" href="/" aria-label="Logistics Insight AI home">
      <svg
        width="31"
        height="34"
        viewBox="0 0 31 34"
        fill="none"
        aria-hidden="true"
      >
        <path
          d="M3 9.5 15.5 2 28 9.5 15.5 17 3 9.5Z"
          stroke="currentColor"
          strokeWidth="1.6"
        />
        <path
          d="m3 17 12.5 7.5L28 17M3 24.5 15.5 32 28 24.5"
          stroke="currentColor"
          strokeWidth="1.6"
        />
        <path
          d="m15.5 17 12.5-7.5V17l-12.5 7.5V17Z"
          fill="#5089ff"
          fillOpacity=".7"
        />
      </svg>
      <span>
        Logistics Insight{!compact && <small>Decision intelligence</small>}
      </span>
      <span className="brand-ai">AI</span>
    </Link>
  );
}
