import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

const nativeGetComputedStyle = window.getComputedStyle.bind(window);

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
  vi.stubGlobal("matchMedia", (query: string): MediaQueryList => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }));
  vi.stubGlobal("getComputedStyle", (element: Element) => {
    try {
      return nativeGetComputedStyle(element);
    } catch {
      // jsdom cannot compute some Ant Design-injected CSS layers.
      return (element as HTMLElement | SVGElement).style ?? document.documentElement.style;
    }
  });
  Object.defineProperties(Element.prototype, {
    hasPointerCapture: { configurable: true, value: () => false },
    releasePointerCapture: { configurable: true, value: () => undefined },
    setPointerCapture: { configurable: true, value: () => undefined },
    scrollIntoView: { configurable: true, value: () => undefined },
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
