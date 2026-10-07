export type LeanStatus =
  | "main-result-formalized"
  | "comparator-challenge-only"
  | "none";

export function leanLabel(status: LeanStatus): string {
  switch (status) {
    case "main-result-formalized":
      return "Formalized main result";
    case "comparator-challenge-only":
      return "Comparator challenge only";
    case "none":
      return "No Lean formalization";
    default: {
      const exhaustive: never = status;
      return exhaustive;
    }
  }
}

export function leanRank(status: LeanStatus): number {
  switch (status) {
    case "main-result-formalized":
      return 0;
    case "comparator-challenge-only":
      return 1;
    case "none":
      return 2;
    default: {
      const exhaustive: never = status;
      return exhaustive;
    }
  }
}
