/**
 * i18n bootstrap — Korean primary, English fallback. Auto-detect from the
 * browser language list with a localStorage override.
 *
 * Keys are organised by domain (`brand`, `home`, `result`, `perform`, …)
 * so a translator can scan a single section instead of the whole bundle.
 * Untranslated keys fall through to the EN bundle to avoid blank UI.
 */

import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";

import ko from "./i18n/ko.json";
import en from "./i18n/en.json";


i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      ko: { translation: ko },
      en: { translation: en },
    },
    fallbackLng: "en",
    supportedLngs: ["ko", "en"],
    interpolation: { escapeValue: false },
    detection: {
      order: ["localStorage", "navigator"],
      lookupLocalStorage: "rechord:lang",
      caches: ["localStorage"],
    },
  });

export default i18n;
