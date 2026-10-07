import { containedContentRect, labelAnchor, toNormalizedPoint, toSvgPoints } from "./zoneGeometry";

describe("restricted-zone geometry", () => {
  test("converts a click on the displayed image to normalized coordinates", () => {
    const rect = { left: 100, top: 50, width: 400, height: 300 };
    expect(toNormalizedPoint(300, 200, rect)).toEqual([0.5, 0.5]);
    expect(toNormalizedPoint(100, 50, rect)).toEqual([0, 0]);
    expect(toNormalizedPoint(500, 350, rect)).toEqual([1, 1]);
    expect(toNormalizedPoint(320, 140, rect)).toEqual([0.55, 0.3]);
  });

  test("is independent of the displayed size", () => {
    const small = toNormalizedPoint(64, 36, { left: 0, top: 0, width: 640, height: 360 });
    const large = toNormalizedPoint(192, 108, { left: 0, top: 0, width: 1920, height: 1080 });
    expect(small).toEqual(large);
  });

  test("clamps clicks on the edge into the 0-1 range and rejects empty boxes", () => {
    const rect = { left: 0, top: 0, width: 200, height: 100 };
    expect(toNormalizedPoint(-5, 120, rect)).toEqual([0, 1]);
    expect(toNormalizedPoint(10, 10, { left: 0, top: 0, width: 0, height: 100 })).toBeNull();
  });

  test("finds the painted area of object-fit: contain video", () => {
    // 4:3 webcam inside a 16:9 box: pillarbox bars left/right.
    expect(containedContentRect(1600, 900, 4 / 3)).toEqual({ left: 200, top: 0, width: 1200, height: 900 });
    // 16:9 video inside a 4:3 box: letterbox bars top/bottom.
    expect(containedContentRect(1200, 900, 16 / 9)).toEqual({ left: 0, top: 112.5, width: 1200, height: 675 });
    // Matching aspect ratio: the content fills the box.
    expect(containedContentRect(1280, 720, 16 / 9)).toEqual({ left: 0, top: 0, width: 1280, height: 720 });
    expect(containedContentRect(0, 720, 16 / 9)).toBeNull();
  });

  test("builds SVG points and label anchors from normalized polygons", () => {
    const square = [[0.55, 0.3], [0.9, 0.3], [0.9, 0.9], [0.55, 0.9]];
    expect(toSvgPoints(square)).toBe("55,30 90,30 90,90 55,90");
    expect(labelAnchor(square)).toEqual([0.55, 0.3]);
  });
});
