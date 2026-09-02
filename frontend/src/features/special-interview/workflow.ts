export type PostRequirementsStep = "special_interview" | "current_gap";

export function nextStepAfterSpecialExtraction(remainingItemCount: number): PostRequirementsStep {
  return remainingItemCount > 0 ? "special_interview" : "current_gap";
}
