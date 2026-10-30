"use client";
import { useI18n } from "@/lib/i18n/provider";
// Original projected torus mesh. No downloaded images, WebGL or frame-by-frame JS.
function point(u: number, v: number) {
  const r = 205 + 66 * Math.cos(v);
  const x = r * Math.cos(u),
    y = r * Math.sin(u),
    z = 66 * Math.sin(v);
  const a = 0.91,
    b = -0.38;
  const yy = y * Math.cos(a) - z * Math.sin(a),
    zz = y * Math.sin(a) + z * Math.cos(a);
  const xx = x * Math.cos(b) + zz * Math.sin(b),
    depth = -x * Math.sin(b) + zz * Math.cos(b);
  const perspective = 1000 / (1000 - depth);
  return { x: 360 + xx * perspective, y: 360 + yy * perspective, z: depth };
}
export function RoutingLens() {
  const { t } = useI18n();
  const faces = [];
  for (let i = 0; i < 72; i++)
    for (let j = 0; j < 20; j++) {
      const u = (i * Math.PI * 2) / 72,
        v = (j * Math.PI * 2) / 20;
      const vertices = [
        point(u, v),
        point(u + (Math.PI * 2) / 72, v),
        point(u + (Math.PI * 2) / 72, v + (Math.PI * 2) / 20),
        point(u, v + (Math.PI * 2) / 20),
      ];
      const light = Math.max(
        0,
        0.54 * Math.sin(u) + 0.68 * Math.sin(v) + 0.3 * Math.cos(u - v),
      );
      const hue = 205 + 45 * Math.sin(u + v * 0.6);
      const saturation = 9 + 64 * Math.pow(Math.max(0, Math.cos(u + 0.8)), 6);
      faces.push({
        key: `${i}-${j}`,
        z: vertices.reduce((sum, p) => sum + p.z, 0) / 4,
        points: vertices
          .map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`)
          .join(" "),
        fill: `hsl(${hue.toFixed(1)} ${saturation.toFixed(1)}% ${(8 + 76 * light).toFixed(1)}%)`,
      });
    }
  return (
    <div className="routing-lens" aria-hidden="true">
      <div className="lens-aura" />
      <svg className="lens-art" viewBox="0 0 720 720" fill="none">
        <defs>
          <radialGradient id="lens-halo">
            <stop stopColor="#5089ff" stopOpacity=".18" />
            <stop offset="1" stopColor="#5089ff" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="orbit-line">
            <stop stopColor="#17263e" stopOpacity="0" />
            <stop offset=".5" stopColor="#789bcc" stopOpacity=".65" />
            <stop offset="1" stopColor="#17263e" stopOpacity="0" />
          </linearGradient>
        </defs>
        <circle cx="360" cy="360" r="340" fill="url(#lens-halo)" />
        <ellipse
          cx="360"
          cy="360"
          rx="332"
          ry="230"
          stroke="url(#orbit-line)"
          strokeWidth=".6"
          transform="rotate(-28 360 360)"
        />
        <ellipse
          cx="360"
          cy="360"
          rx="300"
          ry="310"
          stroke="#344763"
          strokeOpacity=".22"
          strokeDasharray="2 9"
        />
        {faces
          .sort((a, b) => a.z - b.z)
          .map((face) => (
            <polygon
              key={face.key}
              points={face.points}
              fill={face.fill}
              stroke={face.fill}
              strokeWidth=".5"
            />
          ))}
        <path
          d="M70 472C196 520 523 514 663 269"
          stroke="url(#orbit-line)"
          strokeWidth="1"
        />
        <circle cx="640" cy="301" r="3" fill="#77a9ff" />
        <circle cx="91" cy="473" r="2" fill="#a0badf" />
      </svg>
      <span className="lens-note lens-note-one">
        <i />
        {t("Constraints in focus")}
      </span>
      <span className="lens-note lens-note-two">
        {t("A clearer path forward")}
      </span>
    </div>
  );
}
