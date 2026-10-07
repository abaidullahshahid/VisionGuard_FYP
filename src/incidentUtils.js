export const INCIDENT_TYPES = {
  PPE_VIOLATION: "PPE Violation",
  RESTRICTED_ZONE_VIOLATION: "Restricted Zone Violation",
};

export const STATUS_LABELS = {
  open: "Open",
  in_progress: "In Progress",
  resolved: "Resolved",
};

export function incidentTypeLabel(value = "") {
  return INCIDENT_TYPES[value] || value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function statusLabel(value = "") {
  return STATUS_LABELS[value] || value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function severityValue(incidentOrValue) {
  const value = typeof incidentOrValue === "object"
    ? incidentOrValue?.severity || incidentOrValue?.severity_level
    : incidentOrValue;
  return String(value || "").toUpperCase();
}

export function severityLabel(incidentOrValue) {
  const value = severityValue(incidentOrValue);
  return value ? value.charAt(0) + value.slice(1).toLowerCase() : "Unknown";
}

export function severityBadge(value) {
  return { CRITICAL: "red", HIGH: "red", MEDIUM: "yellow", LOW: "green" }[severityValue(value)] || "gray";
}

export function statusBadge(value) {
  return { open: "red", in_progress: "blue", resolved: "green" }[value] || "gray";
}

export function formatDateTime(value) {
  if (!value) return "Not available";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Not available" : date.toLocaleString();
}

export function cameraLabel(incident, cameras = []) {
  const camera = cameras.find((item) => String(item.id) === String(incident?.camera_id));
  if (camera?.name) return camera.name;
  if (incident?.camera_identifier) return incident.camera_identifier;
  if (incident?.camera_id != null) return `Camera #${incident.camera_id}`;
  return "Not assigned";
}
