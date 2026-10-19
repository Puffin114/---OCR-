import { useEffect, useState } from 'react'
import { Modal, Table, Checkbox, Input, message } from 'antd'
import { api } from '../api'

const MODES = [
  { value: 'exact', label: '精确' },
  { value: 'trim_punct', label: '去空格标点' },
  { value: 'ignore_case', label: '忽略大小写' },
  { value: 'date_normalize', label: '日期归一化' },
  { value: 'number_normalize', label: '数字归一化' },
  { value: 'contains', label: '包含即算对' },
]

interface Props {
  open: boolean
  taskId: number
  fields: string[]
  onClose: () => void
  onSaved: () => void
}

export default function CriteriaEditor({ open, taskId, fields, onClose, onSaved }: Props) {
  const [rows, setRows] = useState<Record<string, { modes: string[]; regex: string }>>({})

  useEffect(() => {
    if (!open) return
    api.getCriteria(taskId).then((list: any[]) => {
      const base: any = {}
      fields.forEach(f => { base[f] = { modes: ['exact'], regex: '' } })
      list.forEach(it => { base[it.field] = { modes: it.modes || ['exact'], regex: it.regex || '' } })
      setRows(base)
    })
  }, [open, taskId, fields])

  async function save() {
    const items = fields.map(f => ({
      field: f, modes: rows[f]?.modes || ['exact'], regex: rows[f]?.regex || null,
    }))
    await api.saveCriteria(taskId, items)
    message.success('评测标准已保存')
    onSaved(); onClose()
  }

  return (
    <Modal open={open} title="自定义评测标准（按字段）" width={720}
      onCancel={onClose} onOk={save} okText="保存并重算">
      <Table rowKey="field" size="small" pagination={false}
        dataSource={fields.map(f => ({ field: f }))}
        columns={[
          { title: '字段', dataIndex: 'field', width: 110 },
          {
            title: '匹配规则（可多选）', render: (_, r) => (
              <Checkbox.Group options={MODES} value={rows[r.field]?.modes || ['exact']}
                onChange={(v) => setRows(s => ({ ...s, [r.field]: { ...s[r.field], modes: v as string[] } }))} />
            )
          },
          {
            title: '正则(可选)', width: 180, render: (_, r) => (
              <Input placeholder="如 \\d{4}" value={rows[r.field]?.regex || ''}
                onChange={e => setRows(s => ({ ...s, [r.field]: { ...s[r.field], regex: e.target.value } }))} />
            )
          },
        ]} />
    </Modal>
  )
}
