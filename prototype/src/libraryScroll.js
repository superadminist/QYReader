export function bindLibraryScroll(page) {
  let timer;
  let scrolling = false;
  let pointer = null;
  let hoveredCard = null;

  const setHoveredCard = (card) => {
    if (hoveredCard === card) return;
    hoveredCard?.removeAttribute("data-hovered");
    hoveredCard = card;
    hoveredCard?.setAttribute("data-hovered", "true");
  };
  const trackPointer = (event) => {
    if (event.pointerType !== "touch") {
      pointer = { x: event.clientX, y: event.clientY };
    }
  };
  const onPointerOver = (event) => {
    if (event.pointerType === "touch") return;
    trackPointer(event);
    if (!scrolling) setHoveredCard(event.target.closest(".book-card"));
  };
  const onPointerLeave = () => {
    pointer = null;
    setHoveredCard(null);
  };
  const settle = () => {
    scrolling = false;
    delete page.dataset.scrolling;
    const target = pointer && page.ownerDocument.elementFromPoint(pointer.x, pointer.y);
    setHoveredCard(target && page.contains(target) ? target.closest(".book-card") : null);
  };
  const markScrolling = (event) => {
    if (event.type === "wheel") {
      if (event.ctrlKey || !event.deltaY) return;
      trackPointer(event);
    }
    if (!scrolling) {
      scrolling = true;
      page.dataset.scrolling = "true";
      // Change just the hovered card. Cards moving under a stationary cursor
      // during wheel or scrollbar scrolling should not start new transitions.
      setHoveredCard(null);
    }
    clearTimeout(timer);
    timer = setTimeout(settle, 180);
  };

  setHoveredCard(page.querySelector(".book-card:hover"));
  page.addEventListener("pointerover", onPointerOver);
  page.addEventListener("pointermove", trackPointer, { passive: true });
  page.addEventListener("pointerleave", onPointerLeave);
  page.addEventListener("wheel", markScrolling, { passive: true });
  page.addEventListener("scroll", markScrolling, { passive: true });
  return () => {
    clearTimeout(timer);
    delete page.dataset.scrolling;
    setHoveredCard(null);
    page.removeEventListener("pointerover", onPointerOver);
    page.removeEventListener("pointermove", trackPointer);
    page.removeEventListener("pointerleave", onPointerLeave);
    page.removeEventListener("wheel", markScrolling);
    page.removeEventListener("scroll", markScrolling);
  };
}
