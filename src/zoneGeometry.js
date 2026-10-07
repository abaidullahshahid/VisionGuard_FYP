// Restricted-zone points are stored normalized: [x, y] as fractions (0-1) of
// the camera frame's width and height, never as on-screen pixels.

export const MIN_ZONE_POINTS = 3;

const clamp01 = (value) => Math.min(1, Math.max(0, value));
const round4 = (value) => Math.round(value * 10000) / 10000;

// normalized_x = (clientX - left) / displayed_width, likewise for y.
// `rect` is the on-screen box of the displayed image content.
export function toNormalizedPoint(clientX, clientY, rect) {
  if (!rect || !(rect.width > 0) || !(rect.height > 0)) return null;
  return [
    round4(clamp01((clientX - rect.left) / rect.width)),
    round4(clamp01((clientY - rect.top) / rect.height)),
  ];
}

// Where an `object-fit: contain` image actually paints inside its box, so an
// overlay can skip any letterbox/pillarbox bars. Offsets are box-relative.
export function containedContentRect(boxWidth, boxHeight, contentAspect) {
  if (!(boxWidth > 0) || !(boxHeight > 0) || !(contentAspect > 0)) return null;
  const width = Math.min(boxWidth, boxHeight * contentAspect);
  const height = width / contentAspect;
  return {
    left: (boxWidth - width) / 2,
    top: (boxHeight - height) / 2,
    width,
    height,
  };
}

// SVG "points" attribute for a 0-100 viewBox.
export function toSvgPoints(points) {
  const percent = (value) => Math.round(value * 100000) / 1000;
  return points.map(([x, y]) => `${percent(x)},${percent(y)}`).join(" ");
}

// Label anchor: the top-most vertex (left-most on ties).
export function labelAnchor(points) {
  return points.reduce((best, point) => (
    point[1] < best[1] || (point[1] === best[1] && point[0] < best[0]) ? point : best
  ), points[0]);
}
