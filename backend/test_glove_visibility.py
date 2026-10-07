"""Gloves are judged only when the hands can be in view (no YOLO needed).

Run:
    python test_glove_visibility.py
"""

from ai_module.ppe_analyzer import PPEAnalyzer


def _det(name, box, conf=0.8):
    return {"class_id": 0, "class_name": name, "confidence": conf, "bbox": list(map(float, box))}


def run_tests() -> None:
    analyzer = PPEAnalyzer()
    head_and_shoulders = _det("Person", (60, 100, 560, 480))   # wider than tall: someone at a webcam
    full_body = _det("Person", (200, 40, 330, 460))             # taller than wide: hands in view

    # Webcam close-up without gloves: not a violation, gloves "not visible".
    status = analyzer.analyze([head_and_shoulders])[0]
    assert "gloves" not in status.missing_items, status.missing_items
    assert status.not_visible_items == ["gloves"]
    assert status.missing_items == ["helmet", "vest"]
    assert status.to_dict()["ppe"]["gloves"]["visible"] is False

    # Whole body in view and no gloves: violation as before.
    status = analyzer.analyze([full_body])[0]
    assert status.missing_items == ["helmet", "vest", "gloves"] and status.not_visible_items == []

    # Close-up, but the model sees bare hands: violation.
    bare = _det("no_gloves", (420, 380, 490, 470))
    status = analyzer.analyze([head_and_shoulders, bare])[0]
    assert "gloves" in status.missing_items

    # Close-up, gloves detected: worn.
    glove = _det("gloves", (420, 380, 490, 470))
    status = analyzer.analyze([head_and_shoulders, glove])[0]
    assert status.gloves.present and "gloves" not in status.missing_items and status.not_visible_items == []

    # Helmet and vest are still judged in a close-up.
    helmet = _det("helmet", (220, 40, 380, 130))
    vest = _det("vest", (150, 250, 450, 480))
    status = analyzer.analyze([head_and_shoulders, helmet, vest])[0]
    assert status.compliant and status.not_visible_items == ["gloves"]

    print("Glove visibility tests passed:")
    print("  - hands out of view (head-and-shoulders view): gloves not judged")
    print("  - full body, bare hands detected, or gloves detected: judged as before")


if __name__ == "__main__":
    run_tests()
