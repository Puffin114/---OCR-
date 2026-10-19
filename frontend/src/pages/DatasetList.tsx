import { useEffect, useRef, useState } from 'react'
import { Button, Card, Table, Tag, Space, message, Statistic, Row, Col, Modal, Pagination, Popconfirm, Input } from 'antd'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import DocViewer from '../components/DocViewer'

export default function DatasetList() {
  const [datasets, setDatasets] = useState<any[]>([])
  const [detail, setDetail] = useState<any>(null)
  const [viewerKey, setViewerKey] = useState<string>('')
  const [viewerPage, setViewerPage] = useState(1)
  const [viewerPages, setViewerPages] = useState(1)
  const [renameTarget, setRenameTarget] = useState<any>(null)
  const [renameValue, setRenameValue] = useState('')
  const [renameErr, setRenameErr] = useState('')
  const renameTimer = useRef<any>(null)
  const nav = useNavigate()

  const refresh = () => api.listDatasets().then(setDatasets)
  useEffect(() => { refresh() }, [])

  async function open(id: number) {
    setDetail(await api.getDataset(id))
  }

  function openDoc(key: string) {
    setViewerKey(key)
    setViewerPage(1)
    setViewerPages(1)
    api.docMeta(key, detail?.dataset?.id).then(m => setViewerPages(m.page_count || 1)).catch(() => setViewerPages(1))
  }

  async function remove(id: number) {
    try {
      await api.deleteDataset(id)
      message.success('已删除数据集')
      if (detail?.dataset?.id === id) setDetail(null)
      refresh()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || String(e))
    }
  }

  function onRenameChange(v: string) {
    setRenameValue(v)
    setRenameErr('')
    if (renameTimer.current) clearTimeout(renameTimer.current)
    const val = v.trim()
    if (!val || !renameTarget) return
    renameTimer.current = setTimeout(async () => {
      try {
        const { available } = await api.checkDatasetName(val, renameTarget.id)
        if (!available) setRenameErr('该名称已存在，请换一个')
      } catch { /* 网络错误不阻断 */ }
    }, 400)
  }

  return (
    <div>
      <Space style={{ marginBottom: 16 }} wrap>
        <Button type="primary" onClick={() => nav('/datasets/create')}>创建数据集</Button>
        {/* 回流 / 回流数据集列表 入口暂时下线；后续若接入场景化回流再恢复
        <Button onClick={() => nav('/backflow')}>回流数据</Button>
        <Button onClick={() => nav('/backflow/datasets')}>回流数据集列表</Button>
        */}
        <span style={{ color: '#999' }}>
          创建数据集支持：有标注(zip) 或 未标注(原文件，平台内标注)
        </span>
      </Space>
      <Card title="数据集列表" style={{ marginBottom: 16 }}>
        <Table rowKey="id" dataSource={datasets} pagination={false}
          columns={[
            { title: 'ID', dataIndex: 'id', width: 60 },
            { title: '名称', dataIndex: 'name' },
            { title: '文档数', dataIndex: 'doc_total', width: 100 },
            { title: '创建时间', dataIndex: 'created_at', width: 180 },
            {
              title: '操作', width: 400, render: (_, r) => (
                <Space>
                  <Button size="small" onClick={() => open(r.id)}>查看</Button>
                  <Button size="small" onClick={() => { setRenameTarget(r); setRenameValue(r.name) }}>重命名</Button>
                  <Button size="small" onClick={() => nav(`/datasets/${r.id}/annotate`)}>二次标注</Button>
                  <Button size="small" type="primary" onClick={() => nav(`/datasets/${r.id}/new-task`)}>新建评测任务</Button>
                  <Popconfirm title="确认删除该数据集？" description="将一并删除其标注、评测任务与上传文件，不可恢复。"
                    okText="删除" cancelText="取消" okButtonProps={{ danger: true }}
                    onConfirm={() => remove(r.id)}>
                    <Button size="small" danger>删除</Button>
                  </Popconfirm>
                </Space>
              )
            },
          ]} />
      </Card>

      {detail && (
        <Card title={`字段清单与标注统计（数据集 #${detail.dataset.id}）`}>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            {detail.labels.map((lb: any) => (
              <Col key={lb.id}>
                <Card size="small" style={{ borderTop: `3px solid ${lb.label_color}` }}>
                  <Statistic title={lb.label_name}
                    value={detail.field_counts[lb.label_name] ?? 0}
                    suffix={`/ ${detail.dataset.doc_total}`} />
                </Card>
              </Col>
            ))}
          </Row>
          <Table rowKey="id" size="small" dataSource={detail.documents} scroll={{ y: 320 }}
            pagination={false}
            columns={[
              {
                title: '文档', dataIndex: 'key', ellipsis: true,
                render: (v: string) => <a onClick={() => openDoc(v)}>{v}</a>
              },
              {
                title: '完整性', dataIndex: 'complete', width: 100,
                render: (v) => v ? <Tag color="green">完整</Tag> : <Tag color="orange">不完整</Tag>
              },
              {
                title: '操作', width: 90,
                render: (_, r: any) => <Button size="small" onClick={() => openDoc(r.key)}>查看</Button>
              },
            ]} />
        </Card>
      )}

      <Modal open={!!viewerKey} title={viewerKey} width={900} footer={null}
        onCancel={() => setViewerKey('')}>
        <div style={{ overflow: 'auto', maxHeight: '70vh', border: '1px solid #eee' }}>
          {viewerKey && <DocViewer docKey={viewerKey} pageNum={viewerPage} datasetId={detail?.dataset?.id} />}
        </div>
        <div style={{ marginTop: 8, textAlign: 'center' }}>
          <Pagination simple current={viewerPage} total={viewerPages} pageSize={1}
            onChange={setViewerPage} />
        </div>
      </Modal>

      <Modal open={!!renameTarget} title="重命名数据集" okText="保存" cancelText="取消"
        okButtonProps={{ disabled: !!renameErr }}
        onCancel={() => { setRenameTarget(null); setRenameErr('') }}
        onOk={async () => {
          const name = renameValue.trim()
          if (!name) { message.warning('名称不能为空'); return }
          if (renameErr) { message.warning('数据集名称已存在，请换一个名称'); return }
          try {
            await api.renameDataset(renameTarget.id, name)
          } catch (e: any) {
            message.error(e?.response?.data?.detail || String(e)); return
          }
          const tid = renameTarget.id
          setRenameTarget(null); setRenameErr(''); message.success('已重命名'); refresh()
          if (detail?.dataset?.id === tid) open(tid)
        }}>
        <Input value={renameValue} status={renameErr ? 'error' : undefined}
          onChange={e => onRenameChange(e.target.value)} placeholder="输入新的数据集名称" />
        {renameErr && <div style={{ color: '#ff4d4f', fontSize: 12, marginTop: 4 }}>{renameErr}</div>}
      </Modal>
    </div>
  )
}
