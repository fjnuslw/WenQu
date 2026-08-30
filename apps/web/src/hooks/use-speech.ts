"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * 浏览器原生语音识别（Web Speech API，spec 续十七）：
 * Chrome/Edge 走 Google/Azure 云识别（需网络），支持 zh-CN 实时转写。
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

export function useSpeechRecognition(onFinalText: (text: string) => void) {
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
    recognition.lang = "zh-CN";
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
  }, []);

  return { supported, listening, interim, error, start, stop };
}

/** TTS：SpeechSynthesis 朗读（zh-CN），支持开关与打断。 */
export function useSpeechSynthesis() {
  const [supported, setSupported] = useState(false);
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    setSupported(typeof window !== "undefined" && "speechSynthesis" in window);
    return () => {
      if (typeof window !== "undefined" && "speechSynthesis" in window) {
        window.speechSynthesis.cancel();
      }
    };
  }, []);

  const speak = useCallback(
    (text: string) => {
      if (!enabled || typeof window === "undefined" || !("speechSynthesis" in window)) return;
      const utterance = new SpeechSynthesisUtterance(
        // 朗读纯文本：剥掉 markdown 标记（显示层关切——代码/表格念出来是噪声）
        text
          .replace(/```[\s\S]*?```/g, "（代码略）")
          .replace(/[#*`>\[\]()_-]/g, "")
          .slice(0, 500),
      );
      utterance.lang = "zh-CN";
      utterance.rate = 1.05;
      const zhVoice = window.speechSynthesis.getVoices().find((voice) => voice.lang.startsWith("zh"));
      if (zhVoice) utterance.voice = zhVoice;
      window.speechSynthesis.cancel(); // 新一轮打断上一轮
      window.speechSynthesis.speak(utterance);
    },
    [enabled],
  );

  return { supported, enabled, setEnabled, speak };
}
