/// <reference types="node" />
import "@testing-library/jest-dom/vitest";

import { File as NodeFile } from "node:buffer";

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
// The fetch of Node only sends its own form data and files, which jsdom replaces; its
// form data class is reached through a response it parses.
const nodeForm = await new Response(new URLSearchParams()).formData();
globalThis.FormData = nodeForm.constructor as typeof FormData;
globalThis.File = NodeFile as unknown as typeof File;
// jsdom keeps no object URLs, so photo previews get a fixed one.
URL.createObjectURL = () => "blob:photo";
URL.revokeObjectURL = () => undefined;
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
  // Remembered choices and panels must not leak into the next test.
  window.localStorage.clear();
});
