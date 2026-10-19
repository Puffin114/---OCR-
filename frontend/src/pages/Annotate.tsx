import { useEffect, useState } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { Select, Input, Button, Space, message, Tag, Modal } from 'antd'
import { api } from '../api'
import DocViewer from '../components/DocViewer'

function Eye({ open, color, onClick }: { open: boolean; color?: string; onClick: () => void }) {
  return (
    <span onClick={(e) => { e.stopPropagation(); onClick() }}
      title={open ? '隐藏该字段的框' : '显示该字段的框'}
      style={{ cursor: 'pointer', color: color || '#888', display: 'inline-flex', alignItems: 'center' }}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z" />
        <circle cx="12" cy="12" r="3" />
        {!open && <line x1="3" y1="3" x2="21" y2="21" stroke="currentColor" />}
      </svg>
    </span>
  )
}

export default function Annotate() {
  const { id } = useParams()
  const nav = useNavigate()
  const [searchParams] = useSearchParams()
  const [detail, setDetail] = useState<any>(null)
  const [docKey, setDocKey] = useState<string>('')
  const [activeField, setActiveField] = useState<any>(null)
  const [values, setValues] = useState<Record<string, string>>({})
  const [combo, setCombo] = useState<Record<string, Array<Record<string, string>>>>({})
  const [reloadToken, setReloadToken] = useState(0)
  const [scale, setScale] = useState(1)
  const [hidden, setHidden] = useState<string[]>([])

  useEffect(() => {
    api.getDataset(Number(id)).then(d => {
      setDetail(d)
      const wanted = searchParams.get('doc')
      const match = wanted && d.documents.find((x: any) => x.key === wanted)
      const first = match || d.documents.find((x: any) => x.complete) || d.documents[0]
      if (first) setDocKey(first.key)
    })
    // eslint-disable-next-line
  }, [id])

  const loadGrouped = () => {
    if (!docKey) return
    api.annotationGrouped(docKey, Number(id)).then(d => {
      setValues(d.singles || {})
      setCombo(d.groups || {})
    }).catch(() => { setValues({}); setCombo({}) })
  }
  useEffect(() => {
    if (!docKey) return
    setActiveField(null)
    loadGrouped()
    // eslint-disable-next-line
  }, [docKey])

  async function onSelect(box: number[], page: number) {
    if (!activeField) { message.warning('请先在右侧点击选择一个字段'); return }
    const af = activeField
    const field = af.label_name
    let text = ''
    try {
      const r = await api.recognize(docKey, page, box, Number(id))
      text = r.text || ''
      if (text) message.success(`已识别：${text}`)
      else message.info('识别为空，可在右侧手动输入后保存')
    } catch (e: any) {
      message.warning(`识别失败：${e?.response?.data?.detail || '可手动输入后保存'}`)
    }
    const isCombo = !!af.parent
    const prev = isCombo ? (combo[af.parent]?.[af.group]?.[field] || '') : (values[field] || '')
    const finalVal = text || prev || ''
    if (isCombo) {
      setCombo(c => {
        const list = (c[af.parent] || []).map(g => ({ ...g }))
        while (list.length <= af.group) list.push({})
        list[af.group][field] = finalVal
        return { ...c, [af.parent]: list }
      })
    } else {
      setValues(v => ({ ...v, [field]: finalVal }))
    }
    await api.saveAnnotation({
      doc_key: docKey, field, label_id: af.label_id,
      value: finalVal, page_num: page, box, dataset_id: Number(id),
      ...(isCombo ? { parent_field: af.parent, parent_label_id: af.parentLabelId, group_index: af.group } : {}),
    })
    setReloadToken(x => x + 1)
  }

  function toggleHidden(name: string) {
    setHidden(h => h.includes(name) ? h.filter(x => x !== name) : [...h, name])
  }

  if (!detail) return null
  const documents: any[] = detail.documents || []
  const labels: any[] = detail.labels || []
  const docIdx = documents.findIndex((d: any) => d.key === docKey)
  const gotoDoc = (i: number) => { if (i >= 0 && i < documents.length) setDocKey(documents[i].key) }
  const topLevel = labels.filter(l => !l.parent_id)
  const childrenOf = (lid: string) => labels.filter(l => l.parent_id === lid)

  async function saveField(lb: any) {
    await api.saveAnnotation({
      doc_key: docKey, field: lb.label_name, label_id: lb.label_id,
      value: values[lb.label_name] || '', page_num: 1, box: null, dataset_id: Number(id),
    })
    setReloadToken(x => x + 1)
    message.success('已保存')
  }

  async function saveComboCell(parent: any, sub: any, g: number) {
    await api.saveAnnotation({
      doc_key: docKey, field: sub.label_name, label_id: sub.label_id,
      value: combo[parent.label_name]?.[g]?.[sub.label_name] || '', page_num: 1, box: null,
      dataset_id: Number(id), parent_field: parent.label_name,
      parent_label_id: parent.label_id, group_index: g,
    })
    setReloadToken(x => x + 1)
    message.success('已保存')
  }

  function addGroup(parent: any) {
    setCombo(c => ({ ...c, [parent.label_name]: [...(c[parent.label_name] || []), {}] }))
  }

  async function removeGroup(parent: any, g: number) {
    await api.deleteGroup(docKey, parent.label_name, g, Number(id))
    setReloadToken(x => x + 1)
    loadGrouped()
    message.success('已删除该组')
  }

  function deleteCurrentDoc() {
    if (!docKey) return
    Modal.confirm({
      title: '删除当前文件',
      content: `确定从数据集删除「${docKey}」吗？该文件及其标注将被永久删除，不可恢复。`,
      okText: '删除', okButtonProps: { danger: true }, cancelText: '取消',
      onOk: async () => {
        await api.deleteDocument(Number(id), docKey)
        const d = await api.getDataset(Number(id))
        setDetail(d)
        const docs: any[] = d.documents || []
        if (docs.length) {
          const ni = Math.min(docIdx, docs.length - 1)
          setDocKey(docs[Math.max(0, ni)].key)
          message.success('已删除')
        } else {
          message.info('数据集已无文件'); nav('/datasets')
        }
      },
    })
  }

  // 单字段卡片
  const fieldCard = (lb: any, indent = false) => {
    const active = activeField?.label_id === lb.label_id && activeField?.group === undefined
    const isHidden = hidden.includes(lb.label_name)
    return (
      <div key={lb.id} onClick={() => setActiveField({ ...lb })}
        style={{
          border: `1px solid ${active ? lb.label_color : '#eee'}`,
          borderLeft: `4px solid ${lb.label_color}`, borderRadius: 6, padding: 8,
          cursor: 'pointer', marginLeft: indent ? 14 : 0,
          background: active ? '#f0f6ff' : '#fff',
        }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <b>{lb.label_name}</b>
          <Space size={6}>
            {active && <Tag color="blue">标注中</Tag>}
            <Eye open={!isHidden} color={lb.label_color} onClick={() => toggleHidden(lb.label_name)} />
          </Space>
        </div>
        <Input.TextArea style={{ marginTop: 6 }} autoSize value={values[lb.label_name] || ''}
          onChange={e => setValues(v => ({ ...v, [lb.label_name]: e.target.value }))}
          onFocus={() => setActiveField({ ...lb })}
          onClick={e => { e.stopPropagation(); setActiveField({ ...lb }) }} />
        <Button size="small" style={{ marginTop: 6 }} onClick={(e) => { e.stopPropagation(); saveField(lb) }}>保存</Button>
      </div>
    )
  }

  // 组合子字段某组的单元格
  const comboCell = (parent: any, sub: any, g: number) => {
    const active = activeField?.label_id === sub.label_id && activeField?.group === g
    const val = combo[parent.label_name]?.[g]?.[sub.label_name] || ''
    const select = () => setActiveField({ ...sub, parent: parent.label_name, parentLabelId: parent.label_id, group: g })
    return (
      <div key={`${sub.id}-${g}`} onClick={select}
        style={{
          border: `1px solid ${active ? sub.label_color : '#eee'}`,
          borderLeft: `4px solid ${sub.label_color}`, borderRadius: 6, padding: 8,
          cursor: 'pointer', background: active ? '#f0f6ff' : '#fff',
        }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>{sub.label_name}</span>
          {active && <Tag color="blue">标注中</Tag>}
        </div>
        <Input.TextArea style={{ marginTop: 6 }} autoSize value={val}
          onChange={e => setCombo(c => {
            const list = (c[parent.label_name] || []).map(x => ({ ...x }))
            while (list.length <= g) list.push({})
            list[g][sub.label_name] = e.target.value
            return { ...c, [parent.label_name]: list }
          })}
          onFocus={select}
          onClick={e => { e.stopPropagation(); select() }} />
        <Button size="small" style={{ marginTop: 6 }}
          onClick={(e) => { e.stopPropagation(); saveComboCell(parent, sub, g) }}>保存</Button>
      </div>
    )
  }

  const groupHeader = (lb: any) => {
    const kids = childrenOf(lb.label_id)
    const kidNames = kids.map(k => k.label_name)
    const allHidden = kidNames.length > 0 && kidNames.every(n => hidden.includes(n))
    const toggleGroup = () => {
      setHidden(h => allHidden ? h.filter(x => !kidNames.includes(x)) : Array.from(new Set([...h, ...kidNames])))
    }
    const groups = combo[lb.label_name] || []
    const nGroups = Math.max(groups.length, 1)
    return (
      <div key={lb.id}>
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          borderLeft: `4px solid ${lb.label_color}`, background: '#fafafa',
          padding: '6px 8px', borderRadius: 6, marginTop: 4,
        }}>
          <span><b>{lb.label_name}</b> <Tag>组合字段</Tag></span>
          <Eye open={!allHidden} color={lb.label_color} onClick={toggleGroup} />
        </div>
        {Array.from({ length: nGroups }).map((_, g) => (
          <div key={g} style={{ marginTop: 6, marginLeft: 8, borderLeft: '2px dashed #d6e2ff', paddingLeft: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <span style={{ color: '#2468f2', fontWeight: 500 }}>组 {g + 1}</span>
              <Button size="small" type="link" danger onClick={() => removeGroup(lb, g)}>删除该组</Button>
            </div>
            <Space direction="vertical" style={{ width: '100%' }}>
              {kids.map(k => comboCell(lb, k, g))}
            </Space>
          </div>
        ))}
        <Button size="small" type="dashed" block style={{ marginTop: 6 }}
          onClick={() => addGroup(lb)}>＋ 新增一组</Button>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', gap: 16, height: 'calc(100vh - 160px)', overflow: 'hidden' }}>
      {/* 左栏：文档查看 + 底部文件切换固定 */}
      <div style={{ flex: '1 1 auto', minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <Space style={{ marginBottom: 8 }} wrap>
          <Button size="small" onClick={() => {
            const from = searchParams.get('from')
            if (from === 'result' && searchParams.get('task')) nav(`/tasks/${searchParams.get('task')}/result`)
            else if (from === 'new-task') nav(`/datasets/${id}/new-task`)
            else nav('/datasets')
          }}>← 返回</Button>
          <Select style={{ width: 320 }} value={docKey} onChange={setDocKey}
            options={documents.map((d: any) => ({ value: d.key, label: d.key }))} />
          {activeField
            ? <Tag color="blue">当前标注字段：{activeField.label_name}</Tag>
            : <Tag>请先在右侧选择字段</Tag>}
          <Space.Compact>
            <Button size="small" onClick={() => setScale(s => Math.max(0.5, +(s - 0.25).toFixed(2)))}>−</Button>
            <Button size="small" style={{ pointerEvents: 'none' }}>{Math.round(scale * 100)}%</Button>
            <Button size="small" onClick={() => setScale(s => Math.min(3, +(s + 0.25).toFixed(2)))}>＋</Button>
          </Space.Compact>
          <Button size="small" danger disabled={!docKey} onClick={deleteCurrentDoc}>删除当前文件</Button>
        </Space>
        <div style={{ flex: 1, minHeight: 0, overflow: 'auto', border: '1px solid #eee' }}>
          {docKey && <DocViewer docKey={docKey} allPages selectable onSelect={onSelect}
            showAnnotations highlightField={activeField?.label_name} reloadToken={reloadToken}
            scale={scale} hiddenFields={hidden} datasetId={Number(id)} />}
        </div>
        <div style={{ marginTop: 8 }}>
          <Space>
            <Button size="small" disabled={docIdx <= 0} onClick={() => gotoDoc(docIdx - 1)}>← 上一个</Button>
            <span>文件 {documents.length ? docIdx + 1 : 0} / {documents.length}</span>
            <Button size="small" disabled={docIdx >= documents.length - 1}
              onClick={() => gotoDoc(docIdx + 1)}>下一个 →</Button>
          </Space>
        </div>
      </div>
      {/* 右栏：字段面板内部滚动 */}
      <div style={{ flex: '0 0 360px', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>字段（点击选中后在左侧框选；眼睛可显隐框）</div>
        <div style={{ flex: 1, minHeight: 0, overflow: 'auto', paddingRight: 4 }}>
          <Space direction="vertical" style={{ width: '100%' }}>
            {topLevel.map((lb: any) => lb.is_group ? groupHeader(lb) : fieldCard(lb))}
          </Space>
        </div>
      </div>
    </div>
  )
}
