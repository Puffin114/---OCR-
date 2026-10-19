import { useEffect, useRef, useState } from 'react'
import { api } from '../api'

interface Box { field: string; color: string; text: string; page: number; box: number[] }
interface PageMeta { page: number; width: number; height: number }

interface Props {
  docKey: string
  pageNum?: number
  zoom?: number
  showAnnotations?: boolean
  selectable?: boolean
  onSelect?: (box: number[], page: number) => void
  highlightField?: string | null
  allPages?: boolean
  reloadToken?: number
  scale?: number
  hiddenFields?: string[]
  predBoxes?: Box[]
  showPrediction?: boolean
  datasetId?: number
  fieldColors?: Record<string, string>
}

export default function DocViewer({ docKey, pageNum = 1, zoom = 2, showAnnotations = true,
  selectable = false, onSelect, highlightField = null, allPages = false, reloadToken = 0,
  scale = 1, hiddenFields = [], predBoxes = [], showPrediction = false, datasetId,
  fieldColors }: Props) {
  const [boxes, setBoxes] = useState<Box[]>([])
  const [pages, setPages] = useState<PageMeta[]>([])
  const [drag, setDrag] = useState<{ x: number; y: number } | null>(null)
  const [dragPage, setDragPage] = useState<number | null>(null)
  const [rect, setRect] = useState<number[] | null>(null)
  const pageRefs = useRef<Record<number, HTMLDivElement | null>>({})
  const highlightRef = useRef<HTMLDivElement>(null)

  // 页尺寸（PDF 点坐标），用于百分比定位
  useEffect(() => {
    if (!docKey) { setPages([]); return }
    api.docMeta(docKey, datasetId).then(m => setPages(m.pages || [])).catch(() => setPages([]))
  }, [docKey, datasetId])

  // 标注框（reloadToken 变化时刷新）
  useEffect(() => {
    if (!docKey) { setBoxes([]); return }
    api.annotationBoxes(docKey, datasetId).then(d => setBoxes(d.boxes || [])).catch(() => setBoxes([]))
  }, [docKey, reloadToken, datasetId])

  // 高亮字段 → 滚动定位
  useEffect(() => {
    if (highlightField && highlightRef.current) {
      highlightRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [highlightField, boxes, pages])

  const pageDim = (p: number) => pages.find(x => x.page === p)
  const renderPages = allPages
    ? (pages.length ? pages.map(p => p.page) : [])
    : [pageNum]

  // 本次需要滚动定位的首个高亮框 key（page-boxIndex）；无标注框则落到预测框
  let firstHL: string | null = null
  if (highlightField) {
    for (const p of renderPages) {
      const idx = boxes.findIndex(b => b.page === p && b.field === highlightField)
      if (idx >= 0) { firstHL = `${p}-${idx}`; break }
    }
    if (!firstHL && showPrediction) {
      for (const p of renderPages) {
        const idx = predBoxes.findIndex(b => b.page === p && b.field === highlightField)
        if (idx >= 0) { firstHL = `pred-${p}-${idx}`; break }
      }
    }
  }

  function local(e: React.MouseEvent, pno: number) {
    const r = pageRefs.current[pno]!.getBoundingClientRect()
    return { x: e.clientX - r.left, y: e.clientY - r.top }
  }
  function onDown(e: React.MouseEvent, pno: number) {
    if (!selectable) return
    const p = local(e, pno); setDrag({ x: p.x, y: p.y }); setDragPage(pno); setRect([p.x, p.y, 0, 0])
  }
  function onMove(e: React.MouseEvent) {
    if (!selectable || !drag || dragPage == null) return
    const p = local(e, dragPage)
    setRect([Math.min(drag.x, p.x), Math.min(drag.y, p.y), Math.abs(p.x - drag.x), Math.abs(p.y - drag.y)])
  }
  function onUp() {
    if (!selectable || !drag || dragPage == null || !rect) { setDrag(null); return }
    const pno = dragPage
    const dim = pageDim(pno)
    const r = pageRefs.current[pno]?.getBoundingClientRect()
    if (rect[2] > 4 && rect[3] > 4 && onSelect && dim && r && r.width && r.height) {
      const sx = dim.width / r.width, sy = dim.height / r.height
      onSelect([rect[0] * sx, rect[1] * sy, rect[2] * sx, rect[3] * sy], pno)
    }
    setDrag(null); setDragPage(null); setRect(null)
  }

  function renderPage(pno: number) {
    const dim = pageDim(pno)
    const hidden = new Set(hiddenFields)
    const pageBoxes = showAnnotations && dim
      ? boxes.filter(b => b.page === pno && !hidden.has(b.field)) : []
    const predPageBoxes = showPrediction && dim
      ? predBoxes.filter(b => b.page === pno && !hidden.has(b.field)) : []
    return (
      <div className="viewer-wrap" key={pno}
        ref={el => { pageRefs.current[pno] = el }}
        onMouseDown={selectable ? (e) => onDown(e, pno) : undefined}
        onMouseMove={selectable ? onMove : undefined}
        onMouseUp={selectable ? onUp : undefined}
        style={{ cursor: selectable ? 'crosshair' : 'default', marginBottom: allPages ? 12 : 0,
          width: `${scale * 100}%` }}>
        <img src={api.pageUrl(docKey, pno, zoom, datasetId)} alt={`${docKey}-${pno}`} draggable={false} loading="lazy" />
        {pageBoxes.map((b) => {
          const key = `${pno}-${boxes.indexOf(b)}`
          const hit = highlightField === b.field
          const color = fieldColors?.[b.field] || b.color || '#2468f2'
          const left = b.box[0] / dim!.width * 100
          const top = b.box[1] / dim!.height * 100
          const w = b.box[2] / dim!.width * 100
          const h = b.box[3] / dim!.height * 100
          return (
            <div key={key}>
              {hit && (
                <div className="anno-lead" style={{
                  left: 0, top: `calc(${top}% + ${h / 2}%)`, width: `${left}%`, borderColor: color,
                }} />
              )}
              <div className={`anno-box${hit ? ' anno-box-active' : ''}`} ref={key === firstHL ? highlightRef : undefined}
                style={{
                  left: `${left}%`, top: `${top}%`, width: `${w}%`, height: `${h}%`,
                  borderColor: color, borderWidth: hit ? 3 : 2,
                  background: hit ? `${color}59` : 'transparent',
                  ...(hit ? { ['--hl' as any]: color } : {}),
                }} />
              <div className="anno-label" style={{
                left: `${left}%`, top: `${top}%`, transform: 'translateY(-100%)',
                background: color,
              }}>{b.field}</div>
            </div>
          )
        })}
        {predPageBoxes.map((b) => {
          const key = `pred-${pno}-${predBoxes.indexOf(b)}`
          const hit = highlightField === b.field
          const color = fieldColors?.[b.field] || b.color || '#2468f2'
          const left = b.box[0] / dim!.width * 100
          const top = b.box[1] / dim!.height * 100
          const w = b.box[2] / dim!.width * 100
          const h = b.box[3] / dim!.height * 100
          return (
            <div key={key}>
              <div className={`anno-box${hit ? ' anno-box-active' : ''}`} ref={key === firstHL ? highlightRef : undefined}
                style={{
                  left: `${left}%`, top: `${top}%`, width: `${w}%`, height: `${h}%`,
                  borderColor: color, borderStyle: 'dashed', borderWidth: hit ? 3 : 2,
                  background: hit ? `${color}59` : 'transparent',
                  ...(hit ? { ['--hl' as any]: color } : {}),
                }} />
              <div className="anno-label" style={{
                left: `${left}%`, top: `${top}%`, transform: 'translateY(-100%)',
                background: color, opacity: 0.85,
              }}>{b.field}·预测</div>
            </div>
          )
        })}
        {dragPage === pno && rect && (
          <div className="sel-rect" style={{ left: rect[0], top: rect[1], width: rect[2], height: rect[3] }} />
        )}
      </div>
    )
  }

  return <div>{renderPages.map(renderPage)}</div>
}
