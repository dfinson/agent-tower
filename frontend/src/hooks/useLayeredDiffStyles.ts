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

/* Impact view zones */
.impact-zone-container {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 12px;
  line-height: 1.4;
  padding: 0 12px;
}
.impact-zone-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  cursor: pointer;
  border: 1px solid rgba(100, 100, 140, 0.2);
  border-radius: 4px;
  background: rgba(100, 100, 140, 0.05);
  user-select: none;
  transition: background 0.1s;
}
.impact-zone-header:hover {
  background: rgba(100, 100, 140, 0.1);
}
.impact-chevron {
  font-size: 10px;
  color: #888;
  width: 12px;
  text-align: center;
}
.impact-badge {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.5px;
  padding: 1px 5px;
  border: 1px solid rgba(100, 100, 140, 0.3);
  border-radius: 3px;
  color: #aaa;
}
.impact-summary {
  flex: 1;
  color: #ccc;
  font-size: 11px;
}
.impact-fail-pill {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 8px;
  background: rgba(241, 76, 76, 0.15);
  color: #f48771;
  font-weight: 500;
}
.impact-zone-body {
  margin-top: 4px;
  padding-left: 20px;
}
.impact-caller-card {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  border-radius: 3px;
  cursor: pointer;
  transition: background 0.1s;
}
.impact-caller-card:hover {
  background: rgba(255, 255, 255, 0.04);
}
.impact-caller-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.impact-caller-dot.test { background: #4ec9b0; }
.impact-caller-dot.source { background: #569cd6; }
.impact-caller-name {
  font-family: 'Cascadia Code', 'Fira Code', monospace;
  font-size: 11px;
  color: #dcdcaa;
}
.impact-caller-loc {
  font-size: 10px;
  color: #666;
  margin-left: auto;
}
.impact-more {
  padding: 2px 8px;
  font-size: 10px;
  color: #666;
  font-style: italic;
}

/* Motivation view zone styling */
.motivation-zone {
  padding: 4px 12px;
  border-left: 2px solid rgba(200, 150, 50, 0.5);
  background: rgba(200, 150, 50, 0.05);
  font-size: 12px;
  line-height: 1.4;
  overflow: hidden;
}
.motivation-zone .motivation-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.3px;
  color: rgba(200, 150, 50, 0.8);
  margin-right: 8px;
}
.motivation-zone .motivation-text {
  color: var(--vscode-descriptionForeground, #999);
}
`;
    document.head.appendChild(style);
    return () => { style.remove(); };
  }, []);
}
