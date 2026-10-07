import { Icon } from "./Icons";

const adminMenuItems = [
  { label: "Dashboard",    icon: <Icon name="dashboard" />, path: "/admin" },
  { label: "Manage Users", icon: <Icon name="users" />,     path: "/admin/users" },
  { label: "Locations",    icon: <Icon name="location" />,  path: "/admin/locations" },
  { label: "Cameras",      icon: <Icon name="camera" />,    path: "/admin/cameras" },
  { label: "Safety Rules", icon: <Icon name="rules" />,     path: "/admin/rules" },
  { label: "Alerts",       icon: <Icon name="bell" />,      path: "/admin/alerts" },
];

export default adminMenuItems;
