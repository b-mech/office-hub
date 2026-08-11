import type { ProgramCapacity, ProgramDetail } from "@/types/program-allocations";

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
const PROGRAMS_PATH = "/api/v1/financing/programs";

async function apiFetch<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `API error ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function getPrograms(): Promise<ProgramCapacity[]> {
  return apiFetch<ProgramCapacity[]>(PROGRAMS_PATH);
}

export function getProgram(id: string): Promise<ProgramDetail> {
  return apiFetch<ProgramDetail>(`${PROGRAMS_PATH}/${id}`);
}

export async function getLenderPrograms(lenderId: string): Promise<ProgramDetail[]> {
  const programs = await getPrograms();
  return Promise.all(
    programs.filter((program) => program.lender_id === lenderId).map((program) => getProgram(program.id)),
  );
}
