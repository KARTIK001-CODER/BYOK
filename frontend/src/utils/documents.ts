import { DocumentResponse } from "../api/documents";
import { MembershipResponse, Organization } from "../types";

/** Shared document display helpers (single source of truth). */

export const statusColor = (status: string): string => {
  switch (status?.toLowerCase()) {
    case "ready":
    case "completed":
      return "#10b981"; // emerald
    case "processing":
    case "uploading":
      return "#f59e0b"; // amber
    case "failed":
      return "#ef4444"; // red
    case "uploaded":
    case "pending":
      return "#6366f1"; // indigo
    default:
      return "#94a3b8"; // slate
  }
};

export const statusLabel = (status?: string | null): string => {
  if (!status) return "Unknown";
  return status.replaceAll("_", " ");
};

export const formatStatus = (s?: string | null): string => {
  if (!s) return "Not Started";
  return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase().replace("_", " ");
};

export const formatBytes = (bytes: number): string => {
  if (!bytes || bytes <= 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
};

export const formatDate = (isoStr?: string | null): string => {
  if (!isoStr) return "N/A";
  try {
    return new Date(isoStr).toLocaleString();
  } catch {
    return isoStr;
  }
};

export const isDocumentProcessing = (d: DocumentResponse): boolean => {
  const s = d.status?.toLowerCase();
  const es = d.embedding_status?.toLowerCase();
  if (s === "failed" || s === "archived") return false;
  if (s === "ready" && es === "failed") return false;
  return s === "processing" || s === "uploading" || es === "processing" || es === "pending";
};

/** Resolve the primary organization from a membership list (first entry). */
export const getPrimaryOrganization = (
  memberships: MembershipResponse[]
): Organization | null => {
  if (memberships.length === 0) return null;
  return (
    memberships[0]?.organization || {
      id: memberships[0].organization_id,
      name: "Workspace",
      slug: "workspace",
    }
  );
};
