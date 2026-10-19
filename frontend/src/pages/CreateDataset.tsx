import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Steps, Input, Button, Space, message, Table, Select, Upload, Radio, Tag, Modal } from 'antd'
import { api } from '../api'

const MODE_OPTIONS = [
  { value: 'exact', label: '精确' },
  { value: 'trim_punct', label: '去空格标点' },
  { value: 'ignore_case', label: '忽略大小写' },
  { value: 'date_normalize', label: '日期归一化' },
  { value: 'number_normalize', label: '数字归一化' },
  { value: 'contains', label: '包含即算对' },
]

interface FieldDef { uid: number; name: string; description: string; color: string; modes: string[]; parentUid?: number }

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

export default function CreateDataset() {
  const nav = useNavigate()
  const [step, setStep] = useState(0)
  const [name, setName] = useState('')
  const [nameErr, setNameErr] = useState('')
  const nameTimer = useRef<any>(null)
  const [description, setDescription] = useState('')
  const [defs, setDefs] = useState<FieldDef[]>([])
  const [uid, setUid] = useState(1)
  const [annotated, setAnnotated] = useState(false)
  const [files, setFiles] = useState<File[]>([])
  const [preview, setPreview] = useState<{ url: string; name: string; kind: string } | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // 后端字段（parent 为名称）→ 内部按 uid 关联
  const fromFields = (fields: any[], startUid: number): FieldDef[] => {
    const arr: FieldDef[] = fields.map((f, i) => ({
      uid: startUid + i, name: f.name, description: f.description || '',
      color: f.color || '#2468f2', modes: f.modes?.length ? f.modes : ['exact'], parentUid: undefined,
    }))
    const name2uid: Record<string, number> = {}
    arr.forEach(d => { name2uid[d.name] = d.uid })
    fields.forEach((f, i) => { if (f.parent && name2uid[f.parent] != null) arr[i].parentUid = name2uid[f.parent] })
    return arr
  }

  const patch = (u: number, p: Partial<FieldDef>) => setDefs(ds => ds.map(d => d.uid === u ? { ...d, ...p } : d))
  const delField = (u: number) => setDefs(ds => ds.filter(d => d.uid !== u && d.parentUid !== u))
  const addField = (parentUid?: number) => {
    setDefs(ds => [...ds, { uid, name: '', description: '', color: '#2468f2', modes: ['exact'], parentUid }])
    setUid(x => x + 1)
  }
  const parentUids = new Set(defs.filter(d => d.parentUid).map(d => d.parentUid))

  async function importManifest(file: File) {
    try {
      const d = await api.parseFields(file)
      const fs = fromFields(d.fields || [], 1)
      setDefs(fs); setUid(fs.length + 1)
      message.success(`已导入 ${fs.length} 个字段，可继续编辑`)
    } catch (e: any) { message.error(e?.response?.data?.detail || String(e)) }
  }

  async function onZipSelected(file: File) {
    // 有标注：自动识别字段清单并回填，供用户调整
    try {
      const d = await api.parseFields(file)
      if (d.fields?.length) { const fs = fromFields(d.fields, 1); setDefs(fs); setUid(fs.length + 1); message.success('已从压缩包识别字段，可返回上一步调整') }
    } catch { /* zip 无 labels.json 时忽略 */ }
  }

  function buildFields() {
    const uid2name: Record<number, string> = {}
    defs.forEach(d => { uid2name[d.uid] = d.name.trim() })
    return defs.filter(d => d.name.trim()).map(d => ({
      name: d.name.trim(), description: d.description, color: d.color, modes: d.modes,
      parent: d.parentUid != null ? (uid2name[d.parentUid] || null) : null,
    }))
  }

  function onNameChange(v: string) {
    setName(v)
    setNameErr('')
    if (nameTimer.current) clearTimeout(nameTimer.current)
    const val = v.trim()
    if (!val) return
    nameTimer.current = setTimeout(async () => {
      try {
        const { available } = await api.checkDatasetName(val)
        if (!available) setNameErr('该名称已存在，请换一个')
      } catch { /* 网络错误不阻断，提交时由后端兜底 */ }
    }, 400)
  }

  async function next() {
    if (!name.trim()) { message.warning('请输入数据集名称'); return }
    try {
      const { available } = await api.checkDatasetName(name.trim())
      if (!available) { setNameErr('该名称已存在，请换一个'); message.warning('数据集名称已存在，请换一个名称'); return }
    } catch { /* 网络错误不阻断，提交时由后端兜底 */ }
    if (!annotated && defs.filter(f => f.name.trim()).length === 0) {
      message.warning('未标注导入请先添加字段'); return
    }
    setStep(1)
  }

  function openPreview(file: File) {
    const lower = file.name.toLowerCase()
    const kind = lower.endsWith('.pdf') ? 'pdf'
      : /\.(png|jpe?g|webp|gif|bmp)$/.test(lower) ? 'image' : 'other'
    setPreview({ url: URL.createObjectURL(file), name: file.name, kind })
  }
  function closePreview() {
    if (preview) URL.revokeObjectURL(preview.url)
    setPreview(null)
  }

  async function chunkedUpload(file: File, payload: any) {
    const CHUNK = 5 * 1024 * 1024
    const uploadId = `up${Date.now()}${Math.floor(Math.random() * 1e6)}`
    const total = Math.max(1, Math.ceil(file.size / CHUNK))
    for (let i = 0; i < total; i++) {
      const blob = file.slice(i * CHUNK, (i + 1) * CHUNK)
      let ok = false
      for (let attempt = 0; attempt < 3 && !ok; attempt++) {
        try { await api.uploadChunk(uploadId, i, blob); ok = true }
        catch (e) { if (attempt === 2) throw e }
      }
      message.loading({ content: `上传中 ${Math.round(((i + 1) / total) * 100)}%`, key: 'up', duration: 0 })
    }
    message.loading({ content: '正在解析导入…', key: 'up', duration: 0 })
    const d = await api.uploadFinish({ ...payload, upload_id: uploadId, filename: file.name })
    message.destroy('up')
    return d
  }

  async function submit() {
    const cleanFields = buildFields()
    if (files.length === 0) { message.warning('请上传文件'); return }
    if (annotated && !files.some(f => f.name.toLowerCase().endsWith('.zip'))) {
      message.warning('有标注导入请上传 zip 压缩包'); return
    }
    if (!annotated && cleanFields.length === 0) { message.warning('请先配置字段'); return }
    setSubmitting(true)
    try {
      let d: any
      if (annotated) {
        const zip = files.find(f => f.name.toLowerCase().endsWith('.zip'))!
        d = await chunkedUpload(zip, { name: name.trim(), annotated: true, fields: cleanFields })
      } else if (files.length === 1) {
        d = await chunkedUpload(files[0], { name: name.trim(), annotated: false, fields: cleanFields })
      } else {
        d = await api.createDataset({ name: name.trim(), description, annotated, fields: cleanFields, files })
      }
      message.success(`数据集「${d.dataset.name}」已创建，共 ${d.dataset.doc_total} 篇文档`)
      nav('/datasets')
    } catch (e: any) {
      message.destroy('up')
      message.error(e?.response?.data?.detail || String(e))
    } finally { setSubmitting(false) }
  }

  const step1 = (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <div>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>基本信息</div>
        <Space direction="vertical" style={{ width: '100%' }}>
          <div><span style={{ display: 'inline-block', width: 90 }}>数据集名称</span>
            <Input style={{ width: 360 }} maxLength={50} value={name} status={nameErr ? 'error' : undefined} onChange={e => onNameChange(e.target.value)} placeholder="请输入数据集名称" />
            {nameErr && <div style={{ color: '#ff4d4f', fontSize: 12, marginLeft: 90, marginTop: 4 }}>{nameErr}</div>}</div>
          <div><span style={{ display: 'inline-block', width: 90, verticalAlign: 'top' }}>描述</span>
            <Input.TextArea style={{ width: 360 }} maxLength={100} value={description} onChange={e => setDescription(e.target.value)} placeholder="请输入描述" /></div>
        </Space>
      </div>
      <div>
        <Space style={{ marginBottom: 8 }}>
          <span style={{ fontWeight: 600 }}>字段信息（组合字段按母字段分组）</span>
          <Upload accept=".json,.zip,.xlsx,.csv" showUploadList={false} beforeUpload={(f) => { importManifest(f as any); return false }}>
            <Button size="small">导入字段清单</Button>
          </Upload>
          <Button size="small" type="dashed" onClick={() => addField()}>+ 添加字段</Button>
        </Space>
        <Table rowKey="uid" size="small" pagination={false} dataSource={orderDefs(defs)}
          columns={[
            {
              title: '字段名称', width: 240, render: (_, r: FieldDef) => (
                <Space size={4}>
                  {r.parentUid != null && <span style={{ color: '#bbb' }}>└</span>}
                  <Input size="small" value={r.name} style={{ width: r.parentUid != null ? 150 : 170 }}
                    placeholder="字段名称" onChange={e => patch(r.uid, { name: e.target.value })} />
                  {parentUids.has(r.uid) && <Tag color="blue">组合</Tag>}
                  {r.parentUid != null && <span style={{ color: '#bbb', fontSize: 12 }}>随母字段</span>}
                </Space>
              )
            },
            { title: '字段说明', render: (_, r: FieldDef) => <Input size="small" value={r.description} onChange={e => patch(r.uid, { description: e.target.value })} /> },
            { title: '颜色', width: 70, render: (_, r: FieldDef) => <input type="color" value={r.color || '#2468f2'} onChange={e => patch(r.uid, { color: e.target.value })} /> },
            {
              title: '评测逻辑', width: 240, render: (_, r: FieldDef) => (
                <Select size="small" mode="multiple" style={{ width: 230 }} options={MODE_OPTIONS}
                  value={r.modes} onChange={(v) => patch(r.uid, { modes: v })} />
              )
            },
            {
              title: '操作', width: 150, render: (_, r: FieldDef) => (
                <Space size={4}>
                  {r.parentUid == null && <Button size="small" type="link" onClick={() => addField(r.uid)}>添加子字段</Button>}
                  <Button size="small" danger type="link" onClick={() => delField(r.uid)}>删除</Button>
                </Space>
              )
            },
          ]} />
      </div>
    </Space>
  )

  const step2 = (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <div>
        <span style={{ display: 'inline-block', width: 90 }}>标注状态</span>
        <Radio.Group value={annotated} onChange={e => { setAnnotated(e.target.value); setFiles([]) }}>
          <Radio value={false}>无标注结果（上传原文件，平台内标注）</Radio>
          <Radio value={true}>有标注结果（上传含 annotations/labels.json/doc 的 zip）</Radio>
        </Radio.Group>
      </div>
      <div>
        <span style={{ display: 'inline-block', width: 90, verticalAlign: 'top' }}>上传文件</span>
        <Upload multiple={!annotated} accept={annotated ? '.zip' : undefined}
          showUploadList={annotated}
          beforeUpload={(file, list) => {
            if (annotated) { setFiles([file as any]); onZipSelected(file as any) }
            else setFiles(prev => {
              // antd 对多选会多次回调，用 list 合并去重
              const merged = [...prev]
              for (const f of (list as any[])) if (!merged.find(x => x.name === f.name && x.size === f.size)) merged.push(f)
              return merged
            })
            return false
          }}
          fileList={files.map((f, i) => ({ uid: String(i), name: f.name })) as any}
          onRemove={(file) => setFiles(fs => fs.filter(f => f.name !== file.name))}>
          <Button>上传文件</Button>
        </Upload>
        <div style={{ color: '#999', fontSize: 12, marginTop: 6, marginLeft: 90 }}>
          {annotated
            ? '上传 1 个 zip（含 annotations/（含 labels.json）/doc，可选 parser）。上传后会自动识别字段，可返回上一步调整。'
            : '可多选 PDF/图片（或仅含文件的 zip）；字段用上一步配置的清单。点「查看」可预览 PDF/图片。'}
        </div>
        {!annotated && files.length > 0 && (
          <Table style={{ marginTop: 10 }} rowKey="name" size="small" pagination={false}
            dataSource={files.map(f => ({ name: f.name, size: f.size, file: f }))}
            columns={[
              { title: '文件', dataIndex: 'name', ellipsis: true },
              { title: '大小', dataIndex: 'size', width: 110, render: (v: number) => `${(v / 1024).toFixed(1)} KB` },
              {
                title: '操作', width: 150, render: (_, r: any) => (
                  <Space size={4}>
                    <Button size="small" onClick={() => openPreview(r.file)}>查看</Button>
                    <Button size="small" danger type="link"
                      onClick={() => setFiles(fs => fs.filter(x => x.name !== r.name))}>移除</Button>
                  </Space>
                )
              },
            ]} />
        )}
      </div>
    </Space>
  )

  return (
    <Card title={<Space><Button onClick={() => nav('/datasets')}>← 返回</Button>创建数据集</Space>}>
      <Steps current={step} style={{ maxWidth: 520, margin: '0 auto 20px' }}
        items={[{ title: '基本配置' }, { title: '数据导入' }]} />
      {step === 0 ? step1 : step2}
      <div style={{ marginTop: 24 }}>
        <Space>
          {step === 1 && <Button onClick={() => setStep(0)}>上一步</Button>}
          {step === 0 && <Button type="primary" disabled={!!nameErr} onClick={next}>下一步</Button>}
          {step === 1 && <Button type="primary" loading={submitting} onClick={submit}>确定</Button>}
          <Button onClick={() => nav('/datasets')}>取消</Button>
        </Space>
      </div>
      <Modal open={!!preview} title={preview?.name} width={900} footer={null} onCancel={closePreview}>
        <div style={{ height: '70vh', overflow: 'auto', textAlign: 'center' }}>
          {preview?.kind === 'pdf' && <iframe src={preview.url} title={preview.name} style={{ width: '100%', height: '100%', border: 'none' }} />}
          {preview?.kind === 'image' && <img src={preview.url} alt={preview.name} style={{ maxWidth: '100%' }} />}
          {preview?.kind === 'other' && <div style={{ color: '#999', paddingTop: 40 }}>该文件类型暂不支持预览（{preview.name}），创建后可在二次标注页查看。</div>}
        </div>
      </Modal>
    </Card>
  )
}
