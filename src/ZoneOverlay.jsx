import { useEffect, useState } from "react";
import { containedContentRect, labelAnchor, toSvgPoints } from "./zoneGeometry";

// Draws normalized zone polygons over whatever box contains it. The parent
// must be exactly the displayed image content, so 0-100% maps to the frame.
// variant: "restricted" (enabled), "disabled", or "draft" (being drawn).
export function ZoneShapes({ zones, labelPrefix = "" }) {
  return (
    <>
      <svg className="zone-layer" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        {zones.map((zone) => (
          zone.points.length >= 3 ? (
            <polygon key={zone.key} className={`zone-shape zone-shape--${zone.variant}`} points={toSvgPoints(zone.points)} />
          ) : (
            <polyline key={zone.key} className={`zone-shape zone-shape--${zone.variant} zone-shape--open`} points={toSvgPoints(zone.points)} />
          )
        ))}
      </svg>
      {zones.filter((zone) => zone.name && zone.points.length >= 3).map((zone) => {
        const [x, y] = labelAnchor(zone.points);
        const classes = [
          "zone-label",
          `zone-label--${zone.variant}`,
          y < 0.08 ? "zone-label--below" : "",
          x > 0.6 ? "zone-label--end" : "",
        ].filter(Boolean).join(" ");
        return (
          <span key={`label-${zone.key}`} className={classes} style={{ left: `${x * 100}%`, top: `${y * 100}%` }}>
            {labelPrefix ? `${labelPrefix} · ${zone.name}` : zone.name}
          </span>
        );
      })}
    </>
  );
}

// Measures `boxRef` and returns the box-relative rect where content with
// `aspectRatio` is painted under `object-fit: contain`; null while inactive.
export function useContainedRect(boxRef, aspectRatio, active) {
  const [rect, setRect] = useState(null);

  useEffect(() => {
    const box = boxRef.current;
    if (!active || !box) {
      setRect(null);
      return undefined;
    }
    const measure = () => {
      const next = containedContentRect(box.clientWidth, box.clientHeight, aspectRatio);
      setRect((current) => (
        current && next
        && current.left === next.left && current.top === next.top
        && current.width === next.width && current.height === next.height
          ? current
          : next
      ));
    };
    measure();
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    observer?.observe(box);
    window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [boxRef, aspectRatio, active]);

  return rect;
}
