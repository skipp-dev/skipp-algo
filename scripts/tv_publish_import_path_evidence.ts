function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function hasExpectedImportPathEvidence(bodyText: string, expectedImportPath: string): boolean {
  const normalizedBodyText = bodyText.replace(/\s+/g, " ");
  const trimmedImportPath = expectedImportPath.trim();
  if (trimmedImportPath.length === 0) {
    return false;
  }

  const importPathPattern = new RegExp(`(^|[^A-Za-z0-9_./-])${escapeRegExp(trimmedImportPath)}(?=$|[^A-Za-z0-9_./-])`);
  return importPathPattern.test(normalizedBodyText);
}
