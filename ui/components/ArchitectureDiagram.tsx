'use client'

import { useState } from 'react'

type NodeId =
  | 'kalshi_prism'
  | 'poly_prism'
  | 'custom_prism'
  | 'registry'
  | 'velocity'
  | 'dedup'
  | 'sizer'
  | 'mcp'
  | 'exit'

const UPSTREAM: Record<NodeId, NodeId[]> = {
  kalshi_prism: [],
  poly_prism: [],
  custom_prism: [],
  registry: ['kalshi_prism', 'poly_prism', 'custom_prism'],
  velocity: ['kalshi_prism', 'poly_prism', 'custom_prism', 'registry'],
  dedup: ['kalshi_prism', 'poly_prism', 'custom_prism', 'registry', 'velocity'],
  sizer: ['kalshi_prism', 'poly_prism', 'custom_prism', 'registry', 'velocity', 'dedup'],
  mcp: ['kalshi_prism', 'poly_prism', 'custom_prism', 'registry', 'velocity', 'dedup', 'sizer'],
  exit: ['poly_prism', 'registry', 'mcp', 'kalshi_prism', 'velocity', 'dedup', 'sizer'],
}

type NodeDef = {
  id: NodeId
  label: string
  x: number
  y: number
  w: number
  h: number
  dashed?: boolean
  pinned?: boolean
}

const NODE_DEFS: NodeDef[] = [
  { id: 'kalshi_prism', label: 'Kalshi .prism', x: 5, y: 10, w: 96, h: 28 },
  { id: 'poly_prism', label: 'Polymarket .prism', x: 5, y: 56, w: 110, h: 28 },
  { id: 'custom_prism', label: 'Custom .prism', x: 5, y: 102, w: 96, h: 28, dashed: true },
  { id: 'registry', label: 'Prism Registry', x: 162, y: 56, w: 108, h: 28, pinned: true },
  { id: 'velocity', label: 'VelocityTracker', x: 326, y: 56, w: 120, h: 28 },
  { id: 'dedup', label: 'Deduplicator', x: 496, y: 56, w: 102, h: 28 },
  { id: 'sizer', label: 'Sizer', x: 648, y: 56, w: 54, h: 28 },
  { id: 'mcp', label: 'MCPClient', x: 752, y: 56, w: 88, h: 28 },
  { id: 'exit', label: 'ExitManager', x: 648, y: 152, w: 96, h: 28 },
]

function cx(node: NodeDef) { return node.x + node.w / 2 }
function cy(node: NodeDef) { return node.y + node.h / 2 }
function getNode(id: NodeId) { return NODE_DEFS.find((n) => n.id === id)! }

export default function ArchitectureDiagram() {
  const [hovered, setHovered] = useState<NodeId | null>(null)

  function isHighlighted(id: NodeId) {
    const node = getNode(id)
    if (node.pinned) return true
    if (!hovered) return false
    if (id === hovered) return true
    return UPSTREAM[hovered].includes(id)
  }

  function nodeColor(id: NodeId) {
    return isHighlighted(id) ? 'var(--neon)' : 'var(--text-primary)'
  }

  function nodeBorder(id: NodeId) {
    return isHighlighted(id) ? 'var(--neon)' : '#333333'
  }

  const registry = getNode('registry')
  const velocity = getNode('velocity')
  const dedup = getNode('dedup')
  const sizer = getNode('sizer')
  const mcp = getNode('mcp')
  const exit = getNode('exit')
  const kalshi = getNode('kalshi_prism')
  const poly = getNode('poly_prism')
  const custom = getNode('custom_prism')

  const lineColor = (a: NodeId, b: NodeId) =>
    isHighlighted(a) && isHighlighted(b) ? 'var(--neon)' : '#444444'

  return (
    <svg
      viewBox="0 0 860 210"
      width="100%"
      style={{ overflow: 'visible', display: 'block' }}
    >
      {/* Source → Registry arrows */}
      {[kalshi, poly, custom].map((src) => {
        const color = lineColor(src.id, 'registry')
        const x1 = src.x + src.w
        const y1 = cy(src)
        const x2 = registry.x
        const y2 = cy(registry)
        return (
          <g key={src.id}>
            <path
              d={`M ${x1} ${y1} C ${x1 + 30} ${y1}, ${x2 - 20} ${y2}, ${x2 - 6} ${y2}`}
              fill="none"
              stroke={color}
              strokeWidth="1"
              style={{ transition: 'stroke 150ms' }}
            />
            <polygon
              points={`${x2 - 6},${y2 - 4} ${x2 - 6},${y2 + 4} ${x2},${y2}`}
              fill={color}
              style={{ transition: 'fill 150ms' }}
            />
          </g>
        )
      })}

      {/* Horizontal pipeline arrows */}
      {[
        [registry, velocity],
        [velocity, dedup],
        [dedup, sizer],
        [sizer, mcp],
      ].map(([a, b]) => {
        const color = lineColor(a.id, b.id)
        const x2 = b.x
        const y = cy(a)
        return (
          <g key={`${a.id}_${b.id}`}>
            <line
              x1={a.x + a.w}
              y1={y}
              x2={x2 - 6}
              y2={y}
              stroke={color}
              strokeWidth="1"
              style={{ transition: 'stroke 150ms' }}
            />
            <polygon
              points={`${x2 - 6},${y - 4} ${x2 - 6},${y + 4} ${x2},${y}`}
              fill={color}
              style={{ transition: 'fill 150ms' }}
            />
          </g>
        )
      })}

      {/* MCP → ExitManager vertical */}
      {(() => {
        const color = lineColor('mcp', 'exit')
        const x = cx(mcp)
        const y1 = mcp.y + mcp.h
        const y2 = exit.y
        return (
          <g>
            <line
              x1={x} y1={y1}
              x2={x} y2={y2 - 6}
              stroke={color}
              strokeWidth="1"
              style={{ transition: 'stroke 150ms' }}
            />
            <polygon
              points={`${x - 4},${y2 - 6} ${x + 4},${y2 - 6} ${x},${y2}`}
              fill={color}
              style={{ transition: 'fill 150ms' }}
            />
          </g>
        )
      })()}

      {/* Nodes */}
      {NODE_DEFS.map((node) => (
        <g
          key={node.id}
          onMouseEnter={() => !node.pinned && setHovered(node.id)}
          onMouseLeave={() => setHovered(null)}
          style={{ cursor: node.pinned ? 'default' : 'default' }}
        >
          <rect
            x={node.x}
            y={node.y}
            width={node.w}
            height={node.h}
            rx="2"
            fill={node.pinned ? 'rgba(0,255,163,0.06)' : 'var(--surface-elevated)'}
            stroke={nodeBorder(node.id)}
            strokeWidth={node.pinned ? '1.5' : '1'}
            strokeDasharray={node.dashed ? '4 3' : undefined}
            style={{ transition: 'stroke 150ms' }}
          />
          <text
            x={cx(node)}
            y={cy(node) + 1}
            textAnchor="middle"
            dominantBaseline="middle"
            fill={nodeColor(node.id)}
            fontSize="11"
            fontFamily="var(--font-mono)"
            style={{ transition: 'fill 150ms', userSelect: 'none' }}
          >
            {node.label}
          </text>
        </g>
      ))}
    </svg>
  )
}
