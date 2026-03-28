const INVALID_PERSON_NAME_RE = /[^\p{L}\s'-]/gu;
const LEADING_PERSON_NAME_RE = /^[\s'-]+/u;
const TRAILING_PERSON_NAME_RE = /[\s'-]+$/u;

export const PERSON_NAME_HINT = "Допускаются только буквы, пробел, дефис и апостроф.";

export function sanitizePersonNamePart(value: string): string {
  return value
    .replace(INVALID_PERSON_NAME_RE, "")
    .replace(/\s{2,}/g, " ")
    .replace(/-{2,}/g, "-")
    .replace(/'{2,}/g, "'")
    .replace(LEADING_PERSON_NAME_RE, "");
}

export function finalizePersonNamePart(value: string): string {
  return sanitizePersonNamePart(value).replace(TRAILING_PERSON_NAME_RE, "").trim();
}

export function hasPersonName(fields: {
  firstName?: string | null;
  lastName?: string | null;
  middleName?: string | null;
}): boolean {
  return Boolean(
    finalizePersonNamePart(fields.firstName || "") ||
      finalizePersonNamePart(fields.lastName || "") ||
      finalizePersonNamePart(fields.middleName || "")
  );
}
