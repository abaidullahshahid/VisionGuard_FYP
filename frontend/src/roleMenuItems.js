import { Icon } from "./Icons";

export const officerMenuItems = [
  { label: "Dashboard",          icon: <Icon name="dashboard" />, path: "/officer" },
  { label: "Incidents",          icon: <Icon name="alert" />,     path: "/officer/incidents" },
  { label: "Corrective Actions", icon: <Icon name="clipboard" />, path: "/officer/actions" },
  { label: "Live Feed",          icon: <Icon name="camera" />,    path: "/officer/live" },
  { label: "Instructions",       icon: <Icon name="book" />,      path: "/officer/instructions" },
  { label: "Compliance Records", icon: <Icon name="chart" />,     path: "/officer/compliance" },
];

export const workerMenuItems = [
  { label: "Dashboard",           icon: <Icon name="dashboard" />, path: "/worker" },
  { label: "Locations",           icon: <Icon name="location" />,  path: "/worker/locations" },
  { label: "Safety Instructions", icon: <Icon name="book" />,      path: "/worker/instructions" },
  { label: "My Tasks",            icon: <Icon name="clipboard" />, path: "/worker/tasks" },
];
