export type InterviewLocale = "zh-CN" | "en-US";

export interface VoiceCapabilities {
  configured: boolean;
  provider: "disabled" | "openai_compatible" | "cosyvoice";
  voice: string | null;
  quality: "neural" | "browser";
}

export interface BrowserVoiceOption {
  id: string;
  name: string;
  lang: string;
  quality: "natural" | "standard" | "basic";
}

/** 显示文本与朗读文本分离：保留语义和标点，只移除 Markdown 噪声并展开常见缩写。 */
export function prepareSpeechText(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, "（代码略）")
    .replace(/\[([^\]]+)]\([^)]+\)/g, "$1")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/[\*_`>]/g, "")
    .replace(/\bRAG\b/gi, "R A G")
    .replace(/\bACL\b/gi, "A C L")
    .replace(/\bAPI\b/gi, "A P I")
    .replace(/\bLLM\b/gi, "L L M")
    .replace(/\s*\n+\s*/g, "，")
    .replace(/\s{2,}/g, " ")
    .trim()
    .slice(0, 700);
}

export function normalizeVoiceLocale(language: string): string {
  return language.trim().replace(/_/g, "-").toLowerCase();
}

/** voiceURI 在同一浏览器 profile 内通常稳定；附带语言/名称避免供应商 URI 碰撞。 */
export function browserVoiceId(voice: SpeechSynthesisVoice): string {
  return [voice.voiceURI, normalizeVoiceLocale(voice.lang), voice.name].join("::");
}

function isCompatibleLocale(candidate: string, requested: InterviewLocale): boolean {
  const locale = normalizeVoiceLocale(candidate);
  if (requested === "zh-CN") {
    return locale.startsWith("zh") || locale.startsWith("cmn");
  }
  return locale.startsWith("en");
}

function languageScore(candidate: string, requested: InterviewLocale): number {
  const locale = normalizeVoiceLocale(candidate);
  if (!isCompatibleLocale(locale, requested)) return -1000;
  if (requested === "zh-CN") {
    if (
      /^(zh|cmn)-(cn|sg)$/.test(locale) ||
      /^(zh|cmn)-hans(-(cn|sg))?$/.test(locale)
    ) {
      return 300;
    }
    if (locale === "zh" || locale === "cmn") return 230;
    // 仍可朗读普通话文本，但大陆普通话应优先于 zh-TW / zh-HK / yue。
    return 100;
  }
  if (locale === "en-us") return 300;
  if (locale.startsWith("en-us-")) return 285;
  return 140;
}

export function browserVoiceQuality(
  voice: Pick<SpeechSynthesisVoice, "name">,
): BrowserVoiceOption["quality"] {
  const name = voice.name.toLowerCase();
  if (/natural|neural|premium|enhanced|高品质|精品|自然/.test(name)) return "natural";
  if (/espeak|festival|compact|legacy/.test(name)) return "basic";
  return "standard";
}

/**
 * 跨浏览器启发式排序。语言匹配权重大于品牌；质量词只用于同语言音色间排序。
 * 用户显式选择始终优先，避免把 Windows/macOS/Chrome 的命名习惯写成强制策略。
 */
export function browserVoiceScore(
  voice: SpeechSynthesisVoice,
  requested: InterviewLocale = "zh-CN",
): number {
  const name = voice.name.toLowerCase();
  let score = languageScore(voice.lang, requested);
  const quality = browserVoiceQuality(voice);
  if (quality === "natural") score += 100;
  if (quality === "basic") score -= 250;
  if (/online|cloud/.test(name)) score += 35;
  if (/xiaoxiao|yunxi|yunjian|yunyang|晓晓|云希|云健|云扬/.test(name)) score += 55;
  if (name.includes("google") && /普通话|mandarin/.test(name)) score += 35;
  // remote voice 往往是浏览器提供的云端音色，但只是弱信号，不能压过语言和质量标识。
  if (!voice.localService) score += 10;
  if (voice.default) score += 5;
  return score;
}

export function compatibleBrowserVoices(
  voices: readonly SpeechSynthesisVoice[],
  requested: InterviewLocale,
): SpeechSynthesisVoice[] {
  return voices
    .filter((voice) => isCompatibleLocale(voice.lang, requested))
    .sort((left, right) => {
      const scoreDiff = browserVoiceScore(right, requested) - browserVoiceScore(left, requested);
      return scoreDiff || left.name.localeCompare(right.name);
    });
}

export function selectBestBrowserVoice(
  voices: readonly SpeechSynthesisVoice[],
  requested: InterviewLocale,
  preferredId?: string | null,
): SpeechSynthesisVoice | null {
  const compatible = compatibleBrowserVoices(voices, requested);
  if (preferredId) {
    const preferred = compatible.find((voice) => browserVoiceId(voice) === preferredId);
    if (preferred) return preferred;
  }
  return compatible[0] ?? null;
}

export function toBrowserVoiceOptions(
  voices: readonly SpeechSynthesisVoice[],
  requested: InterviewLocale,
): BrowserVoiceOption[] {
  return compatibleBrowserVoices(voices, requested).map((voice) => ({
    id: browserVoiceId(voice),
    name: voice.name,
    lang: voice.lang,
    quality: browserVoiceQuality(voice),
  }));
}
