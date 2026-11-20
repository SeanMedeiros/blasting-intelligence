import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./en.json";
import fr from "./fr.json";

function initialLang(): string {
  try {
    return localStorage.getItem("bi.lang") ?? "en";
  } catch {
    return "en";
  }
}

i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, fr: { translation: fr } },
  lng: initialLang(),
  fallbackLng: "en",
  interpolation: { escapeValue: false },
  returnObjects: true,
});

export function setLanguage(lng: "en" | "fr") {
  i18n.changeLanguage(lng);
  document.documentElement.lang = lng;
  try {
    localStorage.setItem("bi.lang", lng);
  } catch {
    /* storage unavailable */
  }
}

export default i18n;
