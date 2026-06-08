import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import '@livekit/components-styles'
import './styles/tokens.css'
import './styles/global.css'
import './i18n/index.js'
import { initTheme } from './theme/theme.js'

initTheme()

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode><App /></React.StrictMode>
)
