/**
 * Injects CSS styles for coverage gutter dots and impact view zones.
 * Called once from DiffViewer to set up the necessary Monaco CSS.
 */

import { useEffect } from "react";

export function useLayeredDiffStyles() {
  useEffect(() => {
    const id = "layered-diff-styles";
    if (document.getElementById(id)) return;
    const style = document.createElement("style");
    style.id = id;
    style.textContent = `
/* Coverage gutter dots */
.cov-dot-covered, .cov-dot-uncovered {
  cursor: pointer !important;
}
.cov-dot-covered {
  background: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ccircle cx='8' cy='8' r='4' fill='%234ec9b0'/%3E%3C/svg%3E") center center / 10px no-repeat;
}
.cov-dot-uncovered {
  background: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ccircle cx='8' cy='8' r='4' fill='%23f14c4c'/%3E%3C/svg%3E") center center / 10px no-repeat;
}

/* Motivation view zone */
.motivation-zone {
  padding: 4px 12px 2px 8px;
  background: rgba(156, 220, 254, 0.03);
  border-top: 1px solid #2a2a3a;
  border-bottom: 1px solid #2a2a3a;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 13px;
  line-height: 1.45;
  overflow: hidden;
  pointer-events: auto;
}
.motivation-zone .mot-label {
  display: none;
}
.motivation-zone .mot-text {
  color: #9cdcfe;
  font-style: italic;
  line-height: 1.45;
}

/* Impact zone — collapsible panel matching mockup */
.impact-zone-container {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 12px;
  line-height: 1.4;
  border-top: 1px solid #2a2a4a;
  border-bottom: 1px solid #2a2a4a;
  background: #1b1b28;
  pointer-events: auto;
  overflow: visible;
}
.impact-zone-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px 5px 8px;
  cursor: pointer;
  user-select: none;
  transition: background 0.1s;
}
.impact-zone-header:hover {
  background: rgba(86, 156, 214, 0.06);
}
.impact-chevron {
  font-size: 9px;
  color: #569cd6;
  width: 10px;
  text-align: center;
  transition: transform 0.15s;
}
.impact-badge {
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  padding: 1px 5px;
  border: 1px solid #3a4a6a;
  border-radius: 3px;
  color: #569cd6;
}
.impact-badge-breaking {
  border-color: rgba(241, 76, 76, 0.4);
  color: #f48771;
}
.impact-summary {
  flex: 1;
  color: #a0a0a0;
  font-size: 11px;
}
.impact-test-pill {
  font-size: 9px;
  padding: 1px 5px;
  border-radius: 3px;
  background: rgba(78, 201, 176, 0.12);
  color: #4ec9b0;
  font-weight: 600;
}
.impact-fail-pill {
  font-size: 9px;
  padding: 1px 5px;
  border-radius: 3px;
  background: #3d1515;
  color: #f48771;
  font-weight: 600;
}
.impact-zone-body {
  padding: 0;
}
.impact-caller-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px 5px 28px;
  cursor: pointer;
  transition: background 0.1s;
  border-top: 1px solid #252535;
}
.impact-caller-card:first-child {
  border-top: none;
}
.impact-caller-card:hover {
  background: rgba(255, 255, 255, 0.02);
}
.impact-caller-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.impact-caller-dot.test { background: #4ec9b0; }
.impact-caller-dot.source { background: #569cd6; }
.impact-caller-dot.covered { background: #4ec9b0; }
.impact-caller-dot.uncovered { background: #f14c4c; }
.impact-caller-dot.fail { background: #f14c4c; box-shadow: 0 0 3px #f48771; }
.impact-caller-name {
  font-family: 'Cascadia Code', 'Fira Code', Consolas, monospace;
  font-size: 12px;
  color: #dcdcaa;
}
.impact-caller-loc {
  font-size: 10px;
  color: #6a6a6a;
  margin-left: auto;
}
.impact-more {
  padding: 4px 12px 4px 88px;
  font-size: 10px;
  color: #6a6a6a;
  font-style: italic;
}
`;
    document.head.appendChild(style);
    return () => { style.remove(); };
  }, []);
}
