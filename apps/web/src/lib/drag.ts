/* ------------------------------------------------------------------
   Pointer-driven card dragging with a flying clone, column highlight,
   auto-scroll and elastic drop feedback. Mouse, pen and touch friendly.
   Ported from the Solvik design system.
------------------------------------------------------------------- */

import type { PointerEvent as ReactPointerEvent } from "react";

const DRAGGABLE = "[data-drag-card]";
const DROP_ZONE = "[data-drop]";

export interface CardDragOptions {
  /** The column/card the item currently belongs to; dropping here is a no-op. */
  current?: string | null;
  onDrop?: (id: string, target: string, card: HTMLElement) => void;
}

export function startCardDrag(
  event: ReactPointerEvent<HTMLElement>,
  id: string,
  options: CardDragOptions = {},
) {
  if (event.button !== undefined && event.button !== 0 && event.pointerType === "mouse") return;

  const origin = event.target instanceof Element ? event.target : null;
  if (origin?.closest("button, a, input, select, textarea, [data-no-drag]")) return;

  const card = (event.currentTarget as HTMLElement | null)?.closest<HTMLElement>(DRAGGABLE);
  if (!card) return;

  const startX = event.clientX;
  const startY = event.clientY;
  const rect = card.getBoundingClientRect();
  const scrollElement = card.closest<HTMLElement>("[data-drag-scroll]");
  let ghost: HTMLElement | null = null;
  let started = false;
  let hovered: Element | null = null;
  let frame = 0;
  let last = { x: startX, y: startY };
  let sourceHidden = false;

  const makeGhost = () => {
    ghost = card.cloneNode(true) as HTMLElement;
    ghost.classList.add("drag-ghost");
    ghost.removeAttribute("data-drag-card");
    ghost.style.width = `${rect.width}px`;
    ghost.style.height = `${rect.height}px`;
    ghost.style.left = `${rect.left}px`;
    ghost.style.top = `${rect.top}px`;
    ghost.querySelectorAll("button, input, a").forEach((element) => {
      element.setAttribute("tabindex", "-1");
    });
    document.body.appendChild(ghost);
    card.classList.add("is-dragging");
    sourceHidden = true;
    document.body.classList.add("is-dragging-card");
  };

  const highlight = (x: number, y: number) => {
    const element = document.elementFromPoint(x, y)?.closest(DROP_ZONE) ?? null;
    if (hovered === element) return;
    hovered?.classList.remove("is-drop-target");
    hovered = element;
    hovered?.classList.add("is-drop-target");
  };

  const autoScroll = (x: number, y: number) => {
    if (scrollElement) {
      const box = scrollElement.getBoundingClientRect();
      if (x < box.left + 56) scrollElement.scrollLeft -= 14;
      else if (x > box.right - 56) scrollElement.scrollLeft += 14;
    }
    const scrolling = document.scrollingElement;
    if (!scrolling) return;
    if (y < 90) scrolling.scrollTop -= 10;
    else if (y > window.innerHeight - 90) scrolling.scrollTop += 10;
  };

  const move = (moveEvent: PointerEvent) => {
    last = { x: moveEvent.clientX, y: moveEvent.clientY };
    if (!started) {
      if (Math.hypot(moveEvent.clientX - startX, moveEvent.clientY - startY) < 5) return;
      started = true;
      makeGhost();
      try {
        card.setPointerCapture?.(event.pointerId);
      } catch {
        // Pointer capture is an enhancement; some browsers reject synthetic ids.
      }
    }
    highlight(moveEvent.clientX, moveEvent.clientY);
    autoScroll(moveEvent.clientX, moveEvent.clientY);
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      if (!ghost) return;
      ghost.style.transform = `translate3d(${last.x - startX}px, ${
        last.y - startY
      }px, 0) rotate(1.4deg) scale(1.025)`;
    });
  };

  const cleanup = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    window.removeEventListener("pointercancel", cancel);
    document.body.classList.remove("is-dragging-card");
  };

  const finishGhost = (target: Element | null) => {
    if (!ghost) return;
    const node = ghost;
    ghost = null;
    const remove = () => node.remove();

    try {
      if (target) {
        const box = target.getBoundingClientRect();
        const current = node.getBoundingClientRect();
        const dx = box.left + box.width / 2 - (current.left + current.width / 2);
        const dy = box.top + 26 - (current.top + current.height / 2);
        node
          .animate(
            [
              { transform: node.style.transform, opacity: 1 },
              { transform: `translate3d(${dx}px, ${dy}px, 0) scale(0.55)`, opacity: 0 },
            ],
            { duration: 240, easing: "cubic-bezier(.4,0,.2,1)" },
          )
          .finished.catch(() => {})
          .finally(remove);
      } else {
        node
          .animate(
            [
              { transform: node.style.transform, opacity: 1 },
              { transform: "translate3d(0, 0, 0) scale(0.97)", opacity: 0 },
            ],
            { duration: 180, easing: "ease-out" },
          )
          .finished.catch(() => {})
          .finally(remove);
      }
    } catch {
      remove();
    }

    window.setTimeout(remove, 420);
    card.classList.remove("is-dragging");

    if (sourceHidden) {
      try {
        card.animate([{ opacity: 0.4 }, { opacity: 1 }], { duration: 260, easing: "ease-out" });
      } catch {
        // Web Animations is optional.
      }
    }
  };

  const up = (upEvent: PointerEvent) => {
    cleanup();
    if (frame) cancelAnimationFrame(frame);
    if (!started) return;

    const target = document.elementFromPoint(upEvent.clientX, upEvent.clientY)?.closest(DROP_ZONE) ?? null;
    hovered?.classList.remove("is-drop-target");
    const key = target instanceof HTMLElement ? target.dataset.drop : undefined;

    if (target && key && key !== options.current) {
      target.classList.add("is-hit");
      window.setTimeout(() => target.classList.remove("is-hit"), 620);
      options.onDrop?.(id, key, card);
    }

    finishGhost(target);

    const blockClick = (clickEvent: MouseEvent) => {
      clickEvent.stopPropagation();
      clickEvent.preventDefault();
    };
    document.addEventListener("click", blockClick, { capture: true, once: true });
    window.setTimeout(() => document.removeEventListener("click", blockClick, true), 60);
  };

  const cancel = () => {
    cleanup();
    finishGhost(null);
  };

  if (window.PointerEvent) {
    window.addEventListener("pointermove", move, { passive: true });
    window.addEventListener("pointerup", up, { once: true });
    window.addEventListener("pointercancel", cancel, { once: true });
  }
}
