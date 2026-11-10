import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type CardTile = Schemas["CardTile"];
export type CardDetail = Schemas["CardDetail"];
export type BoardSnapshot = Schemas["BoardSnapshot"];
export type BoardSummary = Schemas["BoardSummary"];
export type ColumnOut = Schemas["ColumnOut"];
export type UserBrief = Schemas["UserBrief"];
export type UserOut = Schemas["UserOut"];
export type TagOut = Schemas["TagOut"];
export type EventOut = Schemas["EventOut"];
export type CommentOut = Schemas["CommentOut"];
export type StepOut = Schemas["StepOut"];
export type NotificationGroup = Schemas["NotificationGroup"];
export type RichText = { [key: string]: unknown };
export type UsersMap = Record<string, UserBrief>;

/** A problem+json error from the API. */
export class ApiError extends Error {
  readonly status: number;
  readonly problem: Record<string, unknown>;

  constructor(status: number, problem: Record<string, unknown>) {
    const detail = problem.detail ?? problem.title ?? `Request failed (${status})`;
    super(String(detail));
    this.status = status;
    this.problem = problem;
  }
}

export const api = createClient<paths>({ baseUrl: "/" });

/** Unwrap an openapi-fetch result: return data or throw ApiError. */
export async function call<T>(
  request: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await request;
  if (!response.ok) {
    throw new ApiError(response.status, (error ?? {}) as Record<string, unknown>);
  }
  return data as T;
}

export const COLUMN_COLORS = [
  "gray",
  "red",
  "orange",
  "amber",
  "lime",
  "green",
  "teal",
  "cyan",
  "blue",
  "indigo",
  "violet",
  "pink",
] as const;
export type ColumnColor = (typeof COLUMN_COLORS)[number];

export function colorVar(color: string): string {
  return `var(--col-${color}, var(--col-gray))`;
}
