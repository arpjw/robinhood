'use client'

import { useState } from 'react'

type NodeId =
  | 'kalshi'
  | 'velocity'
  | 'dedup'
  | 'sizer'
  | 'mcp'
  | 'robinhood'
  | 'polymarket'
  | 'exit'

const UPSTREAM: Record<NodeId, NodeId[]> = {
  kalshi: [],
  polymarket: [],
  velocity: ['kalshi'],
  dedup: ['kalshi', 'velocity'],
  sizer: ['kalshi', 'velocity', 'dedup'],
  mcp: ['kalshi', 'velocity', 'dedup', 'sizer'],
  robinhood: ['kalshi', 'velocity', 'dedup', 'sizer', 'mcp'],
  exit: ['polymarket', 'mcp', 'kalshi', 'velocity', 'dedup', 'sizer'],
}

type ArrowId =
  | 'kw_vt'
  | 'vt_d'
  | 'd_s'
  | 's_mc'
  | 'mc_r'
  | 'mc_em'
  | 'pm_em'

const ARROW_TARGET: Record<ArrowId, NodeId> = {
  kw_vt: 'velocity',
  vt_d: 'dedup',
  d_s: 'sizer',
  s_mc: 'mcp',
  mc_r: 'robinhood',
  mc_em: 'exit',
  pm_em: 'exit',
}

const NODE_DEFS: { id: NodeId; label: string; x: number; y: number; w: number; h: number }[] = [
  { id: 'kalshi', label: 'Kalshi WS', x: 10, y: 37, w: 88, h: 32 },
  { id: 'velocity', label: 'VelocityTracker', x: 130, y: 37, w: 128, h: 32 },
  { id: 'dedup', label: 'Deduplicator', x: 300, y: 37, w: 108, h: 32 },
  { id: 'sizer', label: 'Sizer', x: 450, y: 37, w: 60, h: 32 },
  { id: 'mcp', label: 'MCPClient', x: 552, y: 37, w: 92, h: 32 },
  { id: 'robinhood', label: 'Robinhood', x: 686, y: 37, w: 90, h: 32 },
  { id: 'polymarket', label: 'Polymarket WS', x: 10, y: 137, w: 118, h: 32 },
  { id: 'exit', label: 'ExitManager', x: 552, y: 137, w: 100, h: 32 },
]

function cx(node: (typeof NODE_DEFS)[0]) {
  return node.x + node.w / 2
}
function cy(node: (typeof NODE_DEFS)[0]) {
  return node.y + node.h / 2
}

function getNode(id: NodeId) {
  return NODE_DEFS.find((n) => n.id === id)!
}

export default function ArchitectureDiagram() {
  const [hovered, setHovered] = useState<NodeId | null>(null)

  function isHighlighted(id: NodeId) {
    if (!hovered) return false
    if (id === hovered) return true
    return UPSTREAM[hovered].includes(id)
  }

  function isArrowHighlighted(arrowId: ArrowId) {
    if (!hovered) return false
    const target = ARROW_TARGET[arrowId]
    return target === hovered || UPSTREAM[hovered].includes(target)
  }

  const nodeColor = (id: NodeId) =>
    isHighlighted(id) ? 'var(--neon)' : 'var(--text-primary)'

  const nodeBorder = (id: NodeId) =>
    isHighlighted(id) ? 'var(--neon)' : '#333333'

  const arrowColor = (arrowId: ArrowId) =>
    isArrowHighlighted(arrowId) ? 'var(--neon)' : '#444444'

  const arrowHead = (arrowId: ArrowId, points: string) => (
    <polygon
      points={points}
      fill={arrowColor(arrowId)}
      style={{ transition: 'fill 150ms' }}
    />
  )

  return (
    <svg
      viewBox="0 0 800 200"
      width="100%"
      style={{ overflow: 'visible', display: 'block' }}
    >
      {NODE_DEFS.map((node) => (
        <g
          key={node.id}
          onMouseEnter={() => setHovered(node.id)}
          onMouseLeave={() => setHovered(null)}
          style={{ cursor: 'default' }}
        >
          <rect
            x={node.x}
            y={node.y}
            width={node.w}
            height={node.h}
            rx="2"
            fill="var(--surface-elevated)"
            stroke={nodeBorder(node.id)}
            strokeWidth="1"
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

      {(() => {
        const kalshi = getNode('kalshi')
        const velocity = getNode('velocity')
        const dedup = getNode('dedup')
        const sizer = getNode('sizer')
        const mcp = getNode('mcp')
        const robinhood = getNode('robinhood')
        const polymarket = getNode('polymarket')
        const exit = getNode('exit')

        const arrows: {
          id: ArrowId
          x1: number
          y1: number
          x2: number
          y2: number
          vertical?: boolean
        }[] = [
          {
            id: 'kw_vt',
            x1: kalshi.x + kalshi.w,
            y1: cy(kalshi),
            x2: velocity.x,
            y2: cy(velocity),
          },
          {
            id: 'vt_d',
            x1: velocity.x + velocity.w,
            y1: cy(velocity),
            x2: dedup.x,
            y2: cy(dedup),
          },
          {
            id: 'd_s',
            x1: dedup.x + dedup.w,
            y1: cy(dedup),
            x2: sizer.x,
            y2: cy(sizer),
          },
          {
            id: 's_mc',
            x1: sizer.x + sizer.w,
            y1: cy(sizer),
            x2: mcp.x,
            y2: cy(mcp),
          },
          {
            id: 'mc_r',
            x1: mcp.x + mcp.w,
            y1: cy(mcp),
            x2: robinhood.x,
            y2: cy(robinhood),
          },
          {
            id: 'mc_em',
            x1: cx(mcp),
            y1: mcp.y + mcp.h,
            x2: cx(exit),
            y2: exit.y,
            vertical: true,
          },
          {
            id: 'pm_em',
            x1: polymarket.x + polymarket.w,
            y1: cy(polymarket),
            x2: exit.x,
            y2: cy(exit),
          },
        ]

        return arrows.map((a) => {
          const color = arrowColor(a.id)
          if (a.vertical) {
            const arrowX = a.x2
            const arrowY2 = a.y2
            return (
              <g key={a.id}>
                <line
                  x1={a.x1}
                  y1={a.y1}
                  x2={a.x2}
                  y2={arrowY2 - 6}
                  stroke={color}
                  strokeWidth="1"
                  style={{ transition: 'stroke 150ms' }}
                />
                <polygon
                  points={`${arrowX - 4},${arrowY2 - 6} ${arrowX + 4},${arrowY2 - 6} ${arrowX},${arrowY2}`}
                  fill={color}
                  style={{ transition: 'fill 150ms' }}
                />
              </g>
            )
          }
          const arrowX2 = a.x2
          const arrowY = a.y2
          return (
            <g key={a.id}>
              <line
                x1={a.x1}
                y1={a.y1}
                x2={arrowX2 - 6}
                y2={arrowY}
                stroke={color}
                strokeWidth="1"
                style={{ transition: 'stroke 150ms' }}
              />
              {arrowHead(
                a.id,
                `${arrowX2 - 6},${arrowY - 4} ${arrowX2 - 6},${arrowY + 4} ${arrowX2},${arrowY}`
              )}
            </g>
          )
        })
      })()}
    </svg>
  )
}
