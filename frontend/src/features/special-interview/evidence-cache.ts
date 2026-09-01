export const SPECIAL_EVIDENCE_CACHE_KEY = "special_requirement_user_evidence_v1";

export type ReusableEvidenceRecord = {
  key: string;
  [key: string]: unknown;
};

export function mergeReusableEvidence<T extends ReusableEvidenceRecord>(
  current: T[],
  incoming: T[],
): T[] {
  const merged = new Map(current.map((item) => [item.key.toLowerCase(), item]));
  incoming.forEach((item) => merged.set(item.key.toLowerCase(), item));
  return Array.from(merged.values());
}

export function readReusableEvidence<T extends ReusableEvidenceRecord>(
  storage: Pick<Storage, "getItem">,
): T[] {
  try {
    const payload = JSON.parse(storage.getItem(SPECIAL_EVIDENCE_CACHE_KEY) ?? "[]") as unknown;
    return Array.isArray(payload)
      ? payload.filter((item): item is T => Boolean(
        item
        && typeof item === "object"
        && typeof (item as { key?: unknown }).key === "string"
        && !(item as { key: string }).key.toLowerCase().startsWith("course_category_response:"),
      ))
      : [];
  } catch {
    return [];
  }
}

export function writeReusableEvidence<T extends ReusableEvidenceRecord>(
  storage: Pick<Storage, "setItem">,
  evidence: T[],
) {
  storage.setItem(SPECIAL_EVIDENCE_CACHE_KEY, JSON.stringify(
    evidence.filter((item) => !item.key.toLowerCase().startsWith("course_category_response:")),
  ));
}
