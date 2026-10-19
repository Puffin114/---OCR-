import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { Card, Checkbox, Table, Input, Button, Space, message, Tag, Alert, Select, Upload, Modal, Pagination, Segmented } from 'antd'
import { api } from '../api'
import DocViewer from '../components/DocViewer'

const MODE_OPTIONS = [
  { value: 'exact', label: '精确' },
  { value: 'trim_punct', label: '去空格标点' },
  { value: 'ignore_case', label: '忽略大小写' },
  { value: 'date_normalize', label: '日期归一化' },
  { value: 'number_normalize', label: '数字归一化' },
  { value: 'contains', label: '包含即算对' },
]

interface FieldDef {
  uid: number; name: string; description: string; color: string
  modes: string[]; regex: string; parentUid?: number; include: boolean
}

function orderDefs(defs: FieldDef[]): FieldDef[] {
  const tops = defs.filter(d => !d.parentUid)
  const res: FieldDef[] = []
  const used = new Set<number>()
  for (const t of tops) {
    res.push(t); used.add(t.uid)
    for (const c of defs.filter(d => d.parentUid === t.uid)) { res.push(c); used.add(c.uid) }
  }
  for (const d of defs) if (!used.has(d.uid)) res.push(d)
  return res
}

export default function EvalTaskPreview() {
  const { id } = useParams()
  const nav = useNavigate()
  const [searchParams] = useSearchParams()
  const [docs, setDocs] = useState<any[]>([])
  const [name, setName] = useState(`评测-${Date.now()}`)
  const [nameErr, setNameErr] = useState('')
  const nameTimer = useRef<any>(null)
  const [selDocs, setSelDocs] = useState<string[]>([])
  const [defs, setDefs] = useState<FieldDef[]>([])
  const [uid, setUid] = useState(1)
  const [submitting, setSubmitting] = useState(false)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('全部')
  const [viewerKey, setViewerKey] = useState('')
  const [viewerPage, setViewerPage] = useState(1)
  const [viewerPages, setViewerPages] = useState(1)

  // 把后端字段（parent 为名称）转为内部按 uid 关联
  const fromFields = (fields: any[], startUid: number): FieldDef[] => {
    const arr: FieldDef[] = fields.map((f, i) => ({
      uid: startUid + i, name: f.name, description: f.description || '',
      color: f.color || '#2468f2', modes: f.modes?.length ? f.modes : ['exact'],
      regex: '', parentUid: undefined, include: !f.is_group,
    }))
    const name2uid: Record<string, number> = {}
    arr.forEach(d => { name2uid[d.name] = d.uid })
    fields.forEach((f, i) => { if (f.parent && name2uid[f.parent] != null) arr[i].parentUid = name2uid[f.parent] })
    return arr
  }

  // 由源任务持久化的 field_defs 还原字段编辑器（含 parent/modes/regex/include）
  const fromStoredDefs = (defs: any[]): FieldDef[] => {
    const arr: FieldDef[] = defs.map((f, i) => ({
      uid: i + 1, name: f.name, description: f.description || '',
      color: f.color || '#2468f2', modes: f.modes?.length ? f.modes : ['exact'],
      regex: f.regex || '', parentUid: undefined, include: f.include !== false,
    }))
    const name2uid: Record<string, number> = {}
    arr.forEach(d => { name2uid[d.name] = d.uid })
    defs.forEach((f, i) => { if (f.parent && name2uid[f.parent] != null) arr[i].parentUid = name2uid[f.parent] })
    return arr
  }

  // 复制任务默认名：原名 + "-副本"，若已存在自动追加 -副本2、-副本3…
  async function resolveAvailableName(base: string): Promise<string> {
    let candidate = base
    for (let i = 1; i <= 50; i++) {
      try {
        const { available } = await api.checkEvalTaskName(candidate)
        if (available) return candidate
      } catch { return candidate }
      candidate = `${base}${i + 1}`
    }
    return candidate
  }

  function onNameChange(v: string) {
    setName(v)
    setNameErr('')
    if (nameTimer.current) clearTimeout(nameTimer.current)
    const val = v.trim()
    if (!val) return
    nameTimer.current = setTimeout(async () => {
      try {
        const { available } = await api.checkEvalTaskName(val)
        if (!available) setNameErr('该名称已存在，请换一个')
      } catch { /* 网络错误不阻断，提交时由后端兜底 */ }
    }, 400)
  }

  useEffect(() => {
    api.taskCandidates(Number(id)).then((d: any) => {
      setDocs(d.documents || [])
      const candKeys = new Set((d.documents || []).map((x: any) => x.key))
      const copyFrom = searchParams.get('copyFrom')
      if (copyFrom) {
        api.getEvalTask(Number(copyFrom)).then(async (t: any) => {
          setName(await resolveAvailableName(`${t.name || '评测'}-副本`))
          const picked = (t.doc_keys || []).filter((k: string) => candKeys.has(k))
          setSelDocs(picked.length ? picked : (d.documents || []).filter((x: any) => x.evaluable).map((x: any) => x.key))
          let storedDefs: any[] = []
          try { storedDefs = t.field_defs ? JSON.parse(t.field_defs) : [] } catch { storedDefs = [] }
          const fs = (storedDefs && storedDefs.length) ? fromStoredDefs(storedDefs) : fromFields(d.fields || [], 1)
          setDefs(fs); setUid(fs.length + 1)
        }).catch(() => {
          message.warning('源任务加载失败，已按默认新建')
          setSelDocs((d.documents || []).filter((x: any) => x.evaluable).map((x: any) => x.key))
          const fs = fromFields(d.fields || [], 1); setDefs(fs); setUid(fs.length + 1)
        })
      } else {
        setSelDocs((d.documents || []).filter((x: any) => x.evaluable).map((x: any) => x.key))
        const fs = fromFields(d.fields || [], 1)
        setDefs(fs); setUid(fs.length + 1)
      }
    }).catch((e: any) => message.error(e?.response?.data?.detail || String(e)))
    // eslint-disable-next-line
  }, [id])

  const filteredDocs = docs.filter(d =>
    (!search || d.key.toLowerCase().includes(search.toLowerCase())) &&
    (status === '全部' || (status === '已标注' ? d.annotated : !d.annotated)))
  const filteredEvaluable = filteredDocs.filter(d => d.evaluable).map(d => d.key)
  const allSelected = filteredEvaluable.length > 0 && filteredEvaluable.every(k => selDocs.includes(k))

  const toggleDoc = (key: string, checked: boolean) =>
    setSelDocs(s => checked ? [...s, key] : s.filter(k => k !== key))
  const toggleAll = (checked: boolean) =>
    setSelDocs(s => checked
      ? Array.from(new Set([...s, ...filteredEvaluable]))
      : s.filter(k => !filteredEvaluable.includes(k)))

  function openViewer(key: string) {
    setViewerKey(key); setViewerPage(1); setViewerPages(1)
    api.docMeta(key, Number(id)).then(m => setViewerPages(m.page_count || 1)).catch(() => setViewerPages(1))
  }

  const patch = (u: number, p: Partial<FieldDef>) => setDefs(ds => ds.map(d => d.uid === u ? { ...d, ...p } : d))
  const delField = (u: number) => setDefs(ds => ds.filter(d => d.uid !== u && d.parentUid !== u))
  const addField = (parentUid?: number) => {
    setDefs(ds => [...ds, { uid, name: '', description: '', color: '#2468f2', modes: ['exact'], regex: '', parentUid, include: true }])
    setUid(x => x + 1)
  }
  // 母字段勾选级联到其子字段
  const toggleInclude = (u: number, checked: boolean) =>
    setDefs(ds => ds.map(d => (d.uid === u || d.parentUid === u) ? { ...d, include: checked } : d))

  async function importFields(file: File) {
    try {
      const d = await api.parseFields(file)
      const fs = fromFields(d.fields || [], uid)
      setDefs(fs); setUid(uid + fs.length + 1)
      message.success(`已导入 ${fs.length} 个字段`)
    } catch (e: any) { message.error(e?.response?.data?.detail || String(e)) }
  }

  const parentUids = new Set(defs.filter(d => d.parentUid).map(d => d.parentUid))

  async function submit() {
    if (!name.trim()) { message.warning('请输入任务名称'); return }
    try {
      const { available } = await api.checkEvalTaskName(name.trim())
      if (!available) { setNameErr('该名称已存在，请换一个'); message.warning('评测任务名称已存在，请换一个名称'); return }
    } catch { /* 网络错误不阻断，由后端兜底 */ }
    if (selDocs.length === 0) { message.warning('请至少勾选一个文件'); return }
    const uid2name: Record<number, string> = {}
    defs.forEach(d => { uid2name[d.uid] = d.name.trim() })
    const includeOf = (d: FieldDef) => d.parentUid != null
      ? (defs.find(x => x.uid === d.parentUid)?.include ?? d.include) : d.include
    const field_defs = defs.filter(d => d.name.trim()).map(d => ({
      name: d.name.trim(), description: d.description, color: d.color,
      modes: d.modes, regex: d.regex || null,
      parent: d.parentUid != null ? (uid2name[d.parentUid] || null) : null,
      include: includeOf(d),
    }))
    // 至少一个被纳入的叶子字段
    const parentNames = new Set(field_defs.filter(f => f.parent).map(f => f.parent))
    if (field_defs.filter(f => f.include && !parentNames.has(f.name)).length === 0) {
      message.warning('请至少勾选一个要抽取的字段'); return
    }
    setSubmitting(true)
    try {
      const r = await api.createEvalTask({ dataset_id: Number(id), name: name.trim(), doc_keys: selDocs, field_defs })
      message.success('评测任务已创建，正在后台执行')
      nav(`/tasks/${r.task_id}`)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || String(e))
    } finally { setSubmitting(false) }
  }

  const noAnnotated = docs.length > 0 && docs.every(d => !d.evaluable)

  return (
    <Card title={<Space><Button onClick={() => nav('/datasets')}>← 返回</Button>新建评测任务 · 预览配置</Space>}
      extra={<Button type="primary" loading={submitting} onClick={submit}>创建并评测</Button>}>
      <Space direction="vertical" style={{ width: '100%' }} size="large">
        <div>
          <b>任务名称</b>
          <Input style={{ width: 360, marginLeft: 12 }} value={name} status={nameErr ? 'error' : undefined} onChange={e => onNameChange(e.target.value)} />
          {nameErr && <div style={{ color: '#ff4d4f', fontSize: 12, marginTop: 4 }}>{nameErr}</div>}
        </div>

        {noAnnotated && <Alert type="warning" showIcon
          message="该数据集暂无已标注文件，无法计算指标。请用下方「去标注」给文件打标，再创建评测任务。" />}
        <Alert type="info" showIcon
          message="真实云评测将按文件逐篇消耗额度。可自行勾选任意数量文件。" />

        <Card size="small" title={
          <Space wrap>
            <span>勾选要评测的文件（已选 {selDocs.length}）</span>
            <Checkbox checked={allSelected} onChange={e => toggleAll(e.target.checked)}
              disabled={filteredEvaluable.length === 0}>全选（可评测）</Checkbox>
            <Input.Search allowClear placeholder="按文件名筛选" style={{ width: 220 }}
              onChange={e => setSearch(e.target.value)} />
            <Segmented value={status} onChange={v => setStatus(v as string)} options={['全部', '已标注', '未标注']} />
          </Space>
        }>
          <Table rowKey="key" size="small" pagination={false} dataSource={filteredDocs} scroll={{ y: 260 }}
            columns={[
              {
                title: '选择', width: 60, render: (_, r: any) => (
                  <Checkbox disabled={!r.evaluable} checked={selDocs.includes(r.key)}
                    onChange={e => toggleDoc(r.key, e.target.checked)} />
                )
              },
              { title: '文件', dataIndex: 'key', ellipsis: true },
              {
                title: '标注', width: 90, render: (_, r: any) => r.annotated
                  ? <Tag color="green">已标注</Tag> : <Tag color="orange">未标注</Tag>
              },
              {
                title: '操作', width: 170, render: (_, r: any) => (
                  <Space size={4}>
                    <Button size="small" onClick={() => openViewer(r.key)}>查看</Button>
                    <Button size="small" type="link"
                      onClick={() => nav(`/datasets/${id}/annotate?doc=${encodeURIComponent(r.key)}&from=new-task`)}>去标注</Button>
                  </Space>
                )
              },
            ]} />
        </Card>

        <Card size="small" title={
          <Space>字段信息（组合字段按母字段整组勾选）
            <Upload accept=".json,.zip,.xlsx,.csv" showUploadList={false} beforeUpload={(f) => { importFields(f as any); return false }}>
              <Button size="small">字段导入</Button>
            </Upload>
            <Button size="small" type="dashed" onClick={() => addField()}>+ 添加字段</Button>
          </Space>
        }>
          <Table rowKey="uid" size="small" pagination={false} dataSource={orderDefs(defs)}
            columns={[
              {
                title: '抽取', width: 70, render: (_, r: FieldDef) => (
                  r.parentUid != null
                    ? <span style={{ color: '#bbb', fontSize: 12 }}>随母字段</span>
                    : <Checkbox checked={r.include} onChange={e => toggleInclude(r.uid, e.target.checked)} />
                )
              },
              {
                title: '字段名称', width: 220, render: (_, r: FieldDef) => (
                  <Space size={4}>
                    {r.parentUid != null && <span style={{ color: '#bbb' }}>└</span>}
                    <Input size="small" value={r.name} style={{ width: r.parentUid != null ? 120 : 140 }}
                      placeholder="字段名称"
                      onChange={e => patch(r.uid, { name: e.target.value })}
                      onPressEnter={() => message.success('已保存字段修改')} />
                    {parentUids.has(r.uid) && <Tag color="blue">组合</Tag>}
                  </Space>
                )
              },
              { title: '字段说明', render: (_, r: FieldDef) => <Input size="small" value={r.description} onChange={e => patch(r.uid, { description: e.target.value })} /> },
              { title: '颜色', width: 60, render: (_, r: FieldDef) => <input type="color" value={r.color || '#2468f2'} onChange={e => patch(r.uid, { color: e.target.value })} /> },
              {
                title: '个性化设置评测标准', width: 300, render: (_, r: FieldDef) => (
                  <Space direction="vertical" size={2} style={{ width: '100%' }}>
                    <Select size="small" mode="multiple" style={{ width: 280 }} options={MODE_OPTIONS}
                      value={r.modes} onChange={v => patch(r.uid, { modes: v })} />
                    <Input size="small" placeholder="正则(可选) 如 \\d{4}" value={r.regex}
                      onChange={e => patch(r.uid, { regex: e.target.value })} />
                  </Space>
                )
              },
              {
                title: '操作', width: 150, render: (_, r: FieldDef) => (
                  <Space size={4}>
                    {r.parentUid == null && <Button size="small" type="link" onClick={() => addField(r.uid)}>添加子字段</Button>}
                    <Button size="small" type="link" danger onClick={() => delField(r.uid)}>删除</Button>
                  </Space>
                )
              },
            ]} />
        </Card>
      </Space>

      <Modal open={!!viewerKey} title={viewerKey} width={900} footer={null} onCancel={() => setViewerKey('')}>
        <div style={{ overflow: 'auto', maxHeight: '70vh', border: '1px solid #eee' }}>
          {viewerKey && <DocViewer docKey={viewerKey} pageNum={viewerPage} datasetId={Number(id)} />}
        </div>
        <div style={{ marginTop: 8, textAlign: 'center' }}>
          <Pagination simple current={viewerPage} total={viewerPages} pageSize={1} onChange={setViewerPage} />
        </div>
      </Modal>
    </Card>
  )
}
