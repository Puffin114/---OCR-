import { useEffect, useState } from 'react'
import { Card, Tabs, Input, Button, Space, message, Table, Modal, Select, Form } from 'antd'
import { api } from '../api'

const MODEL_TYPES = [
  '文本生成-非思考', '文本生成-思考', '视觉理解-非思考', '视觉理解-思考',
]

function CredentialsTab() {
  const [v, setV] = useState<any>({})
  const [saving, setSaving] = useState(false)
  const load = () => api.getCredentials().then(setV).catch(() => {})
  useEffect(() => { load() }, [])
  const set = (k: string, val: any) => setV((s: any) => ({ ...s, [k]: val }))

  async function save() {
    setSaving(true)
    try { await api.saveCredentials(v); message.success('已保存并生效'); load() }
    catch (e: any) { message.error(e?.response?.data?.detail || '保存失败') }
    finally { setSaving(false) }
  }

  const row = (label: string, k: string, pwd = false) => (
    <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
      <span style={{ width: 140, color: '#555' }}>{label}</span>
      {pwd
        ? <Input.Password style={{ width: 480 }} value={v[k] || ''} placeholder="留空则不修改"
            onChange={e => set(k, e.target.value)} />
        : <Input style={{ width: 480 }} value={v[k] || ''} onChange={e => set(k, e.target.value)} />}
    </div>
  )

  return (
    <div style={{ paddingTop: 8 }}>
      {row('API Key (AK)', 'api_key')}
      {row('Secret Key (SK)', 'secret_key', true)}
      {row('Token URL', 'token_url')}
      {row('Submit URL', 'submit_url')}
      {row('Result URL', 'result_url')}
      {row('OCR URL', 'ocr_url')}
      <Button type="primary" loading={saving} onClick={save}>保存</Button>
    </div>
  )
}

function ModelsTab() {
  const [rows, setRows] = useState<any[]>([])
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [form] = Form.useForm()
  const load = () => api.listModels().then(setRows).catch(() => {})
  useEffect(() => { load() }, [])

  function openModal(r?: any) {
    setEditing(r || null)
    form.resetFields()
    if (r) form.setFieldsValue({ ...r, api_key: '' })
    setOpen(true)
  }
  async function save() {
    const vals = await form.validateFields()
    try {
      if (editing) await api.updateModel(editing.id, vals)
      else await api.createModel(vals)
      message.success('已保存'); setOpen(false); load()
    } catch (e: any) { message.error(e?.response?.data?.detail || '保存失败') }
  }
  async function del(r: any) {
    await api.deleteModel(r.id); message.success('已删除'); load()
  }

  return (
    <div style={{ paddingTop: 8 }}>
      <Button type="primary" style={{ marginBottom: 12 }} onClick={() => openModal()}>+ 创建模型服务</Button>
      <Table rowKey="id" size="small" pagination={false} dataSource={rows}
        columns={[
          { title: '服务名称', dataIndex: 'name' },
          { title: 'Model', dataIndex: 'model' },
          { title: '模型类型', dataIndex: 'model_type', width: 150 },
          { title: 'API URL', dataIndex: 'api_url', ellipsis: true },
          { title: 'API Key', dataIndex: 'api_key', width: 140 },
          { title: '更新时间', dataIndex: 'updated_at', width: 170 },
          {
            title: '操作', width: 120, render: (_, r: any) => (
              <Space size={4}>
                <Button size="small" type="link" onClick={() => openModal(r)}>编辑</Button>
                <Button size="small" type="link" danger onClick={() => del(r)}>删除</Button>
              </Space>
            )
          },
        ]} />
      <Modal open={open} title={editing ? '编辑模型服务' : '创建模型服务'} okText="保存" cancelText="取消"
        onCancel={() => setOpen(false)} onOk={save} width={560}>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="服务名称" rules={[{ required: true, message: '请输入服务名称' }]}>
            <Input placeholder="如 qwen35-122b-a10b" />
          </Form.Item>
          <Form.Item name="model" label="Model"><Input placeholder="如 qwen3.5-122b-a10b" /></Form.Item>
          <Form.Item name="model_type" label="模型类型">
            <Select options={MODEL_TYPES.map(t => ({ value: t, label: t }))} allowClear />
          </Form.Item>
          <Form.Item name="api_key" label="API Key">
            <Input.Password placeholder={editing ? '留空则不修改' : 'bce-v3/ALTAK-...'} />
          </Form.Item>
          <Form.Item name="api_url" label="API URL">
            <Input placeholder="https://qianfan.baidubce.com/v2/chat/completions" />
          </Form.Item>
          <Space>
            <Form.Item name="context_len" label="上下文长度"><Input placeholder="128K" style={{ width: 120 }} /></Form.Item>
            <Form.Item name="max_input" label="最大输入token"><Input placeholder="64K" style={{ width: 120 }} /></Form.Item>
            <Form.Item name="max_output" label="最大输出token"><Input placeholder="64K" style={{ width: 120 }} /></Form.Item>
          </Space>
        </Form>
      </Modal>
    </div>
  )
}

export default function Settings() {
  return (
    <Card title="配置中心">
      <Tabs items={[
        { key: 'cred', label: '云平台凭证', children: <CredentialsTab /> },
        { key: 'models', label: '模型服务', children: <ModelsTab /> },
      ]} />
    </Card>
  )
}
