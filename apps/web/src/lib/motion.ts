"use client";

import { useEffect, useRef, useState } from "react";

/** True when the operating system asks for reduced motion. */
export function prefersReducedMotion() {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

const easeOutCubic = (progress: number) => 1 - Math.pow(1 - progress, 3);

/**
 * Animate a numeric value from its previous display to a new target.
 *
 * Mounts at zero and springs to the value, which matches the Solvik dashboard
 * counters. Hidden documents and reduced-motion sessions jump straight to the
 * target so a background tab never burns frames and assistive technology never
 * hears intermediate numbers.
 */
export function useCountUp(value: number, duration = 900) {
  const target = Number.isFinite(value) ? Number(value) : 0;
  const currentRef = useRef(prefersReducedMotion() ? target : 0);
  const [display, setDisplay] = useState(currentRef.current);

  useEffect(() => {
    const hidden = typeof document !== "undefined" && document.visibilityState === "hidden";
    if (prefersReducedMotion() || hidden) {
      currentRef.current = target;
      setDisplay(target);
      return;
    }

    const from = currentRef.current;
    const started = performance.now();
    let frame = 0;

    const tick = (now: number) => {
      const progress = Math.min(1, (now - started) / duration);
      const next = from + (target - from) * easeOutCubic(progress);
      currentRef.current = next;
      setDisplay(next);
      if (progress < 1) frame = requestAnimationFrame(tick);
      else currentRef.current = target;
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, duration]);

  return display;
}

/** Local storage-backed state with a safe fallback when storage is blocked. */
export function usePersistentState<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = window.localStorage.getItem(key);
      return raw == null ? initial : (JSON.parse(raw) as T);
    } catch {
      return initial;
    }
  });

  useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // Private browsing or a full quota must not break the page.
    }
  }, [key, value]);

  return [value, setValue] as const;
}

/** Reveal-on-scroll observer. Returns a ref plus whether the element is seen. */
export function useInView<T extends HTMLElement>({
  threshold = 0.15,
  once = true,
}: { threshold?: number; once?: boolean } = {}) {
  const ref = useRef<T | null>(null);
  const [seen, setSeen] = useState(false);

  useEffect(() => {
    const element = ref.current;
    if (!element || typeof IntersectionObserver === "undefined") {
      setSeen(true);
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setSeen(true);
            if (once) observer.disconnect();
          } else if (!once) {
            setSeen(false);
          }
        });
      },
      { threshold, rootMargin: "0px 0px -8% 0px" },
    );

    observer.observe(element);
    return () => observer.disconnect();
  }, [threshold, once]);

  return [ref, seen] as const;
}

/** Move an identifier from one list position to another. */
export function reorder<T>(list: T[], fromId: T, toId: T): T[] {
  if (fromId === toId) return list;
  const from = list.indexOf(fromId);
  const to = list.indexOf(toId);
  if (from < 0 || to < 0) return list;
  const next = [...list];
  next.splice(from, 1);
  next.splice(to, 0, fromId);
  return next;
}

/** Swap an identifier with its neighbour; returns the original list at edges. */
export function moveInList<T>(list: T[], id: T, direction: number): T[] {
  const index = list.indexOf(id);
  const nextIndex = index + direction;
  if (index < 0 || nextIndex < 0 || nextIndex >= list.length) return list;
  const copy = [...list];
  [copy[index], copy[nextIndex]] = [copy[nextIndex], copy[index]];
  return copy;
}
