/**
 * Floating browser-window wrapper with 3D perspective and traffic-light dots.
 */
import React from "react";

export const BrowserFrame: React.FC<{
  children: React.ReactNode;
  rotateX?: number;
  rotateY?: number;
  scale?: number;
  opacity?: number;
  width?: string;
}> = ({ children, rotateX = 0, rotateY = 0, scale = 1, opacity = 1, width = "80%" }) => (
  <div
    style={{
      position: "absolute",
      inset: 0,
      display: "flex",
      justifyContent: "center",
      alignItems: "center",
      perspective: 2400,
    }}
  >
    <div
      style={{
        width,
        borderRadius: 24,
        overflow: "hidden",
        opacity,
        boxShadow:
          "0 80px 200px rgba(0,0,0,0.55), 0 0 0 1px rgba(255,255,255,0.08), 0 0 120px rgba(59,130,246,0.1)",
        transform: `rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale(${scale})`,
        transformStyle: "preserve-3d",
      }}
    >
      {/* chrome bar */}
      <div
        style={{
          height: 52,
          background: "linear-gradient(180deg, hsl(215 22% 16%) 0%, hsl(215 22% 12%) 100%)",
          display: "flex",
          alignItems: "center",
          padding: "0 24px",
          gap: 12,
          borderBottom: "1px solid rgba(255,255,255,0.06)",
        }}
      >
        <div style={{ width: 15, height: 15, borderRadius: "50%", background: "#ff5f57" }} />
        <div style={{ width: 15, height: 15, borderRadius: "50%", background: "#febc2e" }} />
        <div style={{ width: 15, height: 15, borderRadius: "50%", background: "#28c840" }} />
      </div>
      {children}
    </div>
  </div>
);
