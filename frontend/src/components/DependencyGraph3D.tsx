import { useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph3D from '3d-force-graph'

export type GraphRisk = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'

export interface DependencyNode {
  id: string
  path: string
  name: string
  risk: GraphRisk
  imported_by: number
  imports: number
}

export interface DependencyLink {
  source: string
  target: string
}

interface GraphNode extends DependencyNode {
  directory: string
  x?: number
  y?: number
  z?: number
  vx?: number
  vy?: number
  vz?: number
}

interface GraphLink {
  source: string | GraphNode
  target: string | GraphNode
}

interface Props {
  nodes: DependencyNode[]
  links: DependencyLink[]
  cycles: string[][]
}

const RISK_COLOR: Record<GraphRisk, string> = {
  CRITICAL: '#1400FF',
  HIGH: '#6254FF',
  MEDIUM: '#968DFF',
  LOW: '#C2BEFF',
}

const RISKS: GraphRisk[] = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']

function directoryOf(path: string) {
  const slash = path.lastIndexOf('/')
  return slash < 0 ? '[ROOT]' : path.slice(0, slash).split('/')[0] || '[ROOT]'
}

function safeHtml(value: string) {
  return value.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]!)
}

export default function DependencyGraph3D({ nodes, links, cycles }: Props) {
  const mountRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<any>(null)
  const [query, setQuery] = useState('')
  const [visibleRisks, setVisibleRisks] = useState<Set<GraphRisk>>(() => new Set(RISKS))
  const [clustered, setClustered] = useState(false)
  const [selected, setSelected] = useState<DependencyNode | null>(null)
  const [webglError, setWebglError] = useState(false)

  const normalizedNodes = useMemo<GraphNode[]>(() => nodes.map(node => ({ ...node, directory: directoryOf(node.path) })), [nodes])
  const filteredData = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const visible = normalizedNodes.filter(node => visibleRisks.has(node.risk) && (!needle || node.path.toLowerCase().includes(needle)))
    const ids = new Set(visible.map(node => node.id))
    return {
      nodes: visible,
      links: links.filter(link => ids.has(link.source) && ids.has(link.target)).map(link => ({ ...link })),
    }
  }, [normalizedNodes, links, query, visibleRisks])

  useEffect(() => {
    if (!mountRef.current) return
    let graph: any
    try {
      graph = new ForceGraph3D(mountRef.current, { controlType: 'orbit', rendererConfig: { alpha: true, antialias: true } })
      graph = graph as any
      graph.backgroundColor('#F0F0FF')
        .showNavInfo(false)
        .nodeId('id')
        .nodeLabel((node: GraphNode) => `<div class="gnosis-graph-tooltip"><strong>${safeHtml(node.name)}</strong><span>${safeHtml(node.path)}</span><span>${node.imported_by} IMPORTERS · ${node.imports} IMPORTS · ${node.risk}</span></div>`)
        .nodeColor((node: GraphNode) => RISK_COLOR[node.risk])
        .nodeVal((node: GraphNode) => 1.8 + Math.min(node.imported_by, 14) * 0.25)
        .nodeOpacity(0.95)
        .nodeResolution(10)
        .linkColor(() => '#6254FF')
        .linkOpacity(0.24)
        .linkWidth(0.65)
        .linkDirectionalArrowLength(1.8)
        .linkDirectionalArrowRelPos(1)
        .linkDirectionalArrowColor(() => '#6254FF')
        .enableNavigationControls(true)
        .enableNodeDrag(true)
        .cooldownTicks(300)
        .onNodeClick((node: GraphNode) => {
          setSelected(node)
          const distance = 85
          const length = Math.hypot(node.x || 0, node.y || 0, node.z || 0) || 1
          graph.cameraPosition({ x: (node.x || 0) + distance * (node.x || 1) / length, y: (node.y || 0) + distance * (node.y || 1) / length, z: (node.z || 0) + distance * (node.z || 1) / length }, node, 650)
        })
        .onBackgroundClick(() => setSelected(null))

      graphRef.current = graph
    } catch {
      setWebglError(true)
      return
    }

    const observer = new ResizeObserver(entries => {
      const box = entries[0]?.contentRect
      if (box && box.width > 0 && box.height > 0) graph.width(box.width).height(box.height)
    })
    observer.observe(mountRef.current)
    return () => {
      observer.disconnect()
      graph._destructor?.()
      graphRef.current = null
    }
  }, [])

  useEffect(() => {
    const graph = graphRef.current
    if (!graph) return
    graph.graphData(filteredData)
    if (clustered) {
      const groups = [...new Set(filteredData.nodes.map((node: GraphNode) => node.directory))]
      const centers = new Map<string, { x: number; y: number; z: number }>()
      groups.forEach((group, index) => {
        const theta = Math.acos(1 - 2 * (index + 0.5) / Math.max(groups.length, 1))
        const phi = Math.PI * (1 + Math.sqrt(5)) * index
        centers.set(group, { x: 135 * Math.sin(theta) * Math.cos(phi), y: 135 * Math.cos(theta), z: 135 * Math.sin(theta) * Math.sin(phi) })
      })
      const force = (alpha: number) => {
        filteredData.nodes.forEach((node: GraphNode) => {
          const center = centers.get(node.directory)
          if (!center || node.x === undefined) return
          node.vx = (node.vx || 0) + (center.x - node.x) * alpha * 0.035
          node.vy = (node.vy || 0) + (center.y - (node.y || 0)) * alpha * 0.035
          node.vz = (node.vz || 0) + (center.z - (node.z || 0)) * alpha * 0.035
        })
      }
      graph.d3Force('directory-clusters', force)
      graph.d3ReheatSimulation()
    } else {
      graph.d3Force('directory-clusters', null)
      graph.d3ReheatSimulation()
    }
    graph.zoomToFit(550, 42)
    if (selected && !filteredData.nodes.some((node: GraphNode) => node.id === selected.id)) setSelected(null)
  }, [filteredData, clustered])

  const cycleFiles = useMemo(() => new Set(cycles.flat()), [cycles])
  const toggleRisk = (risk: GraphRisk) => setVisibleRisks(current => {
    const next = new Set(current)
    next.has(risk) ? next.delete(risk) : next.add(risk)
    return next
  })

  return (
    <section className="gnosis-graph-shell" aria-label="Interactive 3D dependency graph">
      <div className="gnosis-graph-toolbar">
        <div className="gnosis-graph-heading">
          <span className="gnosis-graph-kicker">STRUCTURAL MAP / WEBGL</span>
          <span className="gnosis-graph-count">{filteredData.nodes.length} NODES · {filteredData.links.length} EDGES</span>
        </div>
        <div className="gnosis-graph-controls">
          <label className="gnosis-graph-search">
            <span className="sr-only">Filter files</span>
            <span aria-hidden="true">⌕</span>
            <input value={query} onChange={event => setQuery(event.target.value)} placeholder="FILTER FILE PATH..." />
          </label>
          <button type="button" className={`gnosis-graph-cluster${clustered ? ' is-active' : ''}`} aria-pressed={clustered} onClick={() => setClustered(value => !value)}>
            {clustered ? 'DIRECTORIES: ON' : 'CLUSTER BY DIRECTORY'}
          </button>
        </div>
      </div>

      <div className="gnosis-graph-filter-row" aria-label="Filter by risk level">
        <span>RISK FILTER</span>
        {RISKS.map(risk => (
          <button key={risk} type="button" className={`gnosis-graph-risk${visibleRisks.has(risk) ? ' is-active' : ''}`} aria-pressed={visibleRisks.has(risk)} onClick={() => toggleRisk(risk)}>
            <i style={{ backgroundColor: RISK_COLOR[risk] }} />{risk}
          </button>
        ))}
        <button type="button" className="gnosis-graph-reset" onClick={() => { setQuery(''); setVisibleRisks(new Set(RISKS)); setClustered(false) }}>RESET VIEW</button>
      </div>

      <div className="gnosis-graph-stage">
        {nodes.length > 0 ? (
          webglError
            ? <div className="gnosis-graph-unavailable">WEBGL IS UNAVAILABLE IN THIS BROWSER. USE THE DEPENDENCY SUMMARY BELOW.</div>
            : <div ref={mountRef} className="gnosis-graph-canvas" />
        ) : (
          <div className="gnosis-graph-unavailable">FULL GRAPH DATA IS NOT AVAILABLE FOR THIS ANALYSIS.</div>
        )}
        {!webglError && nodes.length > 0 && <div className="gnosis-graph-axis-note">DRAG TO ORBIT · SCROLL TO ZOOM · SELECT A NODE FOR DETAILS</div>}
        {selected && !webglError && (
          <aside className="gnosis-graph-inspector" aria-live="polite">
            <button type="button" aria-label="Close node details" onClick={() => setSelected(null)}>×</button>
            <span className="gnosis-graph-kicker">SELECTED MODULE</span>
            <strong title={selected.path}>{selected.name}</strong>
            <code>{selected.path}</code>
            <div><span>RISK</span><b style={{ color: RISK_COLOR[selected.risk] }}>{selected.risk}{cycleFiles.has(selected.path) ? ' · CYCLE' : ''}</b></div>
            <div><span>IMPORTED BY</span><b>{selected.imported_by}</b></div>
            <div><span>IMPORTS</span><b>{selected.imports}</b></div>
          </aside>
        )}
      </div>
      <div className="gnosis-graph-legend">
        <span><i className="gnosis-legend-edge" /> IMPORT DIRECTION</span>
        <span><i className="gnosis-legend-node" /> NODE SIZE = IMPORTERS</span>
        <span>COLOR = RISK</span>
      </div>
    </section>
  )
}
