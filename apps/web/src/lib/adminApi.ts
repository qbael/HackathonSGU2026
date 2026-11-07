import { api, write, writeHeaders, type Page } from "./api.ts";

export type AdminOverview = {
  totalItems: number;
  activeItems: number;
  returnedItems: number;
  hiddenItems: number;
  totalUsers: number;
  activeUsers: number;
  disabledUsers: number;
  totalHubs: number;
  activeHubs: number;
  totalCustodyEvents: number;
  totalHandovers: number;
};

export type AdminUser = {
  id: string;
  email: string | null;
  displayName: string;
  createdAt: string;
  disabledAt: string | null;
  isAdmin: boolean;
  itemsCount: number;
};

export type AdminItemImage = {
  id: string;
  position: number;
  contentVersion: number;
  processingState: string;
  reviewState: string;
  failureCode: string | null;
  retiredAt: string | null;
  previewUrl: string;
  redactionModelId: string | null;
  redactionProfile: string | null;
};

export type AdminItem = {
  id: string;
  title: string;
  publicDescription: string;
  foundArea: string;
  foundTimePrecision: string;
  foundOn: string | null;
  foundFrom: string | null;
  foundUntil: string | null;
  lifecycle: string;
  publicationState: string;
  rowVersion: number;
  createdAt: string;
  updatedAt: string;
  authorId: string;
  authorDisplayName: string;
  authorEmail: string | null;
  custodyKind: string;
  holderPointId: string | null;
  holderPointName: string | null;
  images: AdminItemImage[];
};

export type AdminPoint = {
  id: string;
  name: string;
  publicAddress: string;
  directions: string | null;
  active: boolean;
  createdAt: string;
  staffCount: number;
  itemsCount: number;
};

export type AdminStaff = {
  pointId: string;
  userId: string;
  email: string | null;
  displayName: string;
  canReceive: boolean;
  canReturn: boolean;
  assignedAt: string;
  revokedAt: string | null;
};

export function fetchAdminOverview(signal?: AbortSignal): Promise<AdminOverview> {
  return api<AdminOverview>("/api/admin/overview", { signal });
}

export function fetchAdminUsers(
  params: { query?: string; page?: number; pageSize?: number } = {},
  signal?: AbortSignal,
): Promise<Page<AdminUser>> {
  const query = new URLSearchParams();
  if (params.query) query.set("query", params.query);
  if (params.page) query.set("page", String(params.page));
  if (params.pageSize) query.set("pageSize", String(params.pageSize));
  const queryString = query.toString();
  return api<Page<AdminUser>>(`/api/admin/users${queryString ? `?${queryString}` : ""}`, { signal });
}

export function toggleUserStatus(userId: string): Promise<AdminUser> {
  return write<AdminUser>(`/api/admin/users/${userId}/toggle-status`, {});
}

export function fetchAdminItems(
  params: {
    query?: string;
    lifecycle?: string;
    publicationState?: string;
    page?: number;
    pageSize?: number;
  } = {},
  signal?: AbortSignal,
): Promise<Page<AdminItem>> {
  const query = new URLSearchParams();
  if (params.query) query.set("query", params.query);
  if (params.lifecycle) query.set("lifecycle", params.lifecycle);
  if (params.publicationState) query.set("publicationState", params.publicationState);
  if (params.page) query.set("page", String(params.page));
  if (params.pageSize) query.set("pageSize", String(params.pageSize));
  const queryString = query.toString();
  return api<Page<AdminItem>>(`/api/admin/items${queryString ? `?${queryString}` : ""}`, { signal });
}

export function setPublicationState(
  itemId: string,
  publicationState: "published" | "hidden",
): Promise<{ id: string; publicationState: string; rowVersion: number; updatedAt: string }> {
  return write(`/api/admin/items/${itemId}/set-publication`, { publicationState });
}

export function retireAdminImage(
  itemId: string,
  imageId: string,
): Promise<{ id: string; itemId: string; retiredAt: string; reviewState: string }> {
  return write(`/api/admin/items/${itemId}/images/${imageId}/retire`, {});
}

export function fetchAdminPoints(signal?: AbortSignal): Promise<AdminPoint[]> {
  return api<AdminPoint[]>("/api/admin/points", { signal });
}

export function createAdminPoint(data: {
  name: string;
  publicAddress: string;
  directions?: string;
}): Promise<AdminPoint> {
  return write<AdminPoint>("/api/admin/points", data);
}

export function togglePointActive(pointId: string): Promise<AdminPoint> {
  return write<AdminPoint>(`/api/admin/points/${pointId}/toggle`, {});
}

export function fetchPointStaff(pointId: string, signal?: AbortSignal): Promise<AdminStaff[]> {
  return api<AdminStaff[]>(`/api/admin/points/${pointId}/staff`, { signal });
}

export function assignPointStaff(
  pointId: string,
  data: { userEmail: string; canReceive: boolean; canReturn: boolean },
): Promise<AdminStaff> {
  return write<AdminStaff>(`/api/admin/points/${pointId}/staff`, data);
}

export async function revokePointStaff(pointId: string, userId: string): Promise<void> {
  const headers = await writeHeaders();
  await api<void>(`/api/admin/points/${pointId}/staff/${userId}`, {
    method: "DELETE",
    headers,
  });
}
