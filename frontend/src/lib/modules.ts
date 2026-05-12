export const MODULES = [
  { id: "lots", label: "Lots" },
  { id: "costbook", label: "Costbook" },
  { id: "change_orders", label: "Change Orders" },
  { id: "reports", label: "Reports" },
  { id: "documents", label: "Documents" },
  { id: "settings", label: "Settings" },
] as const;

export type ModuleId = (typeof MODULES)[number]["id"];
export type PermissionLevel = "none" | "viewer" | "editor";
