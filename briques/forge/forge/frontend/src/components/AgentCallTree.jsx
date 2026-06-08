import styles from './AgentCallTree.module.css'

/**
 * Displays the agent call chain as a breadcrumb: Orchestrator → Finance → CalculateROI
 * Built from react_step messages enriched with agentName and depth.
 */
export default function AgentCallTree({ steps }) {
  if (!steps?.length) return null

  // Build ordered list of unique agent names by depth
  const seen = new Map()
  for (const step of steps) {
    const name = step.agentName
    const depth = step.depth ?? 0
    if (name && !seen.has(name)) seen.set(name, depth)
  }

  const chain = [...seen.entries()]
    .sort((a, b) => a[1] - b[1])
    .map(([name]) => name)

  if (chain.length <= 1) return null

  return (
    <div className={styles.tree}>
      {chain.map((name, i) => (
        <span key={name} className={styles.node}>
          {i > 0 && <span className={styles.arrow}>→</span>}
          <span className={styles.label}>{name}</span>
        </span>
      ))}
    </div>
  )
}
