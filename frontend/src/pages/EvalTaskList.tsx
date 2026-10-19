import { useEffect, useState } from 'react'
import { Card, Table, Tag, Button, Space, message, Popconfirm, Modal, Input } from 'antd'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'

const STATUS: Record<string, any> = {
  running: <Tag color="processing">评测中</Tag>,
  success: <Tag color="success">评测成功</Tag>,
  failed: <Tag color="error">评测失败</Tag>,
  created: <Tag>已创建</Tag>,
}

export default function EvalTaskList() {
  const [tasks, setTasks] = useState<any[]>([])
  const [renameTarget, setRenameTarget] = useState<any>(null)
  const [renameValue, setRenameValue] = useState('')
  const nav = useNavigate()
  const refresh = () => api.listEvalTasks().then(setTasks)

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 4000)
    return () => clearInterval(t)
  }, [])

  return (
    <Card title="评测任务列表">
      <Table rowKey="id" dataSource={tasks} pagination={false}
        columns={[
          { title: 'ID', dataIndex: 'id', width: 60 },
          { title: '任务名称', dataIndex: 'name' },
          { title: '版本', dataIndex: 'version', width: 80 },
          { title: '状态', dataIndex: 'status', width: 110, render: v => STATUS[v] || v },
          { title: '信息', dataIndex: 'message', ellipsis: true },
          { title: '创建时间', dataIndex: 'created_at', width: 180 },
          {
            title: '操作', width: 300, render: (_, r) => (
              <Space>
                <Button size="small" type="link" onClick={() => nav(`/tasks/${r.id}`)}>详情</Button>
                <Button size="small" type="link" onClick={() => nav(`/datasets/${r.dataset_id}/new-task?copyFrom=${r.id}`)}>复制</Button>
                <Button size="small" type="link" onClick={() => { setRenameTarget(r); setRenameValue(r.name) }}>重命名</Button>
                <Popconfirm title="确认删除？" onConfirm={async () => { await api.deleteEvalTask(r.id); message.success('已删除'); refresh() }}>
                  <Button size="small" type="link" danger>删除</Button>
                </Popconfirm>
              </Space>
            )
          },
        ]} />
      <Modal open={!!renameTarget} title="重命名任务" okText="保存" cancelText="取消"
        onCancel={() => setRenameTarget(null)}
        onOk={async () => {
          const name = renameValue.trim()
          if (!name) { message.warning('名称不能为空'); return }
          await api.renameEvalTask(renameTarget.id, name)
          setRenameTarget(null); message.success('已重命名'); refresh()
        }}>
        <Input value={renameValue} onChange={e => setRenameValue(e.target.value)} placeholder="输入新的任务名称" />
      </Modal>
    </Card>
  )
}
