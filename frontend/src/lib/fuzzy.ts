export function normalizeSearch(value: string): string {
  return value
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/ё/g, "е")
    .replace(/[^a-zа-я0-9]+/gi, " ")
    .trim();
}

export function levenshteinDistance(a: string, b: string): number {
  if (a === b) return 0;
  if (!a.length) return b.length;
  if (!b.length) return a.length;

  const dp = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = 0; i <= a.length; i += 1) dp[i][0] = i;
  for (let j = 0; j <= b.length; j += 1) dp[0][j] = j;

  for (let i = 1; i <= a.length; i += 1) {
    for (let j = 1; j <= b.length; j += 1) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      dp[i][j] = Math.min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost);
    }
  }

  return dp[a.length][b.length];
}

export function fuzzyScore(query: string, candidate: string): number {
  const q = normalizeSearch(query);
  const c = normalizeSearch(candidate);
  if (!q) return 1;
  if (!c) return 0;
  if (c.includes(q)) return 1;

  const qWords = q.split(" ").filter(Boolean);
  const cWords = c.split(" ").filter(Boolean);
  let best = 0;

  for (const qWord of qWords) {
    for (const cWord of cWords) {
      const distance = levenshteinDistance(qWord, cWord);
      const maxLen = Math.max(qWord.length, cWord.length) || 1;
      const score = 1 - distance / maxLen;
      if (score > best) best = score;
    }
  }

  return best;
}

export function fuzzyFilter<T>(
  items: T[],
  query: string,
  getLabel: (item: T) => string | string[],
  minScore = 0.34
): T[] {
  const normalized = normalizeSearch(query);
  if (!normalized) return items;

  return items
    .map((item) => {
      const rawLabels = getLabel(item);
      const labels = Array.isArray(rawLabels) ? rawLabels : [rawLabels];
      const score = Math.max(...labels.map((label: string) => fuzzyScore(normalized, label)));
      return { item, score };
    })
    .filter((entry) => entry.score >= minScore)
    .sort((left, right) => right.score - left.score)
    .map((entry) => entry.item);
}
