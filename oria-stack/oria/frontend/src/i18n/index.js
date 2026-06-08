import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import fr from './locales/fr.json'
import en from './locales/en.json'
import zh from './locales/zh.json'
import es from './locales/es.json'
import ar from './locales/ar.json'
import pt from './locales/pt.json'
import ja from './locales/ja.json'

const LANG_KEY = 'oria_lang'
const savedLang = localStorage.getItem(LANG_KEY) || 'fr'

i18n
  .use(initReactI18next)
  .init({
    resources: {
      fr: { translation: fr },
      en: { translation: en },
      zh: { translation: zh },
      es: { translation: es },
      ar: { translation: ar },
      pt: { translation: pt },
      ja: { translation: ja },
    },
    lng:         savedLang,
    fallbackLng: 'fr',
    interpolation: { escapeValue: false },
  })

i18n.on('languageChanged', (lang) => {
  localStorage.setItem(LANG_KEY, lang)
  document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr'
  document.documentElement.lang = lang
})

// Set initial dir/lang
document.documentElement.dir  = savedLang === 'ar' ? 'rtl' : 'ltr'
document.documentElement.lang = savedLang

export default i18n
