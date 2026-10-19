import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Table, Button, Space, Checkbox, Tag, message, Segmented } from 'antd'
import { api } from '../api'
import DocViewer from '../components/DocViewer'
import CriteriaEditor from '../components/CriteriaEditor'

export default function EvalResult() {
  const { id } = useParams()
  const nav = useNavigate()
  const [task, setTask] = useState<any>(null)
  const [compare, setCompare] = useState<any>(null)
  const [docIdx, setDocIdx] = useState(0)
  const [showAnno, setShowAnno] = useState(true)
  const [showPred, setShowPred] = useState(true)
  const [valueMode, setValueMode] = useState('归一化后值')
  const [editorOpen, setEditorOpen] = useState(false)
  const [highlightField, setHighlightField] = useState<string | null>(null)
  const [scale, setScale] = useState(1)
  const [predBoxes, setPredBoxes] = useState<any[]>([])
  const tableScrollRef = useRef<HTMLDivElement>(null)

  const loadCompare = () => api.getCompare(Number(id)).then(setCompare)
  useEffect(() => {
    api.getEvalTask(Number(id)).then(setTask)
    loadCompare()
    // eslint-disable-next-line
  }, [id])

  const docs = compare?.documents || []
  const curDoc = docs[docIdx]
  useEffect(() => { setHighlightField(null) }, [docIdx])
  useEffect(() => {
    if (curDoc?.doc_key) {
      api.predictionBoxes(Number(id), curDoc.doc_key).then(d => setPredBoxes(d.boxes || [])).catch(() => setPredBoxes([]))
    } else {
      setPredBoxes([])
    }
    // eslint-disable-next-line
  }, [id, curDoc?.doc_key])

  async function override(field: string, verdict: string) {
    await api.setOverride({ task_id: Number(id), doc_key: curDoc.doc_key, field, verdict })
    message.success('已标记，点击“重新计算”更新指标')
    loadCompare()
  }
  async function clearOv(field: string) {
    await api.clearOverride(Number(id), curDoc.doc_key, field)
    loadCompare()
  }
  async function recompute() {
    await api.recompute(Number(id))
    message.success('已重新计算人工复核后指标')
    loadCompare()
  }

  if (!compare) return null

  // 组装分组行：单个字段段 + 组合字段段（母字段标题 + 子字段）
  const rawRows: any[] = curDoc?.rows || []
  const singles = rawRows.filter(r => !r.parent)
  const combos = rawRows.filter(r => r.parent)
  const hasCombo = combos.length > 0
  const parentOrder: string[] = []
  const byParent: Record<string, any[]> = {}
  for (const r of combos) {
    if (!byParent[r.parent]) { byParent[r.parent] = []; parentOrder.push(r.parent) }
    byParent[r.parent].push(r)
  }
  let tableData: any[]
  if (hasCombo) {
    tableData = []
    if (singles.length) tableData.push({ _type: 'section', _key: 'sec-single', title: '单个字段' })
    for (const r of singles) tableData.push({ ...r, _key: `f-${r.field}` })
    tableData.push({ _type: 'section', _key: 'sec-combo', title: '组合字段' })
    for (const p of parentOrder) {
      tableData.push({ _type: 'parent', _key: `p-${p}`, title: p })
      let lastGroup: any = undefined
      for (const r of byParent[p]) {
        if (r.group !== undefined && r.group !== lastGroup) {
          lastGroup = r.group
          tableData.push({ _type: 'group', _key: `g-${p}-${r.group}`, title: `组 ${r.group}` })
        }
        tableData.push({ ...r, _key: `f-${p}-${r.group ?? 0}-${r.field}`, _sub: true })
      }
    }
  } else {
    tableData = rawRows.map(r => ({ ...r, _key: `f-${r.field}` }))
  }
  const isTitle = (r: any) => r._type === 'section' || r._type === 'parent' || r._type === 'group'
  const annoVal = (r: any) => valueMode === '归一化后值' ? (r.annotation_norm ?? r.annotation) : r.annotation
  const predVal = (r: any) => valueMode === '归一化后值' ? (r.prediction_norm ?? r.prediction) : r.prediction
  // 字段→颜色（取自任务 field_defs，经 compare 返回），用于图片框与右表一致配色
  const fieldColors: Record<string, string> = {}
  ;(compare?.documents || []).forEach((d: any) => (d.rows || []).forEach((r: any) => {
    if (r.color) fieldColors[r.field] = r.color
  }))

  return (
    <Card title={<Space><Button onClick={() => nav(`/tasks/${id}`)}>← 返回</Button>查看评测结果</Space>}
      extra={
        <Space>
          <Button onClick={() => setEditorOpen(true)}>修改（自定义评测标准）</Button>
          <Button type="primary" onClick={recompute}>重新计算</Button>
        </Space>
      }>
      <div style={{ display: 'flex', gap: 16, height: 'calc(100vh - 180px)', overflow: 'hidden' }}>
        {/* 左盒子：图片区域固定宽度 65%，文档区内部滚动 */}
        <div style={{ flex: '0 0 65%', minWidth: 0, display: 'flex', flexDirection: 'column' }}>
          <Space style={{ marginBottom: 8 }} wrap>
            <Checkbox checked={showAnno} onChange={e => setShowAnno(e.target.checked)}>标注信息</Checkbox>
            <Checkbox checked={showPred} onChange={e => setShowPred(e.target.checked)}>预测结果</Checkbox>
            <Space.Compact>
              <Button size="small" onClick={() => setScale(s => Math.max(0.5, +(s - 0.25).toFixed(2)))}>−</Button>
              <Button size="small" style={{ pointerEvents: 'none' }}>{Math.round(scale * 100)}%</Button>
              <Button size="small" onClick={() => setScale(s => Math.min(3, +(s + 0.25).toFixed(2)))}>＋</Button>
            </Space.Compact>
            <span style={{ color: '#999' }}>点击右侧字段可定位到对应标注框</span>
          </Space>
          <div style={{ flex: 1, minHeight: 0, overflow: 'auto', border: '1px solid #eee' }}>
            {curDoc && <DocViewer key={curDoc.doc_key} docKey={curDoc.doc_key} allPages
              showAnnotations={showAnno} highlightField={highlightField} scale={scale}
              predBoxes={predBoxes} showPrediction={showPred} datasetId={task?.dataset_id}
              fieldColors={fieldColors} />}
          </div>
          <div style={{ marginTop: 8 }}>
            <Space wrap>
              <Button size="small" disabled={docIdx <= 0}
                onClick={() => setDocIdx(i => Math.max(0, i - 1))}>← 上一个</Button>
              <span>文件 {docs.length ? docIdx + 1 : 0} / {docs.length}</span>
              <Button size="small" disabled={docIdx >= docs.length - 1}
                onClick={() => setDocIdx(i => Math.min(docs.length - 1, i + 1))}>下一个 →</Button>
              <span style={{ color: '#999', marginLeft: 8 }}>{curDoc?.doc_key}</span>
              <Button size="small" type="primary" ghost
                disabled={!task?.dataset_id || !curDoc?.doc_key}
                onClick={() => nav(`/datasets/${task.dataset_id}/annotate?doc=${encodeURIComponent(curDoc.doc_key)}&from=result&task=${id}`)}>
                修改标注</Button>
              <span style={{ color: '#999', fontSize: 12 }}>（修改标注后，指标需重新评测才会更新）</span>
            </Space>
          </div>
        </div>
        {/* 右盒子：对比表，占剩余宽度，内部纵向滚动 */}
        <div style={{ flex: '1 1 0', minWidth: 0, display: 'flex', flexDirection: 'column' }}>
          <Space style={{ marginBottom: 8 }}>
            <Segmented value={valueMode} onChange={v => setValueMode(v as string)}
              options={['归一化后值', '原始值']} />
            <span style={{ color: '#999', fontSize: 12 }}>
              归一化后值 = 按匹配规则(去标点/大小写/日期等)处理后用于判定的值；原始值 = 抽取原文
            </span>
          </Space>
          <div ref={tableScrollRef} style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
            <Table rowKey="_key" size="small" pagination={false} dataSource={tableData}
              tableLayout="fixed"
              sticky={{ offsetHeader: 0, getContainer: () => tableScrollRef.current || window }}
              rowClassName={(r: any) => (!isTitle(r) && r.field === highlightField) ? 'row-active'
                : (r._type === 'section' ? 'group-section' : r._type === 'parent' ? 'group-parent'
                  : r._type === 'group' ? 'group-row' : '')}
              onRow={(r: any) => isTitle(r) ? {}
                : ({ onClick: () => setHighlightField(r.field), style: { cursor: 'pointer' } })}
              columns={[
                { title: '字段', dataIndex: 'field', width: 96,
                  onCell: (r: any) => isTitle(r) ? { colSpan: 5 } : {},
                  render: (v, r: any) => {
                    if (r._type === 'section') return <b>{r.title}</b>
                    if (r._type === 'parent') return <span style={{ fontWeight: 600 }}>▸ {r.title}</span>
                    if (r._type === 'group') return <span style={{ fontWeight: 500, color: '#2468f2', paddingLeft: 14 }}>{r.title}</span>
                    return (
                      <span style={{ whiteSpace: 'normal', wordBreak: 'break-word', paddingLeft: r._sub ? 28 : 0 }}>
                        <Tag color={r.color}>{' '}</Tag>{v}</span>
                    )
                  } },
                { title: '标注',
                  onCell: (r: any) => isTitle(r) ? { colSpan: 0 }
                    : ({ style: { whiteSpace: 'normal', wordBreak: 'break-word' } }),
                  render: (_: any, r: any) => annoVal(r) },
                {
                  title: '预测',
                  onCell: (r: any) => isTitle(r) ? { colSpan: 0 }
                    : ({ className: r.hit ? '' : 'mismatch-cell',
                        style: { whiteSpace: 'normal', wordBreak: 'break-word' } }),
                  render: (_: any, r: any) => predVal(r),
                },
                {
                  title: '判定', width: 90,
                  onCell: (r: any) => isTitle(r) ? { colSpan: 0 } : {},
                  render: (_, r: any) => (
                    r.override ? <Tag color={r.override === 'success' ? 'green' : 'red'}>
                      {r.override === 'success' ? '人工:一致' : '人工:不一致'}</Tag>
                      : (r.hit ? <Tag color="green">一致</Tag> : <Tag color="red">不一致</Tag>)
                  )
                },
                {
                  title: '人工复核', width: 70,
                  onCell: (r: any) => isTitle(r) ? { colSpan: 0 } : {},
                  render: (_, r: any) => (
                    <Space direction="vertical" size={2}>
                      <Button size="small" onClick={(e) => { e.stopPropagation(); override(r.field, 'success') }}>一致</Button>
                      <Button size="small" danger onClick={(e) => { e.stopPropagation(); override(r.field, 'fail') }}>不一致</Button>
                      {r.override && <Button size="small" type="link" onClick={(e) => { e.stopPropagation(); clearOv(r.field) }}>撤销</Button>}
                    </Space>
                  )
                },
              ]} />
          </div>
        </div>
      </div>
      <CriteriaEditor open={editorOpen} taskId={Number(id)} fields={compare.fields}
        onClose={() => setEditorOpen(false)} onSaved={recompute} />
    </Card>
  )
}
