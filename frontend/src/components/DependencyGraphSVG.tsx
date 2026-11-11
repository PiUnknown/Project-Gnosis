import { useEffect, useMemo, useRef, useState, type PointerEvent, type WheelEvent } from 'react'
import { useReducedMotion } from 'motion/react'

export type GraphRisk = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'

export interface GraphNode {
  id: string
  path: string
  file?: string
  risk: GraphRisk
  imported_by: number
  imports: number
}

export interface GraphLink {
  source: string
  target: string
}

interface Props {
  nodes: GraphNode[]
  links: GraphLink[]
  cycles: string[][]
  selectedId: string | null
  onSelect: (node: GraphNode) => void
  maxNodes?: number
}

const HEIGHT = 620
const PADDING = 84
const MAX_RENDERED_NODES = 48
const RISKS: GraphRisk[] = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']

interface PositionedNode extends GraphNode {
  x: number
  y: number
  degree: number
}

function basename(path: string) {
  const slash = path.lastIndexOf('/')
  return slash < 0 ? path : path.slice(slash + 1)
}

function shortLabel(node: GraphNode) {
  const name = node.file || basename(node.path)
  return name.length > 20 ? `${name.slice(0, 18)}…` : name
}

function buildLayout(
  nodes: GraphNode[],
  links: GraphLink[],
  cycles: string[][],
  width: number,
  height: number,
) {
  if (nodes.length === 0) return { nodes: [] as PositionedNode[], links: [] as Array<{ a: PositionedNode; b: PositionedNode; cycle: boolean }> }

  const degree = new Map<string, number>()
  for (const node of nodes) degree.set(node.id, 0)
  for (const link of links) {
    degree.set(link.source, (degree.get(link.source) || 0) + 1)
    degree.set(link.target, (degree.get(link.target) || 0) + 1)
  }

  const ranked = [...nodes].sort((a, b) => {
    const scoreA = a.imported_by * 3 + a.imports + (degree.get(a.id) || 0)
    const scoreB = b.imported_by * 3 + b.imports + (degree.get(b.id) || 0)
    return scoreB - scoreA || a.path.localeCompare(b.path)
  })

  const centre = { x: width / 2, y: height / 2 }
  const positioned: PositionedNode[] = ranked.map((node, index) => {
    const angle = index * 2.399963
    const radius = Math.min(width, height) * (0.1 + 0.34 * Math.sqrt((index % 11) / 11))
    return {
      ...node,
      degree: degree.get(node.id) || 0,
      x: centre.x + Math.cos(angle) * radius + (index % 3) * 4,
      y: centre.y + Math.sin(angle) * radius + (index % 5) * 3,
    }
  })

  const byId = new Map(positioned.map((node) => [node.id, node]))
  const indexById = new Map(positioned.map((node, index) => [node.id, index]))
  const pairs: Array<{ ai: number; bi: number; a: PositionedNode; b: PositionedNode }> = []
  for (const link of links) {
    const ai = indexById.get(link.source)
    const bi = indexById.get(link.target)
    if (ai === undefined || bi === undefined || ai === bi) continue
    pairs.push({ ai, bi, a: positioned[ai], b: positioned[bi] })
  }

  const velocity = positioned.map(() => ({ x: 0, y: 0 }))
  const iterations = 280
  const pad = Math.min(PADDING, width * 0.1, height * 0.1)

  for (let step = 0; step < iterations; step += 1) {
    const forces = positioned.map(() => ({ x: 0, y: 0 }))

    for (let i = 0; i < positioned.length; i += 1) {
      for (let j = i + 1; j < positioned.length; j += 1) {
        const a = positioned[i]
        const b = positioned[j]
        let dx = a.x - b.x
        let dy = a.y - b.y
        let distanceSq = dx * dx + dy * dy
        if (distanceSq < 0.01) {
          dx = (i % 2 === 0 ? 1 : -1) * 0.7
          dy = (j % 2 === 0 ? 1 : -1) * 0.7
          distanceSq = 0.98
        }
        const distance = Math.sqrt(distanceSq)
        const minDistance = 52
        let force = 2400 / distanceSq
        if (distance < minDistance) force += (minDistance - distance) * 0.9

        const fx = (dx / distance) * force
        const fy = (dy / distance) * force
        forces[i].x += fx
        forces[i].y += fy
        forces[j].x -= fx
        forces[j].y -= fy
      }
    }

    for (const pair of pairs) {
      const dx = pair.b.x - pair.a.x
      const dy = pair.b.y - pair.a.y
      const distance = Math.hypot(dx, dy) || 0.01
      const ideal = 150
      const force = (distance - ideal) * 0.012
      const fx = (dx / distance) * force
      const fy = (dy / distance) * force
      forces[pair.ai].x += fx
      forces[pair.ai].y += fy
      forces[pair.bi].x -= fx
      forces[pair.bi].y -= fy
    }

    for (let i = 0; i < positioned.length; i += 1) {
      const node = positioned[i]
      forces[i].x += (centre.x - node.x) * 0.0025
      forces[i].y += (centre.y - node.y) * 0.0025
      velocity[i].x = (velocity[i].x + forces[i].x) * 0.82
      velocity[i].y = (velocity[i].y + forces[i].y) * 0.82
      const speed = Math.hypot(velocity[i].x, velocity[i].y)
      if (speed > 26) {
        velocity[i].x = (velocity[i].x / speed) * 26
        velocity[i].y = (velocity[i].y / speed) * 26
      }
      node.x += velocity[i].x
      node.y += velocity[i].y

      if (step > iterations * 0.75) {
        const left = pad
        const right = width - pad
        const top = pad
        const bottom = height - pad
        node.x = Math.min(right, Math.max(left, node.x))
        node.y = Math.min(bottom, Math.max(top, node.y))
      }
    }
  }

  // Normalise the settled cloud into the padded viewport.
  const xs = positioned.map((node) => node.x)
  const ys = positioned.map((node) => node.y)
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const spanX = maxX - minX || 1
  const spanY = maxY - minY || 1
  const availableW = width - pad * 2
  const availableH = height - pad * 2
  const fit = Math.min(availableW / spanX, availableH / spanY)
  const offsetX = (width - spanX * fit) / 2
  const offsetY = (height - spanY * fit) / 2

  for (const node of positioned) {
    node.x = offsetX + (node.x - minX) * fit
    node.y = offsetY + (node.y - minY) * fit
  }

  const cyclePairs = new Set<string>()
  const cycleMembers = new Set<string>(cycles.flat())
  for (const pair of pairs) {
    if (cycleMembers.has(pair.a.id) && cycleMembers.has(pair.b.id)) {
      cyclePairs.add(`${pair.a.id}\u0000${pair.b.id}`)
      cyclePairs.add(`${pair.b.id}\u0000${pair.a.id}`)
    }
  }

  return {
    nodes: positioned,
    links: pairs.map((pair) => ({
      a: pair.a,
      b: pair.b,
      cycle: cyclePairs.has(`${pair.a.id}\u0000${pair.b.id}`),
    })),
  }
}

export default function DependencyGraphSVG({
  nodes,
  links,
  cycles,
  selectedId,
  onSelect,
  maxNodes = MAX_RENDERED_NODES,
}: Props) {
  const reducedMotion = useReducedMotion()
  const containerRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 900, height: 620 })
  const [query, setQuery] = useState('')
  const [riskFilter, setRiskFilter] = useState<GraphRisk | 'ALL'>('ALL')
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [panning, setPanning] = useState(false)
  const dragRef = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null)

  const compact = size.width < 520
  const effectiveMaxNodes = compact ? Math.min(14, maxNodes) : maxNodes
  const viewH = HEIGHT
  const viewW = Math.max(
    420,
    Math.min(1100, Math.round(HEIGHT * (size.width / Math.max(1, size.height)))),
  )

  const trimmed = useMemo(() => {
    const degree = new Map<string, number>()
    for (const link of links) {
      degree.set(link.source, (degree.get(link.source) || 0) + 1)
      degree.set(link.target, (degree.get(link.target) || 0) + 1)
    }
    return [...nodes]
      .sort((a, b) => {
        const scoreA = a.imported_by * 3 + a.imports + (degree.get(a.id) || 0)
        const scoreB = b.imported_by * 3 + b.imports + (degree.get(b.id) || 0)
        return scoreB - scoreA || a.path.localeCompare(b.path)
      })
      .slice(0, effectiveMaxNodes)
  }, [nodes, links, effectiveMaxNodes])

  const trimmedIds = useMemo(() => new Set(trimmed.map((node) => node.id)), [trimmed])
  const trimmedLinks = useMemo(
    () => links.filter((link) => trimmedIds.has(link.source) && trimmedIds.has(link.target)),
    [links, trimmedIds],
  )
  const layout = useMemo(
    () => buildLayout(trimmed, trimmedLinks, cycles, viewW, viewH),
    [trimmed, trimmedLinks, cycles, viewW, viewH],
  )

  useEffect(() => {
    const element = containerRef.current
    if (!element) return
    const observer = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect
      if (box && box.width > 0 && box.height > 0) {
        setSize({ width: box.width, height: box.height })
      }
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    setZoom(1)
    setPan({ x: 0, y: 0 })
  }, [nodes, links])

  const needle = query.trim().toLowerCase()
  const visibleIds = useMemo(() => {
    const ids = new Set<string>()
    for (const node of layout.nodes) {
      if (riskFilter !== 'ALL' && node.risk !== riskFilter) continue
      if (needle && !node.path.toLowerCase().includes(needle)) continue
      ids.add(node.id)
    }
    return ids
  }, [layout.nodes, riskFilter, needle])

  const visibleNodes = layout.nodes.filter((node) => visibleIds.has(node.id))
  const selected = layout.nodes.find((node) => node.id === selectedId) || null

  const scale = Math.min(size.width / viewW, size.height / viewH) || 0.9
  const unit = 1 / scale
  const labelSize = 10 * unit
  const labelCap = compact ? 8 : 20
  const labelIds = useMemo(() => {
    if (needle) return new Set(visibleNodes.map((node) => node.id))
    return new Set(
      [...visibleNodes]
        .sort((a, b) => b.degree - a.degree || b.imported_by - a.imported_by)
        .slice(0, labelCap)
        .map((node) => node.id),
    )
  }, [visibleNodes, needle, labelCap])

  const cycleLabels = useMemo(() => {
    const labels: Array<{ x: number; y: number; text: string }> = []
    for (let index = 0; index < Math.min(cycles.length, 2); index += 1) {
      const members = cycles[index]
      const points = layout.nodes.filter((node) => members.includes(node.id) && visibleIds.has(node.id))
      if (points.length < 2) continue
      const x = points.reduce((total, node) => total + node.x, 0) / points.length
      const y = points.reduce((total, node) => total + node.y, 0) / points.length
      labels.push({ x, y, text: cycles.length > 1 ? `CYCLE ${index + 1}` : 'CYCLE' })
    }
    return labels
  }, [cycles, layout.nodes, visibleIds])

  const handleWheel = (event: WheelEvent<SVGSVGElement>) => {
    event.preventDefault()
    const next = zoom * (event.deltaY > 0 ? 0.88 : 1.12)
    setZoom(Math.min(3.5, Math.max(1, next)))
    if (next <= 1) setPan({ x: 0, y: 0 })
  }

  const handlePointerDown = (event: PointerEvent<SVGSVGElement>) => {
    if (zoom <= 1 || event.button !== 0) return
    const target = event.target as SVGElement
    if (target.closest('.graph-node')) return
    dragRef.current = { x: event.clientX, y: event.clientY, panX: pan.x, panY: pan.y }
    setPanning(true)
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  const handlePointerMove = (event: PointerEvent<SVGSVGElement>) => {
    if (!dragRef.current) return
    const drag = dragRef.current
    const dx = (event.clientX - drag.x) / scale
    const dy = (event.clientY - drag.y) / scale
    setPan({ x: drag.panX + dx, y: drag.panY + dy })
  }

  const endPan = (event: PointerEvent<SVGSVGElement>) => {
    if (!dragRef.current) return
    dragRef.current = null
    setPanning(false)
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  if (nodes.length === 0) {
    return <div className="graph-empty">NO DEPENDENCY DATA AVAILABLE</div>
  }

  return (
    <div ref={containerRef} className="graph-stage">
      <div className="graph-toolbar">
        <div className="graph-search">
          <span aria-hidden="true">/</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="FILTER FILES"
            aria-label="Filter dependency graph by file path"
          />
        </div>
        <div className="risk-filter" role="group" aria-label="Filter by risk">
          <button type="button" aria-pressed={riskFilter === 'ALL'} onClick={() => setRiskFilter('ALL')}>
            ALL
          </button>
          {RISKS.map((risk) => (
            <button
              key={risk}
              type="button"
              aria-pressed={riskFilter === risk}
              onClick={() => setRiskFilter(riskFilter === risk ? 'ALL' : risk)}
            >
              {risk}
            </button>
          ))}
        </div>
        <div className="zoom-controls">
          <button type="button" aria-label="Zoom out" onClick={() => setZoom((value) => Math.max(1, value / 1.25))}>
            −
          </button>
          <button type="button" aria-label="Zoom in" onClick={() => setZoom((value) => Math.min(3.5, value * 1.25))}>
            +
          </button>
          <button
            type="button"
            aria-label="Reset view"
            onClick={() => {
              setZoom(1)
              setPan({ x: 0, y: 0 })
            }}
          >
            RESET
          </button>
        </div>
      </div>

      <svg
        className={`graph-svg${panning ? ' is-panning' : ''}`}
        viewBox={`0 0 ${viewW} ${viewH}`}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label={`Dependency graph showing ${visibleNodes.length} of ${nodes.length} files`}
        onWheel={handleWheel}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={endPan}
        onPointerCancel={endPan}
      >
        <g
          transform={`translate(${viewW / 2} ${viewH / 2}) scale(${zoom}) translate(${-viewW / 2 - pan.x} ${-viewH / 2 - pan.y})`}
        >
          {layout.links.map((link, index) => {
            const visible = visibleIds.has(link.a.id) && visibleIds.has(link.b.id)
            return (
              <line
                key={`${link.a.id}-${link.b.id}-${index}`}
                className={`graph-edge${link.cycle ? ' is-cycle' : ' is-draw'}${visible ? '' : ' is-muted'}`}
                x1={link.a.x}
                y1={link.a.y}
                x2={link.b.x}
                y2={link.b.y}
                pathLength={link.cycle ? undefined : 1}
                strokeDasharray={link.cycle ? '3 4' : '1'}
                style={
                  reducedMotion
                    ? { opacity: visible ? 1 : 0 }
                    : { opacity: visible ? 1 : 0, animationDelay: `${Math.min(index, 30) * 0.018}s` }
                }
              />
            )
          })}

          {cycleLabels.map((label, index) => (
            <text
              key={`cycle-${index}`}
              className="graph-cycle-label"
              x={label.x}
              y={label.y - 6 * unit}
              fontSize={9 * unit}
              style={{ strokeWidth: 2.5 * unit }}
            >
              {label.text}
            </text>
          ))}

          {visibleNodes.map((node, index) => {
            const isSelected = node.id === selectedId
            const baseRadius = compact ? 6 : 4 + Math.min(3.5, node.imported_by * 0.55)
            const radius = (isSelected ? (compact ? 9 : 7.5) : baseRadius) * unit
            const showLabel = labelIds.has(node.id) || isSelected
            const labelY = node.y - radius - 7 * unit
            return (
              <g key={node.id}>
                <circle
                  className="graph-hit"
                  cx={node.x}
                  cy={node.y}
                  r={radius + (compact ? 13 : 8) * unit}
                  fill="transparent"
                  onClick={() => onSelect(node)}
                >
                  <title>{`${node.path} · ${node.imported_by} importers · ${node.imports} imports · ${node.risk}`}</title>
                </circle>
                <circle
                  className={`graph-node${isSelected ? ' is-selected' : ''}`}
                  cx={node.x}
                  cy={node.y}
                  r={radius}
                  pointerEvents="none"
                  style={reducedMotion ? undefined : { animationDelay: `${Math.min(index, 24) * 0.02}s` }}
                />
                {showLabel ? (
                  <text
                    className={`graph-label${isSelected ? ' is-selected' : ''}`}
                    x={node.x}
                    y={labelY}
                    fontSize={labelSize}
                    style={{ strokeWidth: 2.5 * unit }}
                  >
                    {shortLabel(node)}
                  </text>
                ) : null}
              </g>
            )
          })}
        </g>
      </svg>

      <div className="graph-detail">
        {selected ? (
          <>
            <span className="sel">{selected.path}</span>
            <span>{selected.risk}</span>
            <span>{selected.imported_by} IMPORTERS</span>
            <span>{selected.imports} IMPORTS</span>
          </>
        ) : (
          <span>NO FILE SELECTED</span>
        )}
        <span className="accent">
          SHOWING {visibleNodes.length}/{nodes.length} FILES
          {trimmed.length < nodes.length ? ` · TOP ${trimmed.length}` : ''}
        </span>
      </div>
    </div>
  )
}
