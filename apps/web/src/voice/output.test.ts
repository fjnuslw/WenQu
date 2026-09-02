import assert from "node:assert/strict";
import test from "node:test";

import {
  browserVoiceId,
  browserVoiceQuality,
  normalizeVoiceLocale,
  prepareSpeechText,
  selectBestBrowserVoice,
  toBrowserVoiceOptions,
} from "./output.ts";

function voice(
  name: string,
  lang: string,
  overrides: Partial<Pick<SpeechSynthesisVoice, "default" | "localService" | "voiceURI">> = {},
): SpeechSynthesisVoice {
  return {
    default: overrides.default ?? false,
    lang,
    localService: overrides.localService ?? true,
    name,
    voiceURI: overrides.voiceURI ?? `voice://${name}`,
  };
}

test("语言标签归一化兼容下划线和大小写", () => {
  assert.equal(normalizeVoiceLocale(" ZH_cn "), "zh-cn");
  assert.equal(normalizeVoiceLocale("cmn-CN"), "cmn-cn");
});

test("中文自动排序优先语言匹配和 Natural/Neural，淘汰基础合成器", () => {
  const voices = [
    voice("eSpeak Mandarin", "zh-CN"),
    voice("Google 普通话", "zh-CN", { localService: false }),
    voice("Microsoft Xiaoxiao Online (Natural)", "zh-CN", { localService: false }),
    voice("Taiwan Standard", "zh-TW"),
    voice("English Natural", "en-US", { localService: false }),
  ];

  const selected = selectBestBrowserVoice(voices, "zh-CN");

  assert.equal(selected?.name, "Microsoft Xiaoxiao Online (Natural)");
  assert.equal(browserVoiceQuality(voices[0]), "basic");
  assert.deepEqual(
    toBrowserVoiceOptions(voices, "zh-CN").map((item) => item.name),
    ["Microsoft Xiaoxiao Online (Natural)", "Google 普通话", "Taiwan Standard", "eSpeak Mandarin"],
  );
});

test("用户显式音色优先于自动评分，并按面试语言隔离候选项", () => {
  const natural = voice("Natural", "en-US", { localService: false });
  const preferred = voice("Preferred Standard", "en-GB");
  const chinese = voice("中文自然", "zh-CN");

  assert.equal(
    selectBestBrowserVoice([natural, preferred, chinese], "en-US", browserVoiceId(preferred))?.name,
    "Preferred Standard",
  );
  assert.deepEqual(
    toBrowserVoiceOptions([natural, preferred, chinese], "en-US").map((item) => item.name),
    ["Natural", "Preferred Standard"],
  );
});

test("大陆普通话标准音色优先于其他中文地区的 Natural 音色", () => {
  const mainland = voice("Mainland Standard", "cmn_Hans_CN");
  const taiwan = voice("Taiwan Natural", "zh-TW", { localService: false });

  assert.equal(selectBestBrowserVoice([taiwan, mainland], "zh-CN")?.name, "Mainland Standard");
});

test("朗读文本去掉 Markdown 噪声并为常见技术缩写增加停顿", () => {
  const spoken = prepareSpeechText("## 结论\n**RAG** 通过 [API](https://example.invalid) 调用 `LLM`。\n```ts\nx();\n```");

  assert.equal(spoken, "结论，R A G 通过 A P I 调用 L L M。，（代码略）");
});
