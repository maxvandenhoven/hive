import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// Radix UI relies on browser APIs that jsdom does not implement.
Element.prototype.hasPointerCapture = () => false;
Element.prototype.setPointerCapture = () => undefined;
Element.prototype.releasePointerCapture = () => undefined;
Element.prototype.scrollIntoView = () => undefined;
globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
// jsdom does not lay out SVGs, so the board finds no screen positions.
SVGSVGElement.prototype.getScreenCTM = () => null;
// Sonner follows the colour scheme of the system.
window.matchMedia = (query: string): MediaQueryList => {
  const list = new EventTarget() as MediaQueryList;

  return Object.assign(list, { matches: false, media: query, onchange: null });
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
