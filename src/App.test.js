import {
  incidentTypeLabel,
  severityBadge,
  severityValue,
  statusLabel,
} from "./incidentUtils";

describe("incident presentation helpers", () => {
  test("uses friendly labels without changing backend values", () => {
    expect(incidentTypeLabel("PPE_VIOLATION")).toBe("PPE Violation");
    expect(incidentTypeLabel("RESTRICTED_ZONE_VIOLATION")).toBe(
      "Restricted Zone Violation"
    );
    expect(statusLabel("in_progress")).toBe("In Progress");
  });

  test("supports both current and legacy severity response fields", () => {
    expect(severityValue({ severity: "HIGH" })).toBe("HIGH");
    expect(severityValue({ severity_level: "medium" })).toBe("MEDIUM");
    expect(severityBadge("LOW")).toBe("green");
  });
});
