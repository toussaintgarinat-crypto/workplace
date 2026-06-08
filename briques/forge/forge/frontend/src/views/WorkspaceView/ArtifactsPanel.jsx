import styles from './ArtifactsPanel.module.css'

export default function ArtifactsPanel({ artifacts, onApprove, onReject, onClose }) {
  return (
    <aside className={`${styles.panel} artifacts`}>
      <div className={styles.header}>
        <span>Artifacts</span>
        <button className={styles.closeBtn} onClick={onClose}>✕</button>
      </div>

      <div className={styles.list}>
        {artifacts.map(artifact => (
          <div key={artifact.id} className={`${styles.artifact} ${styles[artifact.status]}`}>
            <div className={styles.artifactHeader}>
              <span className={styles.type}>{artifact.type}</span>
              {artifact.language && (
                <span className={styles.lang}>{artifact.language}</span>
              )}
              <span className={`${styles.status} ${styles[artifact.status]}`}>
                {artifact.status}
              </span>
            </div>

            {artifact.type === 'code' && (
              <pre className={styles.code}>
                <code>{artifact.content.slice(0, 300)}{artifact.content.length > 300 ? '...' : ''}</code>
              </pre>
            )}

            {artifact.status === 'pending' && (
              <div className={styles.actions}>
                <button
                  className={styles.approveBtn}
                  onClick={() => onApprove(artifact.id)}
                >
                  Approve
                </button>
                <button
                  className={styles.rejectBtn}
                  onClick={() => onReject(artifact.id)}
                >
                  Reject
                </button>
              </div>
            )}

            {artifact.status === 'approved' && (
              <div className={styles.approvedBadge}>✓ Approved</div>
            )}
          </div>
        ))}
      </div>
    </aside>
  )
}
