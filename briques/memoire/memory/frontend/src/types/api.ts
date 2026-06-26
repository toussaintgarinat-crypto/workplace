export interface Location {
  wing: string
  room: string
  drawer?: string | null
}

export interface EdgeRef {
  id: string
  source_id: string
  target_id: string
  type: string
  weight: number
}

export interface NodeResponse {
  id: string
  space_id: string
  type: string
  ipcra_stage: string
  storage_tier: string
  status: string
  title: string
  content_md: string
  frontmatter: Record<string, unknown>
  access_count: number
  last_accessed?: string | null
  happened_at?: string | null
  stage_changed_at?: string | null
  source_url?: string | null
  captured_from?: string | null
  location?: Location | null
  edges: EdgeRef[]
  track_history: boolean
  created_at: string
  updated_at: string
}

export interface NodeRevision {
  id: string
  node_id: string
  title: string
  content_md: string
  frontmatter: Record<string, unknown>
  captured_at: string
}

export interface NodeCreate {
  type: string
  title: string
  content_md?: string
  frontmatter?: Record<string, unknown>
  location?: Location | null
  source_url?: string | null
  captured_from?: string | null
  happened_at?: string | null
}

export interface NodeUpdate {
  title?: string
  content_md?: string
  frontmatter?: Record<string, unknown>
  source_url?: string | null
  captured_from?: string | null
  happened_at?: string | null
  track_history?: boolean
}

export interface SearchResult {
  id: string
  title: string
  content_md: string
  type: string
  storage_tier: string
  happened_at?: string | null
  score: number
}

export interface PalaceRoom {
  id: string
  wing: string
  room: string
  drawer?: string | null
  children: PalaceRoom[]
}

export interface PalaceTree {
  wings: PalaceRoom[]
}

export interface GardienConfig {
  mode: string
  interval_minutes: number
  auto_summarize: boolean
  auto_merge: boolean
  auto_infer: boolean
  auto_suggest_ipcra: boolean
  auto_archive: boolean
}

export interface GardienSuggestion {
  id: string
  action: string
  node_id?: string | null
  details: Record<string, unknown>
  status: string
  created_at: string
}

export interface GraphNode {
  id: string
  title: string
  type: string
  pos?: { x: number; y: number } | null
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  type: string
  weight: number
}

export interface GraphResponse {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface GardienLogEntry {
  id: string
  action: string
  node_id?: string | null
  details: Record<string, unknown>
  status: string
  created_at: string
}

export interface Space {
  id: string
  name: string
  description: string
  role?: string
}

export interface Collection {
  id: string
  space_id: string
  name: string
  description: string
  filter_criteria?: Record<string, string> | null
  is_dynamic: boolean
  node_count: number
  created_at: string
}

export interface Template {
  id: string
  name: string
  node_type: string
  title_template: string
  content_template: string
  frontmatter_template?: string | null
  is_global: boolean
}
