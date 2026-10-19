import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Input, InputNumber, Button, Space, message, Upload, Progress, Alert, Descriptions } from 'antd'
import { api } from '../api'

export default function Backflow() {
  const nav = useNavigate()
  const [scene, setScene] = useState<any>(null)
  const [name, setName] = useState('')
  const [nameErr, setNameErr] = useState('')
  const nameTimer = useRef<any>(null)
  const [dbPassword, setDbPassword] = useState('')
  const [ak, setAk] = useState('')
  const [sk, setSk] = useState('')
  const [userId, setUserId] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [limit, setLimit] = useState(20)
  const [fields, setFields] = useState<any[]>([])
  const [job, setJob] = useState<any>(null)
  const [running, setRunning] = useState(false)
  const [probing, setProbing] = useState(false)
  const [probe, setProbe] = useState<any>(null)
  const pollTimer = useRef<any>(null)

  useEffect(() => {
    api.backflowScene().then(setScene).catch(() => { })
    return () => { if (pollTimer.current) clearTimeout(pollTimer.current) }
  }, [])

  function onNameChange(v: string) {
    setName(v); setNameErr('')
    if (nameTimer.current) clearTimeout(nameTimer.current)
    const val = v.trim()
    if (!val) return
    nameTimer.current = setTimeout(async () => {
      try {
        const { available } = await api.checkDatasetName(val)
        if (!available) setNameErr('该名称已存在，请换一个')
      } catch { /* 网络错误不阻断 */ }
    }, 400)
  }

  async function importFields(file: File) {
    try {
      const d = await api.parseFields(file)
      setFields(d.fields || [])
      message.success(`已导入 ${(d.fields || []).length} 个字段`)
    } catch (e: any) { message.error(e?.response?.data?.detail || String(e)) }
  }

  function poll(jobId: string) {
    api.getBackflowJob(jobId).then((j: any) => {
      setJob(j)
      if (j.status === 'running') {
        pollTimer.current = setTimeout(() => poll(jobId), 1500)
      } else {
        setRunning(false)
        if (j.status === 'success') message.success(j.message || '回流完成')
        else message.error(j.message || '回流失败')
      }
    }).catch(() => { setRunning(false) })
  }

  async function doProbe() {
    if (!dbPassword || !ak || !sk) { message.warning('探测也需要数据库密码、AK、SK'); return }
    setProbing(true); setProbe(null)
    try {
      const d = await api.probeBackflow({
        db_password: dbPassword, ak, sk, user_id: userId.trim() || null, sample: 5,
      })
      setProbe(d)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || String(e))
    } finally { setProbing(false) }
  }

  async function start() {    if (!name.trim()) { message.warning('请输入回流数据集名称'); return }
    if (nameErr) { message.warning('数据集名称已存在，请换一个名称'); return }
    if (!dbPassword || !ak || !sk) { message.warning('数据库密码、AK、SK 均为必填'); return }
    setRunning(true); setJob(null)
    try {
      const { job_id } = await api.startBackflow({
        name: name.trim(), db_password: dbPassword, ak, sk,
        user_id: userId.trim() || null,
        date_from: dateFrom.trim() || null, date_to: dateTo.trim() || null,
        limit, fields,
      })
      // 启动后立即清空内存中的敏感输入
      setDbPassword(''); setAk(''); setSk('')
      poll(job_id)
    } catch (e: any) {
      setRunning(false)
      message.error(e?.response?.data?.detail || String(e))
    }
  }

  const pct = job && job.total ? Math.round((job.done / job.total) * 100) : 0

  return (
    <Card title={<Space><Button onClick={() => nav('/datasets')}>← 返回</Button>回流数据 · 信息提取 Extract</Space>}
      extra={<Button onClick={() => nav('/backflow/datasets')}>回流数据集列表</Button>}>
      <Space direction="vertical" style={{ width: '100%' }} size="large">
        <Alert type="warning" showIcon
          message="凭证仅本次有效、绝不存储：数据库密码、AK、SK 仅用于本次回流，任务启动后立即从页面清除，后端不写入任何持久化介质。" />

        {scene && (
          <Descriptions size="small" column={2} bordered title="场景与连接（预置，不可改）">
            <Descriptions.Item label="场景">{scene.label}</Descriptions.Item>
            <Descriptions.Item label="数据库">{scene.db_host}:{scene.db_port} / {scene.db_name}</Descriptions.Item>
            <Descriptions.Item label="只读账号">{scene.db_user}</Descriptions.Item>
            <Descriptions.Item label="BOS Bucket">{scene.bos_bucket}</Descriptions.Item>
          </Descriptions>
        )}

        <div>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>凭证（单次有效）</div>
          <Space direction="vertical">
            <div><span style={{ display: 'inline-block', width: 110 }}>数据库密码</span>
              <Input.Password style={{ width: 320 }} value={dbPassword} autoComplete="new-password"
                onChange={e => setDbPassword(e.target.value)} placeholder="extract 库只读账号密码" /></div>
            <div><span style={{ display: 'inline-block', width: 110 }}>BOS AK</span>
              <Input.Password style={{ width: 320 }} value={ak} autoComplete="new-password"
                onChange={e => setAk(e.target.value)} placeholder="Access Key" /></div>
            <div><span style={{ display: 'inline-block', width: 110 }}>BOS SK</span>
              <Input.Password style={{ width: 320 }} value={sk} autoComplete="new-password"
                onChange={e => setSk(e.target.value)} placeholder="Secret Key" /></div>
          </Space>
        </div>

        <div>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>筛选条件</div>
          <Space direction="vertical">
            <div><span style={{ display: 'inline-block', width: 110 }}>user_id（可选）</span>
              <Input style={{ width: 320 }} value={userId} onChange={e => setUserId(e.target.value)} placeholder="留空则不限用户" /></div>
            <div><span style={{ display: 'inline-block', width: 110 }}>创建时间（可选）</span>
              <Space>
                <Input style={{ width: 150 }} value={dateFrom} onChange={e => setDateFrom(e.target.value)} placeholder="起 YYYY-MM-DD" />
                <span>~</span>
                <Input style={{ width: 150 }} value={dateTo} onChange={e => setDateTo(e.target.value)} placeholder="止 YYYY-MM-DD" />
              </Space></div>
            <div><span style={{ display: 'inline-block', width: 110 }}>数量上限</span>
              <InputNumber min={1} max={500} value={limit} onChange={v => setLimit(Number(v) || 20)} style={{ width: 150 }} /></div>
          </Space>
        </div>

        <div>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>回流数据集</div>
          <Space direction="vertical">
            <div><span style={{ display: 'inline-block', width: 110 }}>数据集名称</span>
              <Input style={{ width: 320 }} maxLength={50} value={name} status={nameErr ? 'error' : undefined}
                onChange={e => onNameChange(e.target.value)} placeholder="请输入回流数据集名称" />
              {nameErr && <span style={{ color: '#ff4d4f', fontSize: 12, marginLeft: 8 }}>{nameErr}</span>}</div>
            <div><span style={{ display: 'inline-block', width: 110, verticalAlign: 'top' }}>字段清单（可选）</span>
              <Space>
                <Upload accept=".json,.zip,.xlsx,.csv" showUploadList={false} beforeUpload={(f) => { importFields(f as any); return false }}>
                  <Button size="small">导入字段清单</Button>
                </Upload>
                <span style={{ color: '#999', fontSize: 12 }}>
                  {fields.length ? `已导入 ${fields.length} 个字段` : '留空则生成空字段清单，可在平台内再配置'}
                </span>
              </Space></div>
          </Space>
        </div>

        <div>
          <Space>
            <Button type="primary" loading={running} disabled={!!nameErr} onClick={start}>开始回流</Button>
            <Button loading={probing} onClick={doProbe}>探测(dry-run)</Button>
            <Button onClick={() => nav('/datasets')}>取消</Button>
          </Space>
          <div style={{ color: '#999', fontSize: 12, marginTop: 6 }}>
            下载全失败时，先点「探测」：只查前 5 条样本的 DB 字段与 BOS 目录，不下载、不建数据集，用于定位路径/权限问题。
          </div>
        </div>

        {probe && (
          <Card size="small" title="探测结果（dry-run）">
            {(probe.errors || []).length > 0 && (
              <Alert type="error" showIcon style={{ marginBottom: 8 }}
                message="错误" description={<pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{(probe.errors || []).join('\n')}</pre>} />
            )}
            <div style={{ fontWeight: 600, margin: '4px 0' }}>t_extract_doc 实际列</div>
            <pre style={{ whiteSpace: 'pre-wrap', background: '#f6f6f6', padding: 8, borderRadius: 6 }}>
              {(probe.db?.columns || []).join(', ') || '（未取到）'}
            </pre>
            <div style={{ fontWeight: 600, margin: '8px 0 4px' }}>样本文档字段值（前 5 条）</div>
            <pre style={{ whiteSpace: 'pre-wrap', background: '#f6f6f6', padding: 8, borderRadius: 6, maxHeight: 220, overflow: 'auto' }}>
              {JSON.stringify(probe.db?.sample || [], null, 2)}
            </pre>
            <div style={{ fontWeight: 600, margin: '8px 0 4px' }}>BOS 各前缀列目录结果</div>
            <pre style={{ whiteSpace: 'pre-wrap', background: '#f6f6f6', padding: 8, borderRadius: 6, maxHeight: 260, overflow: 'auto' }}>
              {JSON.stringify(probe.bos?.probes || {}, null, 2)}
            </pre>
            <div style={{ fontWeight: 600, margin: '8px 0 4px' }}>库中所有表</div>
            <pre style={{ whiteSpace: 'pre-wrap', background: '#f6f6f6', padding: 8, borderRadius: 6, maxHeight: 160, overflow: 'auto' }}>
              {(probe.db?.tables || []).join(', ') || '（未取到）'}
            </pre>
            <div style={{ fontWeight: 600, margin: '8px 0 4px' }}>t_extract_task 列 + 样本（含场景字段）</div>
            <pre style={{ whiteSpace: 'pre-wrap', background: '#f6f6f6', padding: 8, borderRadius: 6, maxHeight: 120, overflow: 'auto' }}>
              {(probe.db?.task_columns || []).join(', ') || '（未取到）'}
            </pre>
            <pre style={{ whiteSpace: 'pre-wrap', background: '#f6f6f6', padding: 8, borderRadius: 6, maxHeight: 260, overflow: 'auto' }}>
              {JSON.stringify(probe.db?.task_sample || [], null, 2)}
            </pre>
            <div style={{ fontWeight: 600, margin: '8px 0 4px' }}>t_extract_task_doc 列 + 样本（任务↔文档关联）</div>
            <pre style={{ whiteSpace: 'pre-wrap', background: '#f6f6f6', padding: 8, borderRadius: 6, maxHeight: 120, overflow: 'auto' }}>
              {(probe.db?.task_doc_columns || []).join(', ') || '（未取到）'}
            </pre>
            <pre style={{ whiteSpace: 'pre-wrap', background: '#f6f6f6', padding: 8, borderRadius: 6, maxHeight: 220, overflow: 'auto' }}>
              {JSON.stringify(probe.db?.task_doc_sample || [], null, 2)}
            </pre>
          </Card>
        )}

        {job && (
          <Card size="small" title="回流进度">
            <Progress percent={pct} status={job.status === 'failed' ? 'exception' : job.status === 'success' ? 'success' : 'active'} />
            <div style={{ marginTop: 8, color: '#555' }}>
              待处理 {job.total}，已处理 {job.done}，成功 {job.success}，跳过(已存在) {job.skipped}，缺失 {(job.missing || []).length}
            </div>
            {job.message && <div style={{ marginTop: 8 }}>{job.message}</div>}
            {job.status === 'success' && (
              <Button type="link" style={{ paddingLeft: 0 }} onClick={() => nav('/backflow/datasets')}>前往回流数据集列表 →</Button>
            )}
          </Card>
        )}
      </Space>
    </Card>
  )
}
