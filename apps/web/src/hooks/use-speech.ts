"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  browserVoiceId,
  prepareSpeechText,
  selectBestBrowserVoice,
  toBrowserVoiceOptions,
  type InterviewLocale,
  type VoiceCapabilities,
} from "@/voice/output";

/**
 * 浏览器原生语音识别（Web Speech API，spec 续十七）：
 * 能力与是否联网由浏览器实现决定；不假设具体供应商。
 * 不支持的浏览器 isSupported=false——调用方隐藏入口（诚实降级，不报错）。
 */

interface SpeechRecognitionAlternativeLike {
  transcript: string;
}
interface SpeechRecognitionResultLike {
  0: SpeechRecognitionAlternativeLike;
  isFinal: boolean;
  length: number;
}
interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: { length: number; [index: number]: SpeechRecognitionResultLike };
}
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
}
type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

function getRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function useSpeechRecognition(
  onFinalText: (text: string) => void,
  language: InterviewLocale = "zh-CN",
) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  // onFinalText 经 ref 透传，避免识别器因回调身份变化而重建
  const finalTextRef = useRef(onFinalText);
  finalTextRef.current = onFinalText;

  useEffect(() => {
    setSupported(getRecognitionCtor() !== null);
    return () => {
      recognitionRef.current?.abort();
      recognitionRef.current = null;
    };
  }, []);

  const stop = useCallback(() => {
    recognitionRef.current?.stop();
    setListening(false);
    setInterim("");
  }, []);

  const start = useCallback(() => {
    const Ctor = getRecognitionCtor();
    if (!Ctor) return;
    recognitionRef.current?.abort();
    const recognition = new Ctor();
    recognition.lang = language;
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.onresult = (event) => {
      let interimText = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        const transcript = result[0]?.transcript ?? "";
        if (result.isFinal) {
          finalTextRef.current(transcript.trim());
        } else {
          interimText += transcript;
        }
      }
      setInterim(interimText);
    };
    recognition.onerror = (event) => {
      setError(event.error === "not-allowed" ? "麦克风权限被拒绝" : `识别失败: ${event.error}`);
      setListening(false);
    };
    recognition.onend = () => {
      setListening(false);
      setInterim("");
    };
    recognitionRef.current = recognition;
    setError(null);
    setInterim("");
    setListening(true);
    recognition.start();
  }, [language]);

  return { supported, listening, interim, error, start, stop };
}

/** TTS：优先服务端神经语音；未配置时才使用经过质量排序的浏览器中文音色。 */
const VOICE_PREFERENCE_KEY = "getoffer.browser-voice";

export function useSpeechSynthesis(language: InterviewLocale = "zh-CN") {
  const [browserSupported, setBrowserSupported] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [capabilities, setCapabilities] = useState<VoiceCapabilities | null>(null);
  const [browserVoices, setBrowserVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [selectedVoiceId, setSelectedVoiceId] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);

  const stop = useCallback(() => {
    requestRef.current?.abort();
    requestRef.current = null;
    if (audioRef.current) {
      audioRef.current.onended = null;
      audioRef.current.onerror = null;
      audioRef.current.pause();
      audioRef.current.src = "";
      audioRef.current = null;
    }
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    utteranceRef.current = null;
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/voice/capabilities", { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`语音能力探测失败: ${response.status}`);
        return (await response.json()) as VoiceCapabilities;
      })
      .then(setCapabilities)
      .catch((caught: unknown) => {
        if (caught instanceof Error && caught.name === "AbortError") return;
        setCapabilities(null);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const available = "speechSynthesis" in window;
    setBrowserSupported(available);
    if (!available) return;

    const preferenceKey = `${VOICE_PREFERENCE_KEY}.${language}`;
    const loadVoices = () => {
      const voices = window.speechSynthesis.getVoices();
      setBrowserVoices(voices);
      let preferred: string | null = null;
      try {
        preferred = window.localStorage.getItem(preferenceKey);
      } catch {
        // 隐私模式可能禁用 localStorage；音色枚举与自动选择仍可工作。
      }
      const selected = selectBestBrowserVoice(voices, language, preferred);
      setSelectedVoiceId(selected ? browserVoiceId(selected) : "");
    };

    loadVoices();
    window.speechSynthesis.addEventListener("voiceschanged", loadVoices);
    // Chrome/Safari 可能既不立即返回 voice，也延迟/漏发 voiceschanged；有限重试覆盖该差异。
    const retryTimers = [50, 250, 1000].map((delay) => window.setTimeout(loadVoices, delay));
    return () => {
      retryTimers.forEach((timer) => window.clearTimeout(timer));
      window.speechSynthesis.removeEventListener("voiceschanged", loadVoices);
      stop();
    };
  }, [language, stop]);

  useEffect(() => {
    if (!enabled) stop();
  }, [enabled, stop]);

  const playBrowserSpeech = useCallback(
    (spokenText: string, preferredId: string | null = selectedVoiceId) => {
      if (typeof window === "undefined" || !("speechSynthesis" in window)) {
        setError("当前浏览器没有可用语音，且服务端神经语音未配置");
        return;
      }
      stop();
      setError(null);
      const utterance = new SpeechSynthesisUtterance(spokenText);
      utterance.lang = language;
      utterance.rate = 1;
      utterance.pitch = 1;
      const browserVoice = selectBestBrowserVoice(browserVoices, language, preferredId);
      if (browserVoice) utterance.voice = browserVoice;
      const release = () => {
        if (utteranceRef.current === utterance) utteranceRef.current = null;
      };
      utterance.onend = release;
      utterance.onerror = (event) => {
        release();
        if (event.error !== "canceled" && event.error !== "interrupted") {
          setError(`系统语音播放失败: ${event.error}`);
        }
      };
      utteranceRef.current = utterance;
      window.speechSynthesis.speak(utterance);
    },
    [browserVoices, language, selectedVoiceId, stop],
  );

  const speak = useCallback(
    async (text: string) => {
      if (!enabled || typeof window === "undefined") return;
      const spokenText = prepareSpeechText(text);
      if (!spokenText) return;
      stop();
      setError(null);

      if (capabilities?.configured) {
        const controller = new AbortController();
        requestRef.current = controller;
        try {
          const response = await fetch("/api/voice/tts", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: spokenText }),
            signal: controller.signal,
          });
          if (!response.ok) {
            const body = (await response.json().catch(() => null)) as
              | { error?: { message?: string } }
              | null;
            throw new Error(body?.error?.message ?? `神经语音生成失败: ${response.status}`);
          }
          const url = URL.createObjectURL(await response.blob());
          audioUrlRef.current = url;
          const audio = new Audio(url);
          audioRef.current = audio;
          audio.onended = () => {
            if (audioRef.current === audio) audioRef.current = null;
            if (audioUrlRef.current === url) {
              URL.revokeObjectURL(url);
              audioUrlRef.current = null;
            }
          };
          audio.onerror = () => {
            const message = audio.error?.message || `媒体错误 ${audio.error?.code ?? "unknown"}`;
            if (audioRef.current === audio) setError(`神经语音播放失败: ${message}`);
            if (audioRef.current === audio) audioRef.current = null;
            if (audioUrlRef.current === url) {
              URL.revokeObjectURL(url);
              audioUrlRef.current = null;
            }
          };
          await audio.play();
        } catch (caught) {
          if (caught instanceof Error && caught.name === "AbortError") return;
          setError(caught instanceof Error ? caught.message : String(caught));
          stop();
        } finally {
          if (requestRef.current === controller) requestRef.current = null;
        }
        return;
      }

      playBrowserSpeech(spokenText);
    },
    [capabilities, enabled, playBrowserSpeech, stop],
  );

  const browserVoice = selectBestBrowserVoice(browserVoices, language, selectedVoiceId);
  const voiceOptions = toBrowserVoiceOptions(browserVoices, language);
  const selectBrowserVoice = useCallback(
    (id: string) => {
      const selected = selectBestBrowserVoice(browserVoices, language, id);
      if (!selected) return;
      const stableId = browserVoiceId(selected);
      setSelectedVoiceId(stableId);
      try {
        window.localStorage.setItem(`${VOICE_PREFERENCE_KEY}.${language}`, stableId);
      } catch {
        // 偏好无法持久化不应阻塞当前会话选择。
      }
    },
    [browserVoices, language],
  );
  const previewBrowserVoice = useCallback(
    (id: string) => {
      playBrowserSpeech(
        language === "zh-CN" ? "你好，我是本场面试官。我们开始吧。" : "Hello, I will be your interviewer today.",
        id,
      );
    },
    [language, playBrowserSpeech],
  );

  const providerLabel = capabilities?.configured
    ? `神经语音 · ${capabilities.provider}/${capabilities.voice ?? "默认音色"}`
    : `系统语音 · ${browserVoice?.name ?? `浏览器默认${language === "zh-CN" ? "中文" : "英文"}音色`}`;
  const supported = browserSupported || Boolean(capabilities?.configured);

  return {
    supported,
    enabled,
    setEnabled,
    speak,
    stop,
    error,
    providerLabel,
    usesBrowser: !capabilities?.configured,
    voiceOptions,
    selectedVoiceId,
    selectBrowserVoice,
    previewBrowserVoice,
  };
}
