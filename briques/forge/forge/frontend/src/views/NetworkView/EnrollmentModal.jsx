import { useState, useEffect, useRef } from 'react'
import QRCode from 'qrcode'
import { netbird } from '../../services/api'
import styles from './Enrollment.module.css'

const PLATFORMS = [
  { id: 'mobile', label: '📱 Mobile' },
  { id: 'macos',  label: ' macOS' },
  { id: 'linux',  label: '🐧 Linux' },
  { id: 'windows',label: '🪟 Windows' },
]

const DOWNLOAD = {
  ios:     'https://apps.apple.com/app/netbird-vpn/id6471289228',
  android: 'https://play.google.com/store/apps/details?id=io.netbird.android',
  macos:   'https://pkgs.netbird.io/macos/amd64',
  linux:   'https://pkgs.netbird.io/debian/dists',
  windows: 'https://pkgs.netbird.io/windows/x86/netbird_installer_latest_windows_amd64.exe',
}

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <button className={styles.copyBtn} onClick={copy}>
      {copied ? '✓ Copié' : 'Copier'}
    </button>
  )
}

function PlatformContent({ platform, setupKey, managementUrl }) {
  const cmd = (bin) => `${bin} up --management-url ${managementUrl} --setup-key ${setupKey}`

  if (platform === 'mobile') {
    return (
      <div className={styles.mobileContent}>
        <div className={styles.mobileSteps}>
          <div className={styles.step}>
            <span className={styles.stepNum}>1</span>
            <div>
              <div className={styles.stepTitle}>Installer NetBird</div>
              <div className={styles.stepDesc}>Téléchargez l'app sur votre appareil</div>
              <div className={styles.storeLinks}>
                <a href={DOWNLOAD.ios} target="_blank" rel="noreferrer" className={styles.storeBtn}>App Store (iOS)</a>
                <a href={DOWNLOAD.android} target="_blank" rel="noreferrer" className={styles.storeBtn}>Google Play</a>
              </div>
            </div>
          </div>
          <div className={styles.step}>
            <span className={styles.stepNum}>2</span>
            <div>
              <div className={styles.stepTitle}>Configurer le serveur</div>
              <div className={styles.stepDesc}>Dans NetBird → Paramètres → URL de gestion :</div>
              <div className={styles.codeRow}>
                <code className={styles.code}>{managementUrl}</code>
                <CopyButton text={managementUrl} />
              </div>
            </div>
          </div>
          <div className={styles.step}>
            <span className={styles.stepNum}>3</span>
            <div>
              <div className={styles.stepTitle}>Scanner ce QR code</div>
              <div className={styles.stepDesc}>Ouvrez NetBird → Ajouter un réseau → Scanner</div>
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (platform === 'macos') {
    return (
      <div className={styles.platformContent}>
        <div className={styles.platformOption}>
          <div className={styles.optionTitle}>Via Homebrew</div>
          <div className={styles.codeBlock}>
            <code>{`brew install netbirdio/tap/netbird\nsudo netbird service install\nsudo netbird service start\n${cmd('netbird')}`}</code>
            <CopyButton text={`brew install netbirdio/tap/netbird && sudo netbird service install && sudo netbird service start && ${cmd('netbird')}`} />
          </div>
        </div>
        <div className={styles.platformOption}>
          <div className={styles.optionTitle}>Ou télécharger l'installeur</div>
          <a href={DOWNLOAD.macos} target="_blank" rel="noreferrer" className={styles.downloadBtn}>
            Télécharger NetBird pour macOS →
          </a>
        </div>
      </div>
    )
  }

  if (platform === 'linux') {
    return (
      <div className={styles.platformContent}>
        <div className={styles.platformOption}>
          <div className={styles.optionTitle}>Installation + connexion en une commande</div>
          <div className={styles.codeBlock}>
            <code>{`curl -fsSL https://pkgs.netbird.io/install.sh | sudo bash\n${cmd('sudo netbird')}`}</code>
            <CopyButton text={`curl -fsSL https://pkgs.netbird.io/install.sh | sudo bash && ${cmd('sudo netbird')}`} />
          </div>
        </div>
      </div>
    )
  }

  if (platform === 'windows') {
    return (
      <div className={styles.platformContent}>
        <div className={styles.platformOption}>
          <div className={styles.optionTitle}>1. Télécharger l'installeur</div>
          <a href={DOWNLOAD.windows} className={styles.downloadBtn}>
            Télécharger NetBird pour Windows →
          </a>
        </div>
        <div className={styles.platformOption}>
          <div className={styles.optionTitle}>2. Après installation, dans PowerShell (admin)</div>
          <div className={styles.codeBlock}>
            <code>{cmd('netbird')}</code>
            <CopyButton text={cmd('netbird')} />
          </div>
        </div>
      </div>
    )
  }

  return null
}

export default function EnrollmentModal({ onClose }) {
  const [step, setStep]         = useState('confirm')  // confirm | loading | ready
  const [platform, setPlatform] = useState('mobile')
  const [setupKey, setSetupKey] = useState(null)
  const [qrDataUrl, setQrDataUrl] = useState(null)
  const [error, setError]       = useState(null)
  const [timeLeft, setTimeLeft] = useState(86400)
  const timerRef                = useRef(null)

  const managementUrl = `http://${window.location.hostname}:33073`

  const generate = async () => {
    setStep('loading')
    setError(null)
    try {
      const data = await netbird.createSetupKey()
      if (data.error) throw new Error(data.error)
      setSetupKey(data.key)

      const qr = await QRCode.toDataURL(data.key, {
        width: 240,
        margin: 2,
        color: { dark: '#e8e8f0', light: '#13131a' },
      })
      setQrDataUrl(qr)
      setTimeLeft(86400)
      setStep('ready')

      timerRef.current = setInterval(() => {
        setTimeLeft(t => {
          if (t <= 1) { clearInterval(timerRef.current); return 0 }
          return t - 1
        })
      }, 1000)
    } catch (e) {
      setError(e.message)
      setStep('confirm')
    }
  }

  useEffect(() => () => clearInterval(timerRef.current), [])

  const formatTime = (s) => {
    const h = Math.floor(s / 3600)
    const m = Math.floor((s % 3600) / 60)
    const sec = s % 60
    return h > 0 ? `${h}h ${m}m` : `${m}m ${sec}s`
  }

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={e => e.stopPropagation()}>
        <div className={styles.modalHeader}>
          <div>
            <h2 className={styles.modalTitle}>Connecter un appareil</h2>
            <p className={styles.modalSub}>Génère un code d'enrollment à usage unique (24h)</p>
          </div>
          <button className={styles.closeBtn} onClick={onClose}>✕</button>
        </div>

        {step === 'confirm' && (
          <div className={styles.confirmStep}>
            <div className={styles.warningBox}>
              <div className={styles.warningIcon}>🔐</div>
              <div>
                <div className={styles.warningTitle}>Autorisation requise</div>
                <div className={styles.warningText}>
                  Vous allez générer un Setup Key NetBird. Ce code permettra à n'importe quel appareil de rejoindre votre réseau privé pendant 24h (usage unique).
                </div>
              </div>
            </div>
            {error && <div className={styles.errorBox}>{error}</div>}
            <div className={styles.confirmActions}>
              <button className={styles.cancelBtn} onClick={onClose}>Annuler</button>
              <button className={styles.generateBtn} onClick={generate}>
                Générer le code d'enrollment
              </button>
            </div>
          </div>
        )}

        {step === 'loading' && (
          <div className={styles.loadingStep}>
            <div className={styles.spinner} />
            <div>Génération du Setup Key…</div>
          </div>
        )}

        {step === 'ready' && (
          <div className={styles.readyStep}>
            <div className={styles.expiryBadge}>
              ⏱ Expire dans {formatTime(timeLeft)} · Usage unique
            </div>

            <div className={styles.splitLayout}>
              <div className={styles.qrSide}>
                {qrDataUrl && <img src={qrDataUrl} alt="QR enrollment" className={styles.qrImage} />}
                <div className={styles.keyDisplay}>
                  <code>{setupKey}</code>
                  <CopyButton text={setupKey} />
                </div>
                <div className={styles.mgmtUrl}>
                  <span className={styles.mgmtLabel}>Serveur</span>
                  <code>{managementUrl}</code>
                  <CopyButton text={managementUrl} />
                </div>
              </div>

              <div className={styles.instructionsSide}>
                <div className={styles.platformTabs}>
                  {PLATFORMS.map(p => (
                    <button
                      key={p.id}
                      className={`${styles.platformTab} ${platform === p.id ? styles.platformTabActive : ''}`}
                      onClick={() => setPlatform(p.id)}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
                <div className={styles.platformBody}>
                  <PlatformContent
                    platform={platform}
                    setupKey={setupKey}
                    managementUrl={managementUrl}
                  />
                </div>
              </div>
            </div>

            <div className={styles.modalFooter}>
              <button className={styles.generateBtn} onClick={generate}>
                Générer un nouveau code
              </button>
              <button className={styles.cancelBtn} onClick={onClose}>Fermer</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
