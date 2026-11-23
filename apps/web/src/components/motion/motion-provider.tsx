"use client";

import { useEffect } from "react";

/**
 * Global motion runtime.
 *
 * One delegated pointer listener drives every ambient effect instead of a
 * handler per card: parallax sets `--px/--py` on the root, spotlight sets
 * `--mx/--my` on the hovered surface, magnetism sets `--mag-x/--mag-y` on the
 * nearest control, and a ripple is injected on primary buttons. Work is
 * coalesced into a single animation frame and the whole layer respects
 * `prefers-reduced-motion`.
 */
export function MotionProvider() {
  useEffect(() => {
    const root = document.documentElement;
    root.classList.add("motion-ready");

    const reduceQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    const revealAll = () => {
      document.querySelectorAll<HTMLElement>("[data-reveal]").forEach((element) => {
        element.classList.add("is-revealed");
      });
    };

    if (reduceQuery.matches) {
      root.classList.add("motion-reduced");
      revealAll();
      return () => {
        root.classList.remove("motion-ready", "motion-reduced");
      };
    }

    let frame = 0;
    let pointerX = 0;
    let pointerY = 0;
    let magnetic: HTMLElement | null = null;

    const applyParallax = () => {
      frame = 0;
      const width = window.innerWidth || 1;
      const height = window.innerHeight || 1;
      root.style.setProperty("--px", `${(pointerX / width - 0.5) * -12}px`);
      root.style.setProperty("--py", `${(pointerY / height - 0.5) * -10}px`);
    };

    const onPointerMove = (event: PointerEvent) => {
      pointerX = event.clientX;
      pointerY = event.clientY;
      if (!frame) frame = requestAnimationFrame(applyParallax);

      const origin = event.target instanceof Element ? event.target : null;
      if (!origin) return;

      const surface = origin.closest<HTMLElement>("[data-spotlight]");
      if (surface) {
        const rect = surface.getBoundingClientRect();
        surface.style.setProperty("--mx", `${event.clientX - rect.left}px`);
        surface.style.setProperty("--my", `${event.clientY - rect.top}px`);
      }

      const nextMagnetic = origin.closest<HTMLElement>("[data-magnetic]");
      if (nextMagnetic !== magnetic) {
        if (magnetic) {
          magnetic.style.setProperty("--mag-x", "0px");
          magnetic.style.setProperty("--mag-y", "0px");
        }
        magnetic = nextMagnetic;
      }

      if (magnetic) {
        const rect = magnetic.getBoundingClientRect();
        const dx = (event.clientX - (rect.left + rect.width / 2)) / (rect.width / 2 || 1);
        const dy = (event.clientY - (rect.top + rect.height / 2)) / (rect.height / 2 || 1);
        magnetic.style.setProperty("--mag-x", `${Math.max(-1, Math.min(1, dx)) * 5}px`);
        magnetic.style.setProperty("--mag-y", `${Math.max(-1, Math.min(1, dy)) * 4}px`);
      }
    };

    const onPointerDown = (event: PointerEvent) => {
      const origin = event.target instanceof Element ? event.target : null;
      const host = origin?.closest<HTMLElement>(".motion-ripple-host");
      if (!host) return;
      if (host.getAttribute("aria-disabled") === "true") return;
      if (host instanceof HTMLButtonElement && host.disabled) return;

      const rect = host.getBoundingClientRect();
      const ripple = document.createElement("span");
      ripple.className = "motion-ripple";
      ripple.style.left = `${event.clientX - rect.left}px`;
      ripple.style.top = `${event.clientY - rect.top}px`;
      ripple.setAttribute("aria-hidden", "true");
      host.appendChild(ripple);
      window.setTimeout(() => ripple.remove(), 700);
    };

    // Reveal elements as they enter the viewport. A debounced rescan picks up
    // sections that mount after their API request resolves.
    const revealObserver =
      typeof IntersectionObserver === "undefined"
        ? null
        : new IntersectionObserver(
            (entries) => {
              entries.forEach((entry) => {
                if (entry.isIntersecting) {
                  entry.target.classList.add("is-revealed");
                  revealObserver?.unobserve(entry.target);
                }
              });
            },
            { threshold: 0.12, rootMargin: "0px 0px -6% 0px" },
          );

    const scan = () => {
      document.querySelectorAll<HTMLElement>("[data-reveal]:not(.is-revealed)").forEach((element) => {
        if (revealObserver) revealObserver.observe(element);
        else element.classList.add("is-revealed");
      });
    };

    let scanFrame = 0;
    const scheduleScan = () => {
      if (scanFrame) return;
      scanFrame = requestAnimationFrame(() => {
        scanFrame = 0;
        scan();
      });
    };

    scan();
    const mutations =
      typeof MutationObserver === "undefined"
        ? null
        : new MutationObserver((records) => {
            if (records.some((record) => record.addedNodes.length > 0)) scheduleScan();
          });
    mutations?.observe(document.body, { childList: true, subtree: true });

    window.addEventListener("pointermove", onPointerMove, { passive: true });
    window.addEventListener("pointerdown", onPointerDown, { passive: true });

    const onReducedMotionChange = (event: MediaQueryListEvent) => {
      root.classList.toggle("motion-reduced", event.matches);
      if (event.matches) revealAll();
    };
    reduceQuery.addEventListener?.("change", onReducedMotionChange);

    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerdown", onPointerDown);
      reduceQuery.removeEventListener?.("change", onReducedMotionChange);
      mutations?.disconnect();
      revealObserver?.disconnect();
      if (frame) cancelAnimationFrame(frame);
      if (scanFrame) cancelAnimationFrame(scanFrame);
      root.classList.remove("motion-ready", "motion-reduced");
      root.style.removeProperty("--px");
      root.style.removeProperty("--py");
    };
  }, []);

  return null;
}
